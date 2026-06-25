from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import ValidationError

from paperctl._support.fingerprints import (
    FingerprintError,
    PrerequisiteArtifact,
    SourceFile,
    build_stage_fingerprint,
)
from paperctl._support.hashing import canonical_json_hash
from paperctl._support.jsonio import dump_json_bytes, write_json_atomic
from paperctl._support.paths import is_repo_relative_posix
from paperctl._support.redaction import redact_value_for_key
from paperctl._support.schema import validate_artifact
from paperctl._support.sorting import posix_path_sort_key
from paperctl.adapters import ADAPTER_VERSIONS
from paperctl.adapters import (
    csv_adapter,
    json_adapter,
    jsonl_adapter,
    log_adapter,
    markdown_adapter,
    yaml_adapter,
)
from paperctl.inventory import (
    InventoryError,
    _inventory_artifacts,
    _inventory_fingerprint,
    _manifest_path,
    _validate_manifest_experiment_path_ancestors,
    load_manifest,
)


EVIDENCE_SCHEMA_VERSION = 1
NORMALIZE_STAGE_VERSION = 1
RECOGNIZED_REPORT_VERSION = 1


class NormalizeError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceWriteResult:
    experiment_path: str
    evidence_path: str
    status: str


@dataclass(frozen=True)
class NormalizeAllResult:
    manifest_path: str
    experiment_count: int
    created: int
    replaced: int
    unchanged: int
    results: list[EvidenceWriteResult]


@dataclass
class PacketParts:
    canonical_facts: list[dict[str, Any]]
    observed_values: list[dict[str, Any]]
    previews: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]
    unsupported_artifacts: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    reason_codes: set[str]
    redaction_count: int = 0
    execution_status: str = "unknown"
    adapter_versions: dict[str, str] = field(default_factory=dict)


def normalize_all(repo: Path, config: dict[str, Any], force: bool = False) -> NormalizeAllResult:
    repo = repo.resolve()
    try:
        manifest = load_manifest(repo, config)
    except InventoryError as exc:
        raise NormalizeError(str(exc)) from exc
    manifest_path = _manifest_path(config)
    _validate_canonical_experiment_keys(config, manifest)
    results = [
        normalize_one(repo, config, entry, manifest_path=manifest_path, force=force)
        for entry in manifest["experiments"]
    ]
    return NormalizeAllResult(
        manifest_path=manifest_path,
        experiment_count=len(results),
        created=sum(1 for result in results if result.status == "created"),
        replaced=sum(1 for result in results if result.status == "replaced"),
        unchanged=sum(1 for result in results if result.status == "unchanged"),
        results=results,
    )


def normalize_one(
    repo: Path,
    config: dict[str, Any],
    manifest_entry: dict[str, Any],
    *,
    manifest_path: str | None = None,
    force: bool = False,
) -> EvidenceWriteResult:
    repo = repo.resolve()
    manifest_path = manifest_path or _manifest_path(config)
    inventory = _load_fresh_inventory(repo, config, manifest_entry, manifest_path)
    packet = _build_packet(repo, config, manifest_entry, inventory, manifest_path)
    try:
        validate_artifact("evidence-packet.schema.json", packet)
    except ValidationError as exc:
        raise NormalizeError(
            f"invalid generated evidence for {manifest_entry['experiment_path']}: {exc.message}"
        ) from exc
    output_path = _resolve_evidence_output_path(repo, manifest_entry["evidence_path"])
    status = _write_evidence(output_path, packet, force=force)
    return EvidenceWriteResult(
        experiment_path=manifest_entry["experiment_path"],
        evidence_path=manifest_entry["evidence_path"],
        status=status,
    )


