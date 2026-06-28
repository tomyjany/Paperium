from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperium.selection import has_usable_run_artifact, resolve_question_readme
from paperium.state import SelectedExperiment

FACT_CHECK_KEYS = {"status", "findings"}
FACT_CHECK_STATUSES = {"passed", "failed"}
FACT_CHECK_FINDING_KEYS = {"severity", "claim", "reason", "artifact_path", "selector"}
FACT_CHECK_SEVERITIES = {"error", "warning"}
FACT_CHECK_REASON_PREFIXES = (
    "unsupported:",
    "no_artifact:",
    "contradicted:",
    "needs_correction:",
)
MAX_FACT_CHECK_REPAIRS = 2


class FactCheckError(Exception):
    pass


@dataclass(frozen=True)
class FactCheckResult:
    status: str
    findings: list[dict[str, Any]]


def prepare_selected_experiment(repo: Path, exp: Path) -> SelectedExperiment:
    repo = repo.resolve()
    exp = exp.resolve()
    experiment_path = _repo_relative_posix(repo, exp)
    paperium_dir = exp / ".paperium"
    _validate_paperium_output_dir(repo, paperium_dir)
    paperium_dir.mkdir(exist_ok=True)

    question_readme = resolve_question_readme(repo, exp)
    if question_readme is not None:
        question_readme_path = _repo_relative_posix(repo, question_readme)
    else:
        question_readme_path = None

    if has_usable_run_artifact(exp):
        disposition = None
        status = "pending"
    else:
        disposition = "artifact_missing"
        status = "needs_human_review"

    return SelectedExperiment(
        path=experiment_path,
        question_readme=question_readme_path,
        analysis_path=f"{experiment_path}/.paperium/analysis.md",
        fact_check_result_path=f"{experiment_path}/.paperium/fact-check.json",
        disposition=disposition,
        status=status,
        repair_attempts=0,
    )


