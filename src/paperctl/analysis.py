from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, NamedTuple

from jsonschema import ValidationError

from paperctl import config as config_module
from paperctl._support.fingerprints import (
    PrerequisiteArtifact,
    SourceFile,
    build_stage_fingerprint,
)
from paperctl._support.hashing import canonical_json_hash, sha256_bytes, sha256_file
from paperctl._support.jsonio import dump_json_bytes, write_json_atomic
from paperctl._support.paths import is_repo_relative_posix
from paperctl._support.redaction import redact_text
from paperctl._support.schema import (
    load_schema,
    validate_analysis_state_integrity,
    validate_artifact,
)
from paperctl.analysis_backends import AnalysisBackendResult, AnalysisJob
from paperctl.analysis_prompt import (
    PROMPT_BUILDER_VERSION,
    build_analysis_prompt,
    prompt_template_hash,
)
from paperctl.analysis_validation import (
    ANALYSIS_VALIDATION_VERSION,
    AnalysisDiagnostic,
    validate_analysis_claims,
)
from paperctl.formula import FORMULA_EVALUATOR_VERSION


class AnalysisError(ValueError):
    pass


@dataclass(frozen=True)
class AnalyzeResult:
    experiment_path: str
    analysis_path: str | None
    status: Literal["accepted", "failed", "preflight_failed"]
    diagnostic_codes: list[str]


class _PathResult(NamedTuple):
    path: str | None
    diagnostic_code: str | None


class _ParseResult(NamedTuple):
    analysis: dict[str, Any] | None
    diagnostic: dict[str, Any] | None


_CODEX_CAPABILITY_CODES = {
    "codex_missing_dependency",
    "codex_capability_missing",
    "codex_help_failed",
    "codex_launch_failed",
    "codex_temp_dir_unavailable",
}
_MAX_PREVIEW_CHARS = 4000
_MAX_DIAGNOSTICS = 20
_MAX_DIAGNOSTIC_MESSAGE_CHARS = 1000
_MAX_DIAGNOSTIC_DETAIL_BYTES = 4000


def analyze_experiment(
    repo: Path,
    experiment: str,
    backend: object | None = None,
    backend_options_override: dict[str, Any] | None = None,
    timeout_seconds_override: int | None = None,
) -> AnalyzeResult:
    if timeout_seconds_override is not None and timeout_seconds_override <= 0:
        raise AnalysisError("timeout_seconds_override must be positive")
    repo = repo.resolve()
    config = config_module.load_config(repo)
    manifest_path = f"{config['paper']['work_directory']}/manifest.json"

    manifest_result = _load_manifest(repo, config)
    if isinstance(manifest_result, str):
        return _preflight_failed(experiment, manifest_result)
    manifest = manifest_result

    entry_result = _resolve_manifest_entry(manifest, experiment)
    if isinstance(entry_result, str):
        return _preflight_failed(experiment, entry_result)
    manifest_entry = entry_result

    inventory_result = _load_inventory(repo, config, manifest_entry, manifest_path)
    if isinstance(inventory_result, str):
        return _preflight_failed(experiment, inventory_result)
    inventory = inventory_result

    evidence_result = _load_evidence(repo, manifest_entry)
    if isinstance(evidence_result, str):
        return _preflight_failed(experiment, evidence_result)
    evidence_packet = evidence_result

    freshness_code = _evidence_freshness_diagnostic(
        repo, config, manifest_entry, inventory, manifest_path, evidence_packet
    )
    if freshness_code is not None:
        return _preflight_failed(experiment, freshness_code)

    disposition_code = _disposition_diagnostic(evidence_packet)
    if disposition_code is not None:
        return _preflight_failed(experiment, disposition_code)

    if not _has_claimable_structured_evidence(evidence_packet):
        return _preflight_failed(experiment, "no_claimable_structured_evidence")

    analysis_path_result = _analysis_output_path(repo, config, experiment)
    if analysis_path_result.diagnostic_code is not None:
        return _preflight_failed(experiment, analysis_path_result.diagnostic_code)
    analysis_path = analysis_path_result.path
    if analysis_path is None:
        raise AnalysisError("analysis output path resolution returned no path or diagnostic")

    if backend is not None:
        return _run_backend_analysis(
            repo=repo,
            config=config,
            manifest_path=manifest_path,
            manifest_entry=manifest_entry,
            inventory=inventory,
            evidence_packet=evidence_packet,
            analysis_path=analysis_path,
            backend=backend,
            backend_options_override=backend_options_override,
            timeout_seconds_override=timeout_seconds_override,
        )

    return AnalyzeResult(
        experiment_path=experiment,
        analysis_path=analysis_path,
        status="failed",
        diagnostic_codes=["analysis_not_run"],
    )


