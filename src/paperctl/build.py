from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperctl._support.jsonio import write_json_atomic
from paperctl.audit import AuditError, AuditResult, audit
from paperctl.discovery import DiscoveryError, ManifestResult, discover
from paperctl.inventory import InventoryAllResult, InventoryError, inventory_all
from paperctl.normalize import NormalizeAllResult, NormalizeError, normalize_all
from paperctl.rendering import RenderError, RenderResult, render


class BuildError(ValueError):
    pass


@dataclass(frozen=True)
class BuildResult:
    deterministic_status: str
    publication_status: str
    draft_path: str
    audit_path: str
    publication_blocker_codes: list[str]
    discovery: ManifestResult
    inventory: InventoryAllResult
    normalize: NormalizeAllResult
    render: RenderResult
    audit: AuditResult


def build(repo: Path, config: dict[str, Any], force: bool = False) -> BuildResult:
    repo = repo.resolve()
    try:
        discovery_result = _discover_for_build(repo, config, force)
        if force:
            discovery_result = _force_discovery_write(repo, discovery_result)
        inventory_result = inventory_all(
            repo=repo,
            config=config,
            manifest=discovery_result.manifest,
            force=force,
        )
        normalize_result = normalize_all(repo=repo, config=config, force=force)
        render_result = render(repo=repo, config=config, force=force)
        audit_result = audit(repo=repo, config=config, stage="deterministic", force=force)
    except (AuditError, DiscoveryError, InventoryError, NormalizeError, RenderError) as exc:
        raise BuildError(str(exc)) from exc

    if audit_result.deterministic_status != "passed":
        issue_summary = ", ".join(audit_result.issue_codes) or "unknown"
        raise BuildError(f"deterministic audit failed: {issue_summary}")

    return BuildResult(
        deterministic_status=audit_result.deterministic_status,
        publication_status=audit_result.publication_status,
        draft_path=render_result.draft_path,
        audit_path=audit_result.report_path,
        publication_blocker_codes=_unique_codes(audit_result.blocker_codes),
        discovery=discovery_result,
        inventory=inventory_result,
        normalize=normalize_result,
        render=render_result,
        audit=audit_result,
    )


def _unique_codes(codes: list[str]) -> list[str]:
    return list(dict.fromkeys(codes))


def _discover_for_build(repo: Path, config: dict[str, Any], force: bool) -> ManifestResult:
    try:
        return discover(repo=repo, config=config, force=force)
    except DiscoveryError as exc:
        if force or "manifest already exists and differs" not in str(exc):
            raise
        return discover(repo=repo, config=config, force=True)


def _force_discovery_write(repo: Path, result: ManifestResult) -> ManifestResult:
    if result.status != "unchanged":
        return result
    output_path = repo / result.path
    try:
        write_json_atomic(output_path, result.manifest)
    except OSError as exc:
        raise BuildError(f"could not write manifest: {result.path}: {exc}") from exc
    return ManifestResult(
        path=result.path,
        experiment_count=result.experiment_count,
        status="replaced",
        manifest=result.manifest,
    )