def _load_fresh_inventory(
    repo: Path,
    config: dict[str, Any],
    manifest_entry: dict[str, Any],
    manifest_path: str,
) -> dict[str, Any]:
    inventory_path = manifest_entry["inventory_path"]
    absolute_path = repo / inventory_path
    try:
        with absolute_path.open(encoding="utf-8") as handle:
            inventory = json.load(handle)
    except FileNotFoundError as exc:
        raise NormalizeError(
            f"missing artifact inventory: {inventory_path}; run paperctl inventory first"
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise NormalizeError(f"could not read artifact inventory: {inventory_path}: {exc}") from exc
    try:
        validate_artifact("artifact-inventory.schema.json", inventory)
    except ValidationError as exc:
        raise NormalizeError(
            f"invalid artifact inventory: {inventory_path}: {exc.message}"
        ) from exc
    if inventory["experiment_path"] != manifest_entry["experiment_path"]:
        raise NormalizeError(f"artifact inventory does not match manifest entry: {inventory_path}")

    expected = _expected_inventory(repo, config, manifest_entry, manifest_path)
    if dump_json_bytes(inventory) != dump_json_bytes(expected):
        raise NormalizeError(
            f"stale artifact inventory: {inventory_path}; run paperctl inventory --force first"
        )
    return inventory


def _expected_inventory(
    repo: Path,
    config: dict[str, Any],
    manifest_entry: dict[str, Any],
    manifest_path: str,
) -> dict[str, Any]:
    experiment_path = manifest_entry["experiment_path"]
    try:
        _validate_manifest_experiment_path_ancestors(repo, experiment_path)
        experiment_dir = repo / Path(*PurePosixPath(experiment_path).parts)
        if experiment_dir.is_symlink():
            raise InventoryError(f"manifest experiment path is a symlink: {experiment_path}")
        if not experiment_dir.is_dir():
            raise InventoryError(f"manifest experiment path is not a directory: {experiment_path}")
        artifacts = _inventory_artifacts(repo, experiment_dir)
        fingerprint = _inventory_fingerprint(
            repo=repo,
            config=config,
            manifest_path=manifest_path,
            artifacts=artifacts,
        )
    except (InventoryError, FingerprintError, OSError) as exc:
        raise NormalizeError(
            f"could not verify artifact inventory for {experiment_path}: {exc}"
        ) from exc
    return {
        "schema_version": 1,
        "artifact_type": "artifact_inventory",
        "question_path": manifest_entry["question_path"],
        "experiment_path": experiment_path,
        "fingerprint": fingerprint,
        "artifacts": artifacts,
    }


def _build_packet(
    repo: Path,
    config: dict[str, Any],
    manifest_entry: dict[str, Any],
    inventory: dict[str, Any],
    manifest_path: str,
) -> dict[str, Any]:
    parts = PacketParts(
        canonical_facts=[],
        observed_values=[],
        previews=[],
        diagnostics=[],
        conflicts=[],
        unsupported_artifacts=[],
        warnings=[],
        reason_codes=set(),
    )
    experiment_path = manifest_entry["experiment_path"]
    artifact_by_relative = {artifact["path"]: artifact for artifact in inventory["artifacts"]}
    excluded_observed_selectors: dict[str, set[str]] = {}
    _apply_default_reports(
        repo, config, experiment_path, artifact_by_relative, parts, excluded_observed_selectors
    )
    _apply_configured_canonical_facts(
        repo,
        config,
        experiment_path,
        artifact_by_relative,
        parts,
        excluded_observed_selectors,
    )
    _dedupe_canonical_facts(parts)
    _extract_artifacts(repo, config, inventory, parts, excluded_observed_selectors)
    _finalize_status(parts)
    fingerprint = _evidence_fingerprint(
        repo, config, manifest_entry, inventory, manifest_path, parts
    )
    packet = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "artifact_type": "evidence_packet",
        "question_path": manifest_entry["question_path"],
        "experiment_path": experiment_path,
        "inventory_path": manifest_entry["inventory_path"],
        "fingerprint": fingerprint,
        "preanalysis_disposition": parts.preanalysis_disposition,
        "execution_status": parts.execution_status,
        "evidence_status": parts.evidence_status,
        "reason_codes": sorted(parts.reason_codes),
        "counts": {
            "canonical_fact_count": len(parts.canonical_facts),
            "observed_value_count": len(parts.observed_values),
            "preview_count": len(parts.previews),
            "diagnostic_count": len(parts.diagnostics),
            "conflict_count": len(parts.conflicts),
            "unsupported_artifact_count": len(parts.unsupported_artifacts),
            "warning_count": len(parts.warnings),
            "redaction_count": parts.redaction_count,
        },
        "canonical_facts": sorted(parts.canonical_facts, key=_fact_sort_key),
        "observed_values": sorted(parts.observed_values, key=_observed_sort_key),
        "previews": sorted(parts.previews, key=_record_sort_key),
        "diagnostics": sorted(parts.diagnostics, key=_record_sort_key),
        "conflicts": sorted(parts.conflicts, key=lambda item: item["fact_id"]),
        "unsupported_artifacts": sorted(
            parts.unsupported_artifacts, key=lambda item: posix_path_sort_key(item["path"])
        ),
        "warnings": sorted(parts.warnings, key=_record_sort_key),
    }
    return packet


