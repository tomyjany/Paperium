from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import ValidationError

from paperctl._support.atomic import write_bytes_atomic
from paperctl._support.blockers import derive_publication_blockers
from paperctl._support.hashing import canonical_json_hash, sha256_bytes, sha256_file
from paperctl._support.jsonio import dump_json_bytes, write_json_atomic
from paperctl._support.paths import is_repo_relative_posix
from paperctl._support.redaction import redact_text
from paperctl._support.schema import validate_artifact
from paperctl._support.sorting import posix_path_sort_key
from paperctl.inventory import InventoryError, _manifest_path, load_manifest
from paperctl.normalize import (
    NormalizeError,
    _build_packet,
    _load_fresh_inventory,
)


RENDER_SCHEMA_VERSION = 1
RENDERER_VERSION = 1
OBSERVED_LIMIT = 20
PREVIEW_LIMIT = 10
DIAGNOSTIC_LIMIT = 20
WARNING_LIMIT = 20
UNSUPPORTED_LIMIT = 20


class RenderError(ValueError):
    pass


@dataclass(frozen=True)
class RenderResult:
    draft_path: str
    render_state_path: str
    status: str
    experiment_count: int
    blocker_count: int


def render(repo: Path, config: dict[str, Any], force: bool = False) -> RenderResult:
    repo = repo.resolve()
    draft_path = config["paper"]["draft_output"]
    final_path = config["paper"]["final_output"]
    if _is_repo_root_paper_path(draft_path):
        raise RenderError("Milestone 1 render never writes repository-root PAPER.md")
    if draft_path == final_path:
        raise RenderError("paper.draft_output must not equal protected paper.final_output")

    try:
        manifest = load_manifest(repo, config)
    except InventoryError as exc:
        raise RenderError(str(exc)) from exc

    manifest_path = _manifest_path(config)
    evidence_packets = _load_fresh_evidence_packets(repo, config, manifest, manifest_path)
    blockers = derive_publication_blockers(manifest, evidence_packets)
    draft_bytes = render_draft_bytes(manifest, evidence_packets, blockers)
    render_state = _build_render_state(repo, config, manifest, evidence_packets, draft_bytes)

    try:
        validate_artifact("render-state.schema.json", render_state)
    except ValidationError as exc:
        raise RenderError(f"invalid generated render state: {exc.message}") from exc

    draft_output = _resolve_output_path(repo, draft_path, label="draft")
    state_relative = _render_state_path(config)
    state_output = _resolve_output_path(repo, state_relative, label="render state")
    status = _write_outputs(
        draft_output=draft_output,
        draft_bytes=draft_bytes,
        state_output=state_output,
        render_state=render_state,
        force=force,
    )
    return RenderResult(
        draft_path=draft_path,
        render_state_path=state_relative,
        status=status,
        experiment_count=len(manifest["experiments"]),
        blocker_count=len(blockers),
    )