def _preflight_failed(experiment: str, diagnostic_code: str) -> AnalyzeResult:
    return AnalyzeResult(
        experiment_path=experiment,
        analysis_path=None,
        status="preflight_failed",
        diagnostic_codes=[diagnostic_code],
    )


def _load_manifest(repo: Path, config: dict) -> dict | str:
    from paperctl import inventory as inventory_module
    from paperctl.inventory import InventoryError

    try:
        return inventory_module.load_manifest(repo, config)
    except InventoryError as exc:
        message = str(exc)
        if message.startswith("missing discovery manifest"):
            return "missing_manifest"
        if message.startswith("stale discovery manifest"):
            return "stale_manifest"
        return "malformed_manifest"


def _resolve_manifest_entry(manifest: dict, experiment: str) -> dict | str:
    matches = [
        entry
        for entry in manifest.get("experiments", [])
        if entry.get("experiment_path") == experiment
    ]
    if not matches:
        return "experiment_not_found"
    if len(matches) > 1:
        return "duplicate_experiment"
    return matches[0]


def _load_inventory(
    repo: Path, config: dict, manifest_entry: dict, manifest_path: str
) -> dict | str:
    from paperctl.normalize import NormalizeError, _load_fresh_inventory

    try:
        return _load_fresh_inventory(repo, config, manifest_entry, manifest_path)
    except NormalizeError as exc:
        message = str(exc)
        if message.startswith("missing artifact inventory"):
            return "missing_inventory"
        if message.startswith("stale artifact inventory"):
            return "stale_inventory"
        return "malformed_inventory"


def _load_evidence(repo: Path, manifest_entry: dict) -> dict | str:
    from paperctl._support.schema import validate_artifact

    evidence_path = manifest_entry["evidence_path"]
    try:
        with (repo / evidence_path).open(encoding="utf-8") as handle:
            packet = json.load(handle)
    except FileNotFoundError:
        return "missing_evidence"
    except (OSError, json.JSONDecodeError):
        return "malformed_evidence"

    try:
        validate_artifact("evidence-packet.schema.json", packet)
    except ValidationError:
        return "malformed_evidence"
    return packet


def _evidence_freshness_diagnostic(
    repo: Path,
    config: dict,
    manifest_entry: dict,
    inventory: dict,
    manifest_path: str,
    evidence_packet: dict,
) -> str | None:
    from paperctl._support.jsonio import dump_json_bytes
    from paperctl.normalize import NormalizeError, _build_packet

    try:
        expected = _build_packet(repo, config, manifest_entry, inventory, manifest_path)
    except NormalizeError:
        return "stale_evidence"
    if dump_json_bytes(evidence_packet) != dump_json_bytes(expected):
        return "stale_evidence"
    return None


def _disposition_diagnostic(evidence_packet: dict) -> str | None:
    disposition = evidence_packet.get("preanalysis_disposition")
    if disposition == "analysis_candidate":
        return None
    if disposition == "blocked":
        return "blocked_experiment"
    if disposition == "needs_human_review":
        return "needs_human_review"
    return "non_candidate_experiment"


def _has_claimable_structured_evidence(evidence_packet: dict) -> bool:
    for collection_name in ("canonical_facts", "observed_values"):
        for item in evidence_packet.get(collection_name, []):
            source = item.get("source", {})
            if source.get("selector_type") == "json_pointer" and source.get("adapter") in {
                "json",
                "yaml",
            }:
                return True
    return False