def _apply_default_reports(
    repo: Path,
    config: dict[str, Any],
    experiment_path: str,
    artifact_by_relative: dict[str, dict[str, Any]],
    parts: PacketParts,
    excluded_observed_selectors: dict[str, set[str]],
) -> None:
    for report_relative in config["evidence"]["default_canonical_artifacts"]:
        report_path = f"{experiment_path}/{report_relative}"
        artifact = artifact_by_relative.get(report_path)
        if artifact is None:
            continue
        if artifact["file_type"] != "regular" or artifact["kind"] != "json":
            continue
        _record_adapter(parts, "json")
        try:
            document = json_adapter.load(repo / report_path)
        except json_adapter.JsonAdapterError:
            parts.reason_codes.add("malformed_experiment_report")
            continue
        if not isinstance(document, dict) or "schema_version" not in document:
            continue
        if document.get("schema_version") != RECOGNIZED_REPORT_VERSION:
            parts.reason_codes.add("unknown_experiment_report_version")
            continue
        try:
            validate_artifact("experiment-report.schema.json", document)
        except ValidationError:
            parts.reason_codes.add("malformed_experiment_report")
            continue
        if "execution_status" in document:
            parts.execution_status = document["execution_status"]
        source_ids: set[str] = set()
        for fact in document["canonical_facts"]:
            if fact["fact_id"] in source_ids:
                parts.reason_codes.add("duplicate_fact_id_in_source")
                continue
            source_ids.add(fact["fact_id"])
            result = _canonical_from_report_fact(repo, experiment_path, fact, artifact_by_relative)
            if isinstance(result, str):
                parts.reason_codes.add(result)
                continue
            result, redactions = _redact_canonical_fact(result)
            parts.redaction_count += redactions
            if redactions:
                parts.warnings.append(_redaction_warning(result["source"], redactions))
            parts.canonical_facts.append(result)
            _exclude_selector(
                excluded_observed_selectors, result["source"]["path"], result["source"]["selector"]
            )
        excluded_observed_selectors.setdefault(report_path, set()).update(
            {"/schema_version", "/execution_status", "/canonical_facts"}
        )


def _canonical_from_report_fact(
    repo: Path,
    experiment_path: str,
    fact: dict[str, Any],
    artifact_by_relative: dict[str, dict[str, Any]],
) -> dict[str, Any] | str:
    source = fact["source"]
    source_path = _experiment_source_path(experiment_path, source["path"])
    artifact = artifact_by_relative.get(source_path)
    if artifact is None or artifact["file_type"] != "regular":
        return "source_contract_selector_missing"
    try:
        document = _load_structured_source(repo / source_path, artifact["kind"])
        selected = json_adapter.resolve_pointer(document, source["selector"])
    except (ValueError, KeyError, json_adapter.JsonAdapterError, yaml_adapter.YamlAdapterError):
        return "source_contract_selector_missing"
    if json_adapter.is_non_finite_number(selected) or json_adapter.is_non_finite_number(
        fact["value"]
    ):
        return "source_contract_type_mismatch"
    if not json_adapter.is_expected_type(selected, fact["value_type"]):
        return "source_contract_type_mismatch"
    if selected != fact["value"]:
        return "source_contract_value_mismatch"
    return {
        "fact_id": fact["fact_id"],
        "value": selected,
        "value_type": fact["value_type"],
        "unit": fact["unit"],
        "source": _value_source(
            source_path, artifact["sha256"], source["selector"], artifact["kind"]
        ),
    }


