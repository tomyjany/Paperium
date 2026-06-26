from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple

from jsonschema import ValidationError

from paperctl import config as config_module
from paperctl._support.paths import is_repo_relative_posix


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


def analyze_experiment(repo: Path, experiment: str, backend: object | None = None) -> AnalyzeResult:
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