def _run_backend_analysis(
    *,
    repo: Path,
    config: dict[str, Any],
    manifest_path: str,
    manifest_entry: dict[str, Any],
    inventory: dict[str, Any],
    evidence_packet: dict[str, Any],
    analysis_path: str,
    backend: object,
    backend_options_override: dict[str, Any] | None = None,
    timeout_seconds_override: int | None = None,
) -> AnalyzeResult:
    experiment_path = manifest_entry["experiment_path"]
    question_path = manifest_entry["question_path"]
    inventory_path = manifest_entry["inventory_path"]
    evidence_path = manifest_entry["evidence_path"]
    question_readme_path, question_readme_hash = _question_readme_metadata(repo, manifest_entry)
    prompt = build_analysis_prompt(
        {
            "question_path": question_path,
            "question_readme_path": question_readme_path,
            "question_readme_hash": question_readme_hash,
            "experiment_path": experiment_path,
            "inventory_path": inventory_path,
            "evidence_packet_path": evidence_path,
            "output_schema_name": "experiment-analysis.schema.json",
        },
        evidence_packet,
    )
    backend_options = _effective_backend_options(config, backend_options_override)
    timeout_seconds = _effective_timeout_seconds(config, timeout_seconds_override)
    job = AnalysisJob(
        repo=repo,
        config=config,
        question_path=question_path,
        question_readme_path=question_readme_path,
        question_readme_hash=question_readme_hash,
        experiment_path=experiment_path,
        inventory_path=inventory_path,
        evidence_path=evidence_path,
        output_schema_path=_schema_resource_path("experiment-analysis.schema.json"),
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        backend_options=backend_options,
    )
    result = backend.analyze(job)
    if not isinstance(result, AnalysisBackendResult):
        result = AnalysisBackendResult(
            backend_name=str(getattr(backend, "name", "unknown")),
            status="failed",
            raw_response=None,
            return_code=None,
            stdout=None,
            stderr="backend returned an invalid result object",
        )

    capability_code = _codex_capability_code(result)
    if capability_code is not None:
        return AnalyzeResult(
            experiment_path=experiment_path,
            analysis_path=analysis_path,
            status="failed",
            diagnostic_codes=[capability_code],
        )

    analysis, diagnostics = _analysis_and_diagnostics_from_backend_result(
        repo=repo,
        manifest_entry=manifest_entry,
        evidence_packet=evidence_packet,
        backend_result=result,
    )
    status: Literal["accepted", "failed"] = "accepted" if analysis is not None else "failed"
    state = _build_analysis_state(
        repo=repo,
        config=config,
        manifest_path=manifest_path,
        manifest_entry=manifest_entry,
        inventory=inventory,
        evidence_packet=evidence_packet,
        analysis_path=analysis_path,
        backend_result=result,
        diagnostics=diagnostics,
        analysis=analysis,
        question_readme_path=question_readme_path,
        question_readme_hash=question_readme_hash,
        backend_options=backend_options,
        timeout_seconds=timeout_seconds,
        status=status,
    )
    validate_artifact("analysis-state.schema.json", state)
    validate_analysis_state_integrity(state)
    write_json_atomic(repo / analysis_path, state)
    return AnalyzeResult(
        experiment_path=experiment_path,
        analysis_path=analysis_path,
        status=status,
        diagnostic_codes=[diagnostic["code"] for diagnostic in state["diagnostics"]],
    )