def _apply_configured_canonical_facts(
    repo: Path,
    config: dict[str, Any],
    experiment_path: str,
    artifact_by_relative: dict[str, dict[str, Any]],
    parts: PacketParts,
    excluded_observed_selectors: dict[str, set[str]],
) -> None:
    mappings = config["evidence"]["canonical_facts"].get(experiment_path, [])
    seen_fact_ids: set[str] = set()
    for mapping in mappings:
        fact_id = mapping["fact_id"]
        if fact_id in seen_fact_ids:
            raise NormalizeError(
                f"duplicate configured canonical fact id: {experiment_path}: {fact_id}"
            )
        seen_fact_ids.add(fact_id)
        source_path = _validate_configured_source_path(repo, experiment_path, mapping["source"])
        artifact = artifact_by_relative.get(source_path)
        if artifact is None or artifact["file_type"] != "regular":
            raise NormalizeError(f"canonical source file does not exist: {source_path}")
        _record_adapter(parts, "yaml" if artifact["kind"] == "yaml" else "json")
        try:
            document = _load_structured_source(repo / source_path, artifact["kind"])
            selected = json_adapter.resolve_pointer(document, mapping["selector"])
        except (
            ValueError,
            KeyError,
            json_adapter.JsonAdapterError,
            yaml_adapter.YamlAdapterError,
        ) as exc:
            raise NormalizeError(
                f"canonical selector did not resolve: {source_path} {mapping['selector']}"
            ) from exc
        if not json_adapter.is_expected_type(selected, mapping["expected_type"]):
            if json_adapter.is_non_finite_number(selected):
                raise NormalizeError(
                    f"non-finite numeric value in canonical source: "
                    f"{source_path} {mapping['selector']}"
                )
            raise NormalizeError(
                f"canonical selector type mismatch: {source_path} {mapping['selector']}"
            )
        if isinstance(selected, dict | list):
            raise NormalizeError(
                f"canonical selector type mismatch: {source_path} {mapping['selector']}"
            )
        fact = {
            "fact_id": fact_id,
            "value": selected,
            "value_type": _canonical_value_type(selected, mapping["expected_type"]),
            "unit": mapping.get("unit"),
            "source": _value_source(
                source_path, artifact["sha256"], mapping["selector"], artifact["kind"]
            ),
        }
        fact, redactions = _redact_canonical_fact(fact)
        parts.redaction_count += redactions
        if redactions:
            parts.warnings.append(_redaction_warning(fact["source"], redactions))
        parts.canonical_facts.append(fact)
        _exclude_selector(excluded_observed_selectors, source_path, mapping["selector"])


def _dedupe_canonical_facts(parts: PacketParts) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for fact in parts.canonical_facts:
        grouped.setdefault(fact["fact_id"], []).append(fact)
    canonical: list[dict[str, Any]] = []
    for fact_id in sorted(grouped):
        facts = grouped[fact_id]
        signatures = {
            canonical_json_hash(
                {
                    "value": fact["value"],
                    "value_type": fact["value_type"],
                    "unit": fact["unit"],
                }
            )
            for fact in facts
        }
        if len(signatures) > 1:
            parts.reason_codes.add("canonical_conflict")
            parts.conflicts.append(
                {
                    "reason_code": "canonical_conflict",
                    "fact_id": fact_id,
                    "sources": [fact["source"] for fact in facts],
                }
            )
            canonical.extend(facts)
            continue
        canonical.append(sorted(facts, key=lambda fact: _source_sort_key(fact["source"]))[0])
    parts.canonical_facts = canonical