def load_fact_check_result(
    path: Path, allowed_artifact_paths: set[str] | None = None
) -> FactCheckResult:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise FactCheckError(f"invalid fact-check JSON: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise FactCheckError("fact-check result must be an object")
    if set(data) != FACT_CHECK_KEYS:
        raise FactCheckError("fact-check result must contain exactly status and findings")

    status = data["status"]
    if not isinstance(status, str) or status not in FACT_CHECK_STATUSES:
        raise FactCheckError(f"invalid fact-check status: {status}")

    findings = data["findings"]
    if not isinstance(findings, list):
        raise FactCheckError("fact-check findings must be a list")
    if status == "passed" and findings:
        raise FactCheckError("passed fact-check results must not include findings")
    if status == "failed" and not findings:
        raise FactCheckError("failed fact-check results require at least one finding")

    validated_findings = [
        _validate_fact_check_finding(finding, allowed_artifact_paths)
        for finding in findings
    ]
    return FactCheckResult(status=status, findings=validated_findings)


def next_fact_check_status(
    repair_attempts: int, fact_check_passed: bool
) -> tuple[str, int]:
    if fact_check_passed:
        return "approved", repair_attempts
    if repair_attempts >= MAX_FACT_CHECK_REPAIRS:
        return "needs_human_review", MAX_FACT_CHECK_REPAIRS
    return "running", repair_attempts + 1


def apply_fact_check_result(
    selected_experiment: dict[str, Any], result: FactCheckResult
) -> dict[str, Any]:
    repair_attempts = selected_experiment.get("repair_attempts", 0)
    status, next_repair_attempts = next_fact_check_status(
        repair_attempts=repair_attempts,
        fact_check_passed=result.status == "passed",
    )
    updated = dict(selected_experiment)
    updated["status"] = status
    updated["repair_attempts"] = next_repair_attempts
    if status == "approved":
        updated["disposition"] = None
    elif status == "needs_human_review":
        updated["disposition"] = "fact_check_failed"
    return updated


def _validate_fact_check_finding(
    finding: Any, allowed_artifact_paths: set[str] | None
) -> dict[str, Any]:
    if not isinstance(finding, dict):
        raise FactCheckError("fact-check finding must be an object")
    if set(finding) != FACT_CHECK_FINDING_KEYS:
        raise FactCheckError("fact-check finding has invalid fields")

    severity = finding["severity"]
    if not isinstance(severity, str) or severity not in FACT_CHECK_SEVERITIES:
        raise FactCheckError(f"invalid fact-check finding severity: {severity}")

    claim = finding["claim"]
    if not isinstance(claim, str) or not claim.strip():
        raise FactCheckError("fact-check finding claim must be a non-empty string")

    reason = finding["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise FactCheckError("fact-check finding reason must be a non-empty string")
    reason = reason.strip()
    if reason in {"unsupported", "no_artifact", "contradicted", "needs_correction"}:
        raise FactCheckError("fact-check finding reason must be prose, not an enum")
    _validate_fact_check_reason_prose(reason)

    artifact_path = finding["artifact_path"]
    selector = finding["selector"]
    _validate_artifact_selector_pair(
        artifact_path=artifact_path,
        selector=selector,
        reason=reason,
        allowed_artifact_paths=allowed_artifact_paths,
    )

    return {
        "severity": severity,
        "claim": claim,
        "reason": reason,
        "artifact_path": artifact_path,
        "selector": selector,
    }


def _validate_fact_check_reason_prose(reason: str) -> None:
    for prefix in FACT_CHECK_REASON_PREFIXES:
        if reason.startswith(prefix) and not reason.removeprefix(prefix).strip():
            raise FactCheckError(
                "fact-check finding reason must include explanatory prose"
            )


def _validate_artifact_selector_pair(
    *,
    artifact_path: Any,
    selector: Any,
    reason: str,
    allowed_artifact_paths: set[str] | None,
) -> None:
    artifact_is_null = artifact_path is None
    selector_is_null = selector is None
    if artifact_is_null != selector_is_null:
        raise FactCheckError("artifact_path and selector must both be null or non-null")

    if artifact_is_null:
        if not (
            reason.startswith("unsupported:") or reason.startswith("no_artifact:")
        ):
            raise FactCheckError("null artifact references require unsupported/no_artifact reason")
        return

    if reason.startswith(("contradicted:", "needs_correction:")):
        _validate_artifact_path(artifact_path, allowed_artifact_paths)
        _validate_selector(selector)
        return

    _validate_artifact_path(artifact_path, allowed_artifact_paths)
    _validate_selector(selector)


def _validate_artifact_path(
    artifact_path: Any, allowed_artifact_paths: set[str] | None
) -> None:
    if not isinstance(artifact_path, str) or not artifact_path:
        raise FactCheckError("artifact_path must be a non-empty string")
    if (
        artifact_path.startswith("/")
        or "\\" in artifact_path
        or re.match(r"^[A-Za-z]:", artifact_path)
    ):
        raise FactCheckError(f"unsafe artifact_path: {artifact_path}")
    if any(part in {"", ".", ".."} for part in artifact_path.split("/")):
        raise FactCheckError(f"unsafe artifact_path: {artifact_path}")
    if allowed_artifact_paths is not None and artifact_path not in allowed_artifact_paths:
        raise FactCheckError(f"artifact_path is not allowed: {artifact_path}")


def _validate_selector(selector: Any) -> None:
    if not isinstance(selector, str) or not selector:
        raise FactCheckError("selector must be a non-empty string")
    if not (
        selector.startswith("/")
        or selector.startswith("lines ")
        or selector.startswith("csv:")
    ):
        raise FactCheckError(f"invalid selector: {selector}")


def _repo_relative_posix(repo: Path, path: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside repository: {path}") from exc


def _validate_paperium_output_dir(repo: Path, paperium_dir: Path) -> None:
    resolved = paperium_dir.resolve()
    if paperium_dir.is_symlink():
        try:
            resolved.relative_to(repo)
        except ValueError as exc:
            raise ValueError(
                f".paperium symlink resolves outside repository: {paperium_dir}"
            ) from exc
        raise ValueError(f".paperium symlink is not allowed: {paperium_dir}")
    _repo_relative_posix(repo, resolved)