def _analysis_and_diagnostics_from_backend_result(
    *,
    repo: Path,
    manifest_entry: dict[str, Any],
    evidence_packet: dict[str, Any],
    backend_result: AnalysisBackendResult,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if backend_result.status == "failed":
        return None, [
            _diagnostic(
                "backend_failure",
                _backend_failure_message(backend_result),
                detail=_backend_result_detail(backend_result),
            )
        ]
    if backend_result.status == "timed_out":
        return None, [
            _diagnostic(
                "backend_timeout",
                "Analysis backend timed out.",
                detail=_backend_result_detail(backend_result),
            )
        ]

    parse_result = _parse_backend_response(backend_result.raw_response)
    if parse_result.analysis is not None:
        analysis = parse_result.analysis
        try:
            validate_artifact("experiment-analysis.schema.json", analysis)
        except ValidationError as exc:
            return None, [
                _diagnostic(
                    "schema_failure",
                    "Backend response does not match experiment-analysis.schema.json.",
                    detail=_schema_validation_detail(exc),
                )
            ]
        claim_diagnostics = validate_analysis_claims(
            repo=repo,
            manifest_entry=manifest_entry,
            evidence_packet=evidence_packet,
            analysis=analysis,
        )
        if claim_diagnostics:
            return None, [
                _diagnostic(
                    "claim_validation_failure",
                    "Backend response failed deterministic claim validation.",
                    detail={
                        "diagnostic_codes": [
                            item.code for item in claim_diagnostics[:_MAX_DIAGNOSTICS]
                        ],
                        "diagnostic_count": len(claim_diagnostics),
                        "diagnostics": [
                            _diagnostic_from_dataclass(item) for item in claim_diagnostics
                        ],
                    },
                )
            ]
        return analysis, []
    assert parse_result.diagnostic is not None
    return None, [parse_result.diagnostic]


def _parse_backend_response(raw_response: bytes | None) -> _ParseResult:
    if raw_response is None or raw_response == b"":
        return _ParseResult(
            None, _diagnostic("empty_output", "Analysis backend response body was empty.")
        )
    try:
        text = raw_response.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _ParseResult(
            None,
            _diagnostic(
                "invalid_utf8",
                "Analysis backend response body was not valid UTF-8.",
                detail={"start": exc.start, "reason": exc.reason},
            ),
        )
    if text.strip() == "":
        return _ParseResult(
            None, _diagnostic("empty_output", "Analysis backend response body was empty.")
        )
    decoder = json.JSONDecoder()
    start = _first_non_whitespace_index(text)
    try:
        value, end = decoder.raw_decode(text, start)
    except json.JSONDecodeError as exc:
        return _ParseResult(
            None,
            _diagnostic(
                "invalid_json",
                "Analysis backend response body was not valid JSON.",
                detail={"line": exc.lineno, "column": exc.colno, "position": exc.pos},
            ),
        )
    if text[end:].strip():
        return _ParseResult(
            None,
            _diagnostic(
                "concatenated_json",
                "Analysis backend response body contained content after the first JSON object.",
            ),
        )
    if not isinstance(value, dict):
        return _ParseResult(
            None,
            _diagnostic(
                "non_object_json",
                "Analysis backend response body must contain one top-level JSON object.",
            ),
        )
    return _ParseResult(value, None)


def _first_non_whitespace_index(text: str) -> int:
    for index, char in enumerate(text):
        if not char.isspace():
            return index
    return 0


def _schema_validation_detail(exc: ValidationError) -> dict[str, Any]:
    return {
        "validator": str(exc.validator),
        "path": list(exc.path),
        "schema_path": list(exc.schema_path),
    }


def _build_analysis_state(
    *,
    repo: Path,
    config: dict[str, Any],
    manifest_path: str,
    manifest_entry: dict[str, Any],
    inventory: dict[str, Any],
    evidence_packet: dict[str, Any],
    analysis_path: str,
    backend_result: AnalysisBackendResult,
    diagnostics: list[dict[str, Any]],
    analysis: dict[str, Any] | None,
    question_readme_path: str | None,
    question_readme_hash: str | None,
    backend_options: dict[str, Any],
    timeout_seconds: int,
    status: Literal["accepted", "failed"],
) -> dict[str, Any]:
    raw_output_sha256 = (
        sha256_bytes(backend_result.raw_response)
        if backend_result.raw_response is not None and len(backend_result.raw_response) > 0
        else None
    )
    sanitized_diagnostics = [_sanitize_diagnostic(item) for item in diagnostics][:_MAX_DIAGNOSTICS]
    fingerprint = _analysis_fingerprint(
        repo=repo,
        config=config,
        manifest_path=manifest_path,
        manifest_entry=manifest_entry,
        inventory=inventory,
        evidence_packet=evidence_packet,
        analysis=analysis,
        diagnostics=sanitized_diagnostics,
        backend_result=backend_result,
        backend_options=backend_options,
        timeout_seconds=timeout_seconds,
        raw_output_sha256=raw_output_sha256,
        question_readme_path=question_readme_path,
        question_readme_hash=question_readme_hash,
    )
    return {
        "schema_version": 1,
        "artifact_type": "analysis_state",
        "status": status,
        "question_path": manifest_entry["question_path"],
        "experiment_path": manifest_entry["experiment_path"],
        "analysis_path": analysis_path,
        "fingerprint": fingerprint,
        "backend": {
            "name": backend_result.backend_name,
            "status": backend_result.status,
            "return_code": backend_result.return_code,
            "stdout_preview": _preview_text(backend_result.stdout),
            "stderr_preview": _preview_text(backend_result.stderr),
            "token_usage": backend_result.token_usage,
        },
        "diagnostics": sanitized_diagnostics,
        "analysis": analysis if status == "accepted" else None,
        "raw_output_sha256": raw_output_sha256,
    }


def _analysis_fingerprint(
    *,
    repo: Path,
    config: dict[str, Any],
    manifest_path: str,
    manifest_entry: dict[str, Any],
    inventory: dict[str, Any],
    evidence_packet: dict[str, Any],
    analysis: dict[str, Any] | None,
    diagnostics: list[dict[str, Any]],
    backend_result: AnalysisBackendResult,
    backend_options: dict[str, Any],
    timeout_seconds: int,
    raw_output_sha256: str | None,
    question_readme_path: str | None,
    question_readme_hash: str | None,
) -> dict[str, Any]:
    source_files = _analysis_source_files(
        repo=repo,
        analysis=analysis,
        question_readme_path=question_readme_path,
        question_readme_hash=question_readme_hash,
    )
    extra_inputs = {
        "analysis_state_schema_sha256": canonical_json_hash(
            load_schema("analysis-state.schema.json")
        ),
        "experiment_analysis_schema_sha256": canonical_json_hash(
            load_schema("experiment-analysis.schema.json")
        ),
        "prompt_template_sha256": prompt_template_hash(),
        "prompt_builder_version": PROMPT_BUILDER_VERSION,
        "claim_validator_version": ANALYSIS_VALIDATION_VERSION,
        "formula_evaluator_version": FORMULA_EVALUATOR_VERSION,
        "question_readme_sha256": question_readme_hash,
        "backend": {
            "name": backend_result.backend_name,
            "status": backend_result.status,
            "return_code": backend_result.return_code,
            "options": backend_options,
            "timeout_seconds": timeout_seconds,
            "token_usage": backend_result.token_usage,
        },
        "raw_output_sha256": raw_output_sha256,
        "accepted_analysis_sha256": canonical_json_hash(analysis) if analysis is not None else None,
        "diagnostics_sha256": canonical_json_hash(diagnostics),
    }
    return build_stage_fingerprint(
        stage_name="analyze",
        stage_version=1,
        schema_version=1,
        relevant_config={
            "paper": {"work_directory": config["paper"]["work_directory"]},
            "analysis": _analysis_stage_config(config),
        },
        source_files=source_files,
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
            PrerequisiteArtifact(
                path=manifest_entry["evidence_path"],
                file=repo / manifest_entry["evidence_path"],
                schema_name="evidence-packet.schema.json",
            ),
        ],
        extra_inputs=extra_inputs,
    )