def _extract_artifacts(
    repo: Path,
    config: dict[str, Any],
    inventory: dict[str, Any],
    parts: PacketParts,
    excluded_observed_selectors: dict[str, set[str]],
) -> None:
    limits = config["evidence"]["extraction_limits"]
    for artifact in inventory["artifacts"]:
        if artifact["file_type"] != "regular":
            parts.unsupported_artifacts.append(
                {"path": artifact["path"], "reason_code": "unsupported_only"}
            )
            continue
        if artifact["kind"] in {"binary", "unknown"}:
            parts.unsupported_artifacts.append(
                {"path": artifact["path"], "reason_code": "unsupported_only"}
            )
            continue
        path = repo / artifact["path"]
        maximum_file_bytes = limits["maximum_file_bytes"]
        over_byte_limit = artifact["byte_size"] > maximum_file_bytes
        if over_byte_limit:
            parts.reason_codes.add("normalization_truncated")
        if artifact["kind"] in {"json", "yaml"}:
            if over_byte_limit:
                parts.warnings.append(_byte_limit_warning(artifact, inspected_byte_count=0))
                continue
            _record_adapter(parts, artifact["kind"])
            module = json_adapter if artifact["kind"] == "json" else yaml_adapter
            try:
                document = module.load(path)
            except (json_adapter.JsonAdapterError, yaml_adapter.YamlAdapterError) as exc:
                parts.warnings.append(
                    _none_record(artifact, f"could not parse {artifact['kind']}: {exc}")
                )
                continue
            observations, warnings, redactions, truncated = module.scalar_observations(
                document,
                source_path=artifact["path"],
                source_hash=artifact["sha256"],
                limit=limits["maximum_scalar_observations_per_file"],
                max_depth=limits["maximum_nesting_depth"],
                excluded_selectors=excluded_observed_selectors.get(artifact["path"], set()),
            )
            parts.observed_values.extend(observations)
            parts.warnings.extend(warnings)
            parts.redaction_count += redactions
            if redactions:
                parts.warnings.append(_redaction_warning(_none_source(artifact), redactions))
            if truncated:
                parts.reason_codes.add("normalization_truncated")
            continue
        if artifact["kind"] in {"csv", "markdown"} and over_byte_limit:
            parts.warnings.append(_byte_limit_warning(artifact, inspected_byte_count=0))
            continue
        max_bytes = maximum_file_bytes if over_byte_limit else None
        if artifact["kind"] == "csv":
            _record_adapter(parts, "csv")
            previews, diagnostics, warnings, redactions = csv_adapter.extract(
                path,
                source_path=artifact["path"],
                source_hash=artifact["sha256"],
                preview_rows=limits["preview_rows"],
                max_bytes=max_bytes,
            )
        elif artifact["kind"] == "jsonl":
            _record_adapter(parts, "jsonl")
            previews, diagnostics, warnings, redactions = jsonl_adapter.extract(
                path,
                source_path=artifact["path"],
                source_hash=artifact["sha256"],
                preview_rows=limits["preview_rows"],
                max_bytes=max_bytes,
            )
        elif artifact["kind"] == "markdown":
            _record_adapter(parts, "markdown")
            previews, diagnostics, warnings, redactions = markdown_adapter.extract(
                path,
                source_path=artifact["path"],
                source_hash=artifact["sha256"],
                preview_lines=limits["log_head_lines"],
                max_bytes=max_bytes,
            )
        else:
            _record_adapter(parts, "log")
            previews, diagnostics, warnings, redactions = log_adapter.extract(
                path,
                source_path=artifact["path"],
                source_hash=artifact["sha256"],
                head_lines=limits["log_head_lines"],
                tail_lines=limits["log_tail_lines"],
                max_bytes=max_bytes,
            )
        parts.previews.extend(previews)
        parts.diagnostics.extend(diagnostics)
        parts.warnings.extend(warnings)
        parts.redaction_count += redactions
        if redactions:
            parts.warnings.append(_redaction_warning(_none_source(artifact), redactions))