def render_draft_bytes(
    manifest: dict[str, Any],
    evidence_packets: list[dict[str, Any]],
    blockers: list[dict[str, Any]] | None = None,
) -> bytes:
    if blockers is None:
        blockers = derive_publication_blockers(manifest, evidence_packets)
    packet_by_experiment = {packet["experiment_path"]: packet for packet in evidence_packets}
    lines: list[str] = [
        "# PRE-ANALYSIS EVIDENCE DRAFT",
        "",
        "> This is a pre-analysis evidence draft. It contains deterministic evidence listings "
        "only, is not a publishable paper, and is never promoted to PAPER.md in Milestone 1.",
        "",
        "## Known Publication Blockers",
        "",
    ]
    if blockers:
        lines.extend(
            [
                "| Code | Experiment | Evidence Status | Preanalysis Disposition |",
                "|---|---|---|---|",
            ]
        )
        for blocker in blockers:
            lines.append(
                "| "
                f"{_cell(blocker['code'])} | "
                f"{_cell(blocker.get('experiment_path') or 'repository')} | "
                f"{_cell(blocker.get('evidence_status') or 'n/a')} | "
                f"{_cell(blocker.get('preanalysis_disposition') or 'n/a')} |"
            )
    else:
        lines.append("No known publication blockers.")
    lines.append("")

    for question_path, entries in _group_manifest_by_question(manifest):
        first = entries[0]
        lines.extend(
            [
                f"## Question `{_code(question_path)}`",
                "",
                f"- README: `{_code(first['question_readme_path'] or 'missing')}`",
                f"- README SHA-256: `{_code(first['question_readme_sha256'] or 'missing')}`",
                f"- Discovered experiments: `{len(entries)}`",
                "",
            ]
        )
        for entry in entries:
            packet = packet_by_experiment[entry["experiment_path"]]
            _append_experiment(lines, entry, packet)

    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _load_fresh_evidence_packets(
    repo: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: str,
) -> list[dict[str, Any]]:
    packets: list[dict[str, Any]] = []
    for entry in manifest["experiments"]:
        inventory = _fresh_inventory(repo, config, entry, manifest_path)
        evidence_path = entry["evidence_path"]
        absolute_path = repo / evidence_path
        try:
            with absolute_path.open(encoding="utf-8") as handle:
                packet = json.load(handle)
        except FileNotFoundError as exc:
            raise RenderError(
                f"missing evidence packet: {evidence_path}; run paperctl normalize first"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RenderError(f"could not read evidence packet: {evidence_path}: {exc}") from exc
        try:
            validate_artifact("evidence-packet.schema.json", packet)
        except ValidationError as exc:
            raise RenderError(f"invalid evidence packet: {evidence_path}: {exc.message}") from exc
        if packet["experiment_path"] != entry["experiment_path"]:
            raise RenderError(f"evidence packet does not match manifest entry: {evidence_path}")

        expected = _expected_packet(repo, config, entry, inventory, manifest_path)
        if dump_json_bytes(packet) != dump_json_bytes(expected):
            raise RenderError(
                f"stale evidence packet: {evidence_path}; run paperctl normalize --force first"
            )
        packets.append(packet)
    return packets


def _fresh_inventory(
    repo: Path,
    config: dict[str, Any],
    entry: dict[str, Any],
    manifest_path: str,
) -> dict[str, Any]:
    try:
        return _load_fresh_inventory(repo, config, entry, manifest_path)
    except NormalizeError as exc:
        raise RenderError(str(exc)) from exc


def _expected_packet(
    repo: Path,
    config: dict[str, Any],
    entry: dict[str, Any],
    inventory: dict[str, Any],
    manifest_path: str,
) -> dict[str, Any]:
    try:
        return _build_packet(repo, config, entry, inventory, manifest_path)
    except NormalizeError as exc:
        raise RenderError(
            f"could not verify evidence packet for {entry['experiment_path']}: {exc}"
        ) from exc


def _append_experiment(
    lines: list[str],
    entry: dict[str, Any],
    packet: dict[str, Any],
) -> None:
    lines.extend(
        [
            f"### Experiment `{_code(entry['experiment_path'])}`",
            "",
            f"- Evidence packet: `{_code(entry['evidence_path'])}`",
            f"- preanalysis_disposition: `{_code(packet['preanalysis_disposition'])}`",
            f"- execution_status: `{_code(packet['execution_status'])}`",
            f"- evidence_status: `{_code(packet['evidence_status'])}`",
            f"- reason_codes: `{_code(', '.join(packet['reason_codes']) or 'none')}`",
            "",
        ]
    )
    _append_canonical_facts(lines, packet)
    evidence_path = entry["evidence_path"]
    _append_observed_values(lines, packet, evidence_path)
    _append_records(lines, "Previews", packet, "previews", PREVIEW_LIMIT, evidence_path)
    _append_records(lines, "Diagnostics", packet, "diagnostics", DIAGNOSTIC_LIMIT, evidence_path)
    _append_conflicts(lines, packet)
    _append_records(lines, "Warnings", packet, "warnings", WARNING_LIMIT, evidence_path)
    _append_unsupported(lines, packet, evidence_path)


def _append_canonical_facts(lines: list[str], packet: dict[str, Any]) -> None:
    lines.extend(["#### Canonical Facts", ""])
    facts = packet["canonical_facts"]
    if not facts:
        lines.extend(["None.", ""])
        return
    lines.extend(
        ["| Fact ID | Value | Type | Unit | Source | Selector |", "|---|---|---|---|---|---|"]
    )
    for fact in facts:
        source = fact["source"]
        lines.append(
            "| "
            f"{_cell(fact['fact_id'])} | "
            f"{_cell(_render_scalar(fact['value']))} | "
            f"{_cell(fact['value_type'])} | "
            f"{_cell(fact['unit'] if fact['unit'] is not None else 'null')} | "
            f"{_cell(source['path'])} | "
            f"{_cell(_source_selector(source))} |"
        )
    lines.append("")


def _append_observed_values(lines: list[str], packet: dict[str, Any], evidence_path: str) -> None:
    lines.extend(["#### Observed Values", ""])
    values = packet["observed_values"]
    if not values:
        lines.extend(["None.", ""])
        return
    lines.extend(["| Value | Type | Unit | Source | Selector |", "|---|---|---|---|---|"])
    for value in values[:OBSERVED_LIMIT]:
        source = value["source"]
        lines.append(
            "| "
            f"{_cell(_render_scalar(value['value']))} | "
            f"{_cell(value['value_type'])} | "
            f"{_cell(value['unit'] if value['unit'] is not None else 'null')} | "
            f"{_cell(source['path'])} | "
            f"{_cell(_source_selector(source))} |"
        )
    _append_omitted(lines, len(values), OBSERVED_LIMIT, evidence_path, "observed values")
    lines.append("")


def _append_records(
    lines: list[str],
    title: str,
    packet: dict[str, Any],
    key: str,
    limit: int,
    evidence_path: str,
) -> None:
    lines.extend([f"#### {title}", ""])
    records = packet[key]
    if not records:
        lines.extend(["None.", ""])
        return
    lines.extend(["| Source | Selector | Message | Detail |", "|---|---|---|---|"])
    for record in records[:limit]:
        source = record["source"]
        lines.append(
            "| "
            f"{_cell(source['path'])} | "
            f"{_cell(_source_selector(source))} | "
            f"{_cell(record['message'])} | "
            f"{_cell(_record_detail(record))} |"
        )
    _append_omitted(lines, len(records), limit, evidence_path, key.replace("_", " "))
    lines.append("")


def _append_conflicts(lines: list[str], packet: dict[str, Any]) -> None:
    lines.extend(["#### Conflicts", ""])
    conflicts = packet["conflicts"]
    if not conflicts:
        lines.extend(["None.", ""])
        return
    lines.extend(["| Reason | Fact ID | Sources |", "|---|---|---|"])
    for conflict in conflicts:
        sources = "; ".join(
            f"{source['path']} {_source_selector(source)}" for source in conflict["sources"]
        )
        lines.append(
            "| "
            f"{_cell(conflict['reason_code'])} | "
            f"{_cell(conflict['fact_id'])} | "
            f"{_cell(sources)} |"
        )
    lines.append("")


def _append_unsupported(lines: list[str], packet: dict[str, Any], evidence_path: str) -> None:
    lines.extend(["#### Unsupported Artifacts", ""])
    artifacts = packet["unsupported_artifacts"]
    if not artifacts:
        lines.extend(["None.", ""])
        return
    lines.extend(["| Artifact | Reason |", "|---|---|"])
    for artifact in artifacts[:UNSUPPORTED_LIMIT]:
        lines.append(f"| {_cell(artifact['path'])} | {_cell(artifact['reason_code'])} |")
    _append_omitted(
        lines,
        len(artifacts),
        UNSUPPORTED_LIMIT,
        evidence_path,
        "unsupported artifacts",
    )
    lines.append("")


def _append_omitted(
    lines: list[str],
    count: int,
    limit: int,
    evidence_path: str,
    label: str,
) -> None:
    if count <= limit:
        return
    omitted = count - limit
    lines.append(f"_{omitted} {label} omitted by render limit; see `{_code(evidence_path)}`._")


def _group_manifest_by_question(manifest: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in manifest["experiments"]:
        grouped.setdefault(entry["question_path"], []).append(entry)
    return [
        (
            question_path,
            sorted(entries, key=lambda entry: posix_path_sort_key(entry["experiment_path"])),
        )
        for question_path, entries in sorted(
            grouped.items(), key=lambda item: posix_path_sort_key(item[0])
        )
    ]


def _record_detail(record: dict[str, Any]) -> str:
    ignored = {"source", "message"}
    detail = {key: record[key] for key in sorted(record) if key not in ignored}
    if not detail:
        return ""
    return json.dumps(detail, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _render_scalar(value: Any) -> str:
    if isinstance(value, str):
        redacted, _ = redact_text(value)
        return redacted
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _source_selector(source: dict[str, Any]) -> str:
    selector_type = source["selector_type"]
    if selector_type == "json_pointer":
        return source["selector"]
    if selector_type == "line_range":
        return f"lines {source['line_start']}-{source['line_end']}"
    return "none"


def _cell(value: Any) -> str:
    return _table_text(str(value)).replace("\n", "<br>")


def _code(value: str) -> str:
    redacted, _ = redact_text(value)
    return redacted.replace("`", "'")


def _table_text(value: str) -> str:
    redacted, _ = redact_text(value)
    return redacted.replace("`", "\\`").replace("|", "\\|").replace("<", "\\<").replace(">", "\\>")


def _build_render_state(
    repo: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    evidence_packets: list[dict[str, Any]],
    draft_bytes: bytes,
) -> dict[str, Any]:
    manifest_path = _manifest_path(config)
    manifest_sha256 = sha256_file(repo / manifest_path)
    evidence_hashes = [
        sha256_file(repo / entry["evidence_path"]) for entry in manifest["experiments"]
    ]
    draft_sha256 = sha256_bytes(draft_bytes)
    fingerprint = {
        "stage": {"name": "render", "version": RENDERER_VERSION},
        "schema_version": RENDER_SCHEMA_VERSION,
        "renderer_version": str(RENDERER_VERSION),
        "config_sha256": canonical_json_hash(_relevant_config(config)),
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "evidence_packet_sha256": evidence_hashes,
        "draft_path": config["paper"]["draft_output"],
        "draft_sha256": draft_sha256,
        "input_counts": {
            "experiment_count": len(manifest["experiments"]),
            "evidence_packet_count": len(evidence_packets),
        },
    }
    fingerprint["fingerprint_sha256"] = canonical_json_hash(fingerprint)
    return {
        "schema_version": RENDER_SCHEMA_VERSION,
        "artifact_type": "render_state",
        "draft_output": config["paper"]["draft_output"],
        "fingerprint": fingerprint,
        "manifest_sha256": manifest_sha256,
        "evidence_packet_sha256": evidence_hashes,
    }


def _write_outputs(
    *,
    draft_output: Path,
    draft_bytes: bytes,
    state_output: Path,
    render_state: dict[str, Any],
    force: bool,
) -> str:
    state_bytes = dump_json_bytes(render_state)
    if (
        not force
        and draft_output.exists()
        and state_output.exists()
        and draft_output.read_bytes() == draft_bytes
        and state_output.read_bytes() == state_bytes
    ):
        return "unchanged"
    try:
        write_bytes_atomic(draft_output, draft_bytes)
        write_json_atomic(state_output, render_state)
    except OSError as exc:
        raise RenderError(f"could not write render outputs: {exc}") from exc
    return "wrote"


def _resolve_output_path(repo: Path, path: str, *, label: str) -> Path:
    if not is_repo_relative_posix(path):
        raise RenderError(f"{label} path must be repo-relative POSIX: {path}")
    current = repo
    parts = PurePosixPath(path).parts
    for index, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            relative = current.relative_to(repo).as_posix()
            if index == len(parts) - 1:
                raise RenderError(f"{label} output path is a symlink: {path}")
            raise RenderError(f"{label} output path contains a symlink: {relative}")
        if not current.exists():
            break
    return repo / Path(*parts)


def _is_repo_root_paper_path(path: str) -> bool:
    return PurePosixPath(path).parts == ("PAPER.md",)


def _render_state_path(config: dict[str, Any]) -> str:
    return f"{config['paper']['work_directory']}/render-state.json"


def _relevant_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper": {
            "work_directory": config["paper"]["work_directory"],
            "draft_output": config["paper"]["draft_output"],
            "final_output": config["paper"]["final_output"],
        },
        "render_limits": {
            "observed_values": OBSERVED_LIMIT,
            "previews": PREVIEW_LIMIT,
            "diagnostics": DIAGNOSTIC_LIMIT,
            "warnings": WARNING_LIMIT,
            "unsupported_artifacts": UNSUPPORTED_LIMIT,
        },
    }