def _analysis_source_files(
    *,
    repo: Path,
    analysis: dict[str, Any] | None,
    question_readme_path: str | None,
    question_readme_hash: str | None,
) -> list[SourceFile]:
    by_path: dict[str, SourceFile] = {}
    if question_readme_path is not None:
        by_path[question_readme_path] = SourceFile(
            path=question_readme_path,
            file=repo / question_readme_path,
            sha256=question_readme_hash,
        )
    if analysis is None:
        return list(by_path.values())
    claims = analysis.get("claims")
    if not isinstance(claims, list):
        return list(by_path.values())
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("claim_type") != "measured_value":
            continue
        source = claim.get("source")
        if not isinstance(source, dict):
            continue
        path = source.get("path")
        source_hash = source.get("source_hash")
        if isinstance(path, str) and isinstance(source_hash, str):
            by_path[path] = SourceFile(path=path, file=repo / path, sha256=source_hash)
    return list(by_path.values())


def _diagnostic_from_dataclass(diagnostic: AnalysisDiagnostic) -> dict[str, Any]:
    payload = {
        key: value for key, value in dataclasses.asdict(diagnostic).items() if value is not None
    }
    return _sanitize_diagnostic(payload)


def _diagnostic(
    code: str,
    message: str,
    *,
    path: str | None = None,
    selector: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if path is not None:
        diagnostic["path"] = path
    if selector is not None:
        diagnostic["selector"] = selector
    if detail is not None:
        diagnostic["detail"] = detail
    return diagnostic


def _sanitize_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {
        "code": str(diagnostic.get("code", "backend_failure")),
        "message": _truncate_text(
            _redact_text(str(diagnostic.get("message", ""))),
            _MAX_DIAGNOSTIC_MESSAGE_CHARS,
        )
        or "Analysis failed.",
    }
    for key in ("path", "selector"):
        value = diagnostic.get(key)
        if value is not None:
            sanitized[key] = value
    if "detail" in diagnostic and diagnostic["detail"] is not None:
        sanitized["detail"] = _cap_detail(_redact_detail(diagnostic["detail"]))
    return sanitized


def _redact_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _redact_detail(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_detail(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _cap_detail(detail: Any) -> dict[str, Any]:
    if not isinstance(detail, dict):
        detail = {"value": detail}
    if len(dump_json_bytes(detail)) <= _MAX_DIAGNOSTIC_DETAIL_BYTES:
        return detail
    capped: dict[str, Any] = {}
    for key in sorted(detail):
        candidate = {**capped, key: detail[key]}
        if len(dump_json_bytes(candidate)) <= _MAX_DIAGNOSTIC_DETAIL_BYTES:
            capped[key] = detail[key]
    capped["truncated"] = True
    while len(dump_json_bytes(capped)) > _MAX_DIAGNOSTIC_DETAIL_BYTES and capped:
        removable = [key for key in capped if key != "truncated"]
        if not removable:
            break
        capped.pop(removable[-1])
    return capped


def _preview_text(value: str | None) -> str | None:
    if value is None:
        return None
    return _truncate_text(_redact_text(value), _MAX_PREVIEW_CHARS)


def _redact_text(value: str) -> str:
    return redact_text(value)[0]


def _truncate_text(value: str, limit: int) -> str:
    return value[:limit]


def _backend_failure_message(result: AnalysisBackendResult) -> str:
    detail = result.stderr or result.stdout or "Analysis backend failed."
    return f"Analysis backend failed: {detail}"


def _backend_result_detail(result: AnalysisBackendResult) -> dict[str, Any]:
    return {
        "backend_name": result.backend_name,
        "status": result.status,
        "return_code": result.return_code,
        "stdout_preview": _preview_text(result.stdout),
        "stderr_preview": _preview_text(result.stderr),
    }


def _codex_capability_code(result: AnalysisBackendResult) -> str | None:
    if result.backend_name != "codex-exec" or result.status != "failed":
        return None
    if result.return_code is not None:
        return None
    for part in (result.stderr, result.stdout):
        if not part:
            continue
        code = _structured_codex_capability_code(part)
        if code is not None:
            return code
    return None


def _structured_codex_capability_code(text: str) -> str | None:
    diagnostic_prefixes = (
        "",
        "code:",
        "code=",
        "diagnostic_code:",
        "diagnostic_code=",
        "error_code:",
        "error_code=",
    )
    for line in text.splitlines():
        stripped = line.strip()
        for prefix in diagnostic_prefixes:
            candidate = stripped
            if prefix:
                if not stripped.startswith(prefix):
                    continue
                candidate = stripped[len(prefix) :].strip()
            for code in sorted(_CODEX_CAPABILITY_CODES):
                if candidate == code or candidate.startswith(f"{code}:"):
                    return code
    return None


def _question_readme_metadata(
    repo: Path, manifest_entry: dict[str, Any]
) -> tuple[str | None, str | None]:
    if "question_readme_path" in manifest_entry or "question_readme_sha256" in manifest_entry:
        return (
            manifest_entry.get("question_readme_path"),
            manifest_entry.get("question_readme_sha256"),
        )
    question_path = manifest_entry["question_path"]
    readme = repo / question_path / "README.md"
    if readme.is_file():
        return f"{question_path}/README.md", sha256_file(readme)
    return None, None


def _analysis_stage_config(config: dict[str, Any]) -> dict[str, Any]:
    analysis_config = config.get("analysis")
    return analysis_config if isinstance(analysis_config, dict) else {}


def _analysis_backend_config(config: dict[str, Any]) -> dict[str, Any]:
    analysis_config = _analysis_stage_config(config)
    backend_config = analysis_config.get("backend")
    return backend_config if isinstance(backend_config, dict) else {}


def _analysis_timeout_seconds(config: dict[str, Any]) -> int:
    analysis_config = _analysis_stage_config(config)
    value = analysis_config.get("timeout_seconds")
    if isinstance(value, int) and value > 0:
        return value
    return 300


def _effective_backend_options(
    config: dict[str, Any], backend_options_override: dict[str, Any] | None
) -> dict[str, Any]:
    options = dict(_analysis_backend_config(config))
    if backend_options_override is not None:
        options.update(backend_options_override)
    return options


def _effective_timeout_seconds(config: dict[str, Any], timeout_seconds_override: int | None) -> int:
    if timeout_seconds_override is not None:
        return timeout_seconds_override
    return _analysis_timeout_seconds(config)


def _schema_resource_path(name: str) -> Path:
    return Path(__file__).with_name("schemas") / name


def _analysis_output_path(repo: Path, config: dict, experiment: str) -> _PathResult:
    relative = f"{config['paper']['work_directory']}/analyses/{experiment}.json"
    if not is_repo_relative_posix(relative):
        return _PathResult(None, "unsafe_analysis_path")

    current = repo
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            return _PathResult(None, "unsafe_analysis_path")
        if not current.exists():
            break
        if index < len(parts) - 1 and not current.is_dir():
            return _PathResult(None, "unsafe_analysis_path")
    return _PathResult(relative, None)