def _finalize_status(parts: PacketParts) -> None:
    blocker_codes = {
        "malformed_experiment_report",
        "unknown_experiment_report_version",
        "source_contract_selector_missing",
        "source_contract_type_mismatch",
        "source_contract_value_mismatch",
        "duplicate_fact_id_in_source",
    }
    if "canonical_conflict" in parts.reason_codes:
        parts.evidence_status = "conflicting"
        parts.preanalysis_disposition = "needs_human_review"
        return
    usable = bool(
        parts.canonical_facts or parts.observed_values or parts.previews or parts.diagnostics
    )
    if usable:
        parts.evidence_status = "available"
    elif parts.unsupported_artifacts:
        parts.evidence_status = "unsupported"
        parts.reason_codes.add("unsupported_only")
    else:
        parts.evidence_status = "missing"
        parts.reason_codes.add("no_usable_evidence")
    parts.preanalysis_disposition = (
        "blocked"
        if blocker_codes.intersection(parts.reason_codes)
        or parts.evidence_status in {"missing", "unsupported"}
        else "analysis_candidate"
    )


def _evidence_fingerprint(
    repo: Path,
    config: dict[str, Any],
    manifest_entry: dict[str, Any],
    inventory: dict[str, Any],
    manifest_path: str,
    parts: PacketParts,
) -> dict[str, Any]:
    inspected_paths = {
        artifact["path"]
        for artifact in inventory["artifacts"]
        if artifact["file_type"] == "regular" and artifact["kind"] not in {"binary", "unknown"}
    }
    return build_stage_fingerprint(
        stage_name="normalize",
        stage_version=NORMALIZE_STAGE_VERSION,
        schema_version=EVIDENCE_SCHEMA_VERSION,
        relevant_config=_relevant_config(config),
        source_files=[
            SourceFile(path=path, file=repo / path)
            for path in sorted(inspected_paths, key=posix_path_sort_key)
        ],
        prerequisite_artifacts=[
            PrerequisiteArtifact(
                path=manifest_path,
                file=repo / manifest_path,
                schema_name="manifest.schema.json",
            ),
            PrerequisiteArtifact(
                path=manifest_entry["inventory_path"],
                file=repo / manifest_entry["inventory_path"],
                schema_name="artifact-inventory.schema.json",
            ),
        ],
        extra_inputs={
            "adapter_versions": dict(sorted(parts.adapter_versions.items())),
            "canonical_fact_count": len(parts.canonical_facts),
            "reason_codes": sorted(parts.reason_codes),
        },
    )


def _record_adapter(parts: PacketParts, adapter: str) -> None:
    parts.adapter_versions[adapter] = ADAPTER_VERSIONS[adapter]


def _relevant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence": config["evidence"],
        "paper": {"work_directory": config["paper"]["work_directory"]},
    }


def _load_structured_source(path: Path, kind: str) -> Any:
    if kind == "json":
        return json_adapter.load(path)
    if kind == "yaml":
        return yaml_adapter.load(path)
    raise ValueError(f"canonical source must be JSON or YAML, got {kind}")


def _validate_configured_source_path(repo: Path, experiment_path: str, source: str) -> str:
    if not is_repo_relative_posix(source):
        raise NormalizeError(f"configured path must be repo-relative POSIX: {source!r}")
    relative = _experiment_source_path(experiment_path, source)
    untrusted_path = repo / Path(*PurePosixPath(relative).parts)
    if untrusted_path.is_symlink():
        try:
            resolved = untrusted_path.resolve(strict=True)
        except OSError as exc:
            raise NormalizeError(
                f"canonical source symlink cannot be resolved: {relative}"
            ) from exc
        try:
            resolved.relative_to(repo)
        except ValueError as exc:
            raise NormalizeError(
                f"canonical source resolves outside repository: {relative}"
            ) from exc
    return relative


def _validate_canonical_experiment_keys(config: dict[str, Any], manifest: dict[str, Any]) -> None:
    valid_paths = {entry["experiment_path"] for entry in manifest["experiments"]}
    for experiment_path in config["evidence"]["canonical_facts"]:
        if experiment_path not in valid_paths:
            raise NormalizeError(
                f"configured canonical experiment does not exist: {experiment_path}"
            )


def _experiment_source_path(experiment_path: str, source: str) -> str:
    if not is_repo_relative_posix(source):
        raise NormalizeError(f"configured path must be repo-relative POSIX: {source!r}")
    return f"{experiment_path}/{source}"


def _value_source(source_path: str, source_hash: str, selector: str, kind: str) -> dict[str, Any]:
    adapter = "yaml" if kind == "yaml" else "json"
    return {
        "path": source_path,
        "source_hash": source_hash,
        "selector_type": "json_pointer",
        "selector": selector,
        "adapter": adapter,
        "adapter_version": ADAPTER_VERSIONS[adapter],
    }


def _exclude_selector(excluded: dict[str, set[str]], source_path: str, selector: str) -> None:
    excluded.setdefault(source_path, set()).add(selector)


def _canonical_value_type(value: Any, expected_type: str) -> str:
    if expected_type in {"string", "number", "integer", "boolean", "null"}:
        return expected_type
    return json_adapter.value_type(value)


def _redact_canonical_fact(fact: dict[str, Any]) -> tuple[dict[str, Any], int]:
    value, count = redact_value_for_key(_selector_leaf(fact["source"]["selector"]), fact["value"])
    if count == 0:
        return fact, 0
    redacted = dict(fact)
    redacted["value"] = value
    redacted["value_type"] = json_adapter.value_type(value)
    return redacted, count


def _selector_leaf(selector: str) -> str:
    if selector == "":
        return ""
    leaf = selector.rsplit("/", 1)[-1]
    return leaf.replace("~1", "/").replace("~0", "~")


def _none_record(artifact: dict[str, Any], message: str, **fields: Any) -> dict[str, Any]:
    return {"source": _none_source(artifact), "message": message, **fields}


def _byte_limit_warning(artifact: dict[str, Any], *, inspected_byte_count: int) -> dict[str, Any]:
    omitted_byte_count = max(0, artifact["byte_size"] - inspected_byte_count)
    return _none_record(
        artifact,
        "file exceeded extraction byte limit",
        warning_type="byte_limit_truncated",
        inspected_byte_count=inspected_byte_count,
        omitted_byte_count=omitted_byte_count,
    )


def _none_source(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": artifact["path"],
        "source_hash": artifact.get("sha256"),
        "selector_type": "none",
        "selector": None,
        "adapter": artifact["kind"],
        "adapter_version": ADAPTER_VERSIONS.get(artifact["kind"], "1"),
    }


def _redaction_warning(source: dict[str, Any], redaction_count: int) -> dict[str, Any]:
    return {
        "source": dict(source),
        "message": f"redacted {redaction_count} secret-like value(s)",
        "warning_type": "redaction",
        "redaction_category": "secret_like",
        "redaction_count": redaction_count,
    }


def _resolve_evidence_output_path(repo: Path, path: str) -> Path:
    if not is_repo_relative_posix(path):
        raise NormalizeError(f"manifest path must be repo-relative POSIX: {path}")
    current = repo
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            relative = current.relative_to(repo).as_posix()
            if index == len(parts) - 1:
                raise NormalizeError(f"evidence output path is a symlink: {path}")
            raise NormalizeError(f"evidence output path contains a symlink: {relative}")
        if not current.exists():
            break
    return repo / Path(*parts)


def _write_evidence(output_path: Path, packet: dict[str, Any], *, force: bool) -> str:
    new_bytes = dump_json_bytes(packet)
    if output_path.exists() and not force:
        try:
            if output_path.read_bytes() == new_bytes:
                return "unchanged"
        except OSError as exc:
            raise NormalizeError(f"could not read existing evidence: {output_path}: {exc}") from exc
    status = "replaced" if output_path.exists() else "created"
    try:
        write_json_atomic(output_path, packet)
    except OSError as exc:
        raise NormalizeError(f"could not write evidence: {output_path}: {exc}") from exc
    return status


def _fact_sort_key(fact: dict[str, Any]) -> tuple[Any, ...]:
    return (fact["fact_id"], *_source_sort_key(fact["source"]))


def _observed_sort_key(value: dict[str, Any]) -> tuple[Any, ...]:
    return _source_sort_key(value["source"])


def _record_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return _source_sort_key(record["source"])


def _source_sort_key(source: dict[str, Any]) -> tuple[Any, ...]:
    path = source["path"]
    selector = source.get("selector") or ""
    line_start = source.get("line_start") or 0
    line_end = source.get("line_end") or 0
    return (*posix_path_sort_key(path), selector, line_start, line_end)
