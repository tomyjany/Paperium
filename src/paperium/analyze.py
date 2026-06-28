from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperium.context_requests import context_request_state_from_request, read_context_request
from paperium.prompts import build_analysis_prompt, build_fact_check_prompt
from paperium.selection import has_usable_run_artifact, resolve_question_readme
from paperium.state import ContextRequestState, PaperiumState, SelectedExperiment, WorkerRecord
from paperium.worker_runner import run_worker
from paperium.workers import WorkerResult, WorkerSpec, build_worker_record, worker_id_for

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
WORKER_TIMEOUT_SECONDS = 1800


class FactCheckError(Exception):
    pass


@dataclass(frozen=True)
class FactCheckResult:
    status: str
    findings: list[dict[str, Any]]


class AnalyzeError(Exception):
    pass


def analyze_selected_experiments(repo: Path, state: PaperiumState, jobs: int = 2) -> None:
    del jobs
    repo = repo.resolve()
    for selected in state.selected_experiments:
        _normalize_selected_paths(selected)
        experiment = _repo_relative_path(repo, selected.path)
        if not has_usable_run_artifact(experiment):
            selected.disposition = "artifact_missing"
            selected.status = "needs_human_review"
            continue
        if selected.status not in {"pending", "running"}:
            continue

        analysis_worker_id = worker_id_for("analyze", selected.path)
        if _has_denied_context_request(state, analysis_worker_id):
            _mark_worker_failure(selected)
            continue

        selected.status = "running"
        analysis_result = _run_and_record_worker(
            repo,
            state,
            _analysis_spec(
                selected,
                approved_expansions=_approved_context_expansions(state, analysis_worker_id),
            ),
        )
        if analysis_result.status == "needs_context":
            _ingest_context_request(repo, state, analysis_result.worker_id)
            return
        if analysis_result.status != "succeeded":
            _mark_worker_failure(selected)
            raise AnalyzeError(analysis_result.failure_reason or "analysis_worker_failed")

        fact_check_worker_id = worker_id_for("fact_check", selected.path)
        if _has_denied_context_request(state, fact_check_worker_id):
            _mark_worker_failure(selected)
            continue

        fact_check_result = _run_and_record_worker(
            repo,
            state,
            _fact_check_spec(
                selected,
                approved_expansions=_approved_context_expansions(state, fact_check_worker_id),
            ),
        )
        if fact_check_result.status == "needs_context":
            _ingest_context_request(repo, state, fact_check_result.worker_id)
            return
        if fact_check_result.status != "succeeded":
            _mark_worker_failure(selected)
            raise AnalyzeError(fact_check_result.failure_reason or "fact_check_worker_failed")

        result_path = _fact_check_result_path(repo, selected, fact_check_result)
        selected_dict = apply_fact_check_result(
            selected.to_dict(),
            load_fact_check_result(result_path),
        )
        _update_selected_experiment(selected, selected_dict)

    if _analysis_complete(state):
        state.phase = "ranking"
    elif state.phase == "selecting":
        state.phase = "analyzing"


def _analysis_spec(
    selected: SelectedExperiment,
    approved_expansions: list[str] | None = None,
) -> WorkerSpec:
    _normalize_selected_paths(selected)
    worker_id = worker_id_for("analyze", selected.path)
    output_path = _worker_output_path(worker_id)
    readable_paths = _readable_paths(selected)
    expansions = approved_expansions or []
    writable_paths = [selected.analysis_path, _worker_dir(worker_id), ".paperium/context-requests"]
    return WorkerSpec(
        worker_id=worker_id,
        backend="codex",
        role="analyze",
        readable_paths=readable_paths,
        writable_paths=writable_paths,
        prompt=build_analysis_prompt(
            experiment_path=selected.path,
            question_readme=selected.question_readme,
            readable_paths=readable_paths,
            writable_paths=writable_paths,
            analysis_path=selected.analysis_path,
            output_path=output_path,
            approved_expansions=expansions,
        ),
        timeout_seconds=WORKER_TIMEOUT_SECONDS,
        experiment_path=selected.path,
        approved_expansions=expansions,
    )


def _fact_check_spec(
    selected: SelectedExperiment,
    approved_expansions: list[str] | None = None,
) -> WorkerSpec:
    _normalize_selected_paths(selected)
    worker_id = worker_id_for("fact_check", selected.path)
    output_path = _worker_output_path(worker_id)
    readable_paths = _readable_paths(selected, extra=[selected.analysis_path])
    expansions = approved_expansions or []
    writable_paths = [_worker_dir(worker_id), ".paperium/context-requests"]
    return WorkerSpec(
        worker_id=worker_id,
        backend="codex",
        role="fact_check",
        readable_paths=readable_paths,
        writable_paths=writable_paths,
        prompt=build_fact_check_prompt(
            analysis_path=selected.analysis_path,
            experiment_path=selected.path,
            readable_paths=readable_paths,
            writable_paths=writable_paths,
            result_json_path=_worker_result_path(worker_id),
            output_path=output_path,
            approved_expansions=expansions,
        ),
        timeout_seconds=WORKER_TIMEOUT_SECONDS,
        experiment_path=selected.path,
        canonical_result_path=selected.fact_check_result_path,
        approved_expansions=expansions,
    )


def _run_and_record_worker(repo: Path, state: PaperiumState, spec: WorkerSpec) -> WorkerResult:
    record = build_worker_record(spec)
    result = run_worker(repo, spec)
    _apply_worker_result(record, result)
    state.workers.append(WorkerRecord.from_dict(record))
    return _worker_result_from_any(spec, result)


def _apply_worker_result(record: dict[str, Any], result: Any) -> None:
    for field in (
        "status",
        "started_at",
        "ended_at",
        "stdout_path",
        "stderr_path",
        "output_path",
        "result_json_path",
        "canonical_result_path",
        "failure_reason",
    ):
        value = _result_value(result, field)
        if value is not None or field in {"failure_reason", "canonical_result_path"}:
            record[field] = value


def _worker_result_from_any(spec: WorkerSpec, result: Any) -> WorkerResult:
    defaults = build_worker_record(spec)
    return WorkerResult(
        worker_id=_result_value(result, "worker_id") or spec.worker_id,
        status=_result_value(result, "status") or "failed",
        stdout_path=_result_value(result, "stdout_path") or str(defaults["stdout_path"]),
        stderr_path=_result_value(result, "stderr_path") or str(defaults["stderr_path"]),
        output_path=_result_value(result, "output_path") or str(defaults["output_path"]),
        result_json_path=(
            _result_value(result, "result_json_path") or str(defaults["result_json_path"])
        ),
        canonical_result_path=_result_value(result, "canonical_result_path"),
        started_at=_result_value(result, "started_at"),
        ended_at=_result_value(result, "ended_at"),
        failure_reason=_result_value(result, "failure_reason"),
    )


def _result_value(result: Any, field: str) -> Any:
    if isinstance(result, dict):
        return result.get(field)
    return getattr(result, field, None)


def _fact_check_result_path(repo: Path, selected: SelectedExperiment, result: WorkerResult) -> Path:
    _normalize_selected_paths(selected)
    canonical = repo / selected.fact_check_result_path
    if canonical.exists():
        return canonical
    result_path = repo / result.result_json_path
    if result_path.exists():
        return result_path
    raise AnalyzeError("missing_fact_check_result")


def _update_selected_experiment(selected: SelectedExperiment, values: dict[str, Any]) -> None:
    selected.status = values["status"]
    selected.repair_attempts = values["repair_attempts"]
    selected.disposition = values["disposition"]


def _mark_worker_failure(selected: SelectedExperiment) -> None:
    selected.status = "needs_human_review"
    selected.disposition = "needs_human_review"


def _approved_context_expansions(state: PaperiumState, worker_id: str) -> list[str]:
    paths: list[str] = []
    for request in state.context_requests:
        if request.worker_id == worker_id and request.status == "approved":
            paths.extend(request.requested_paths)
    return list(dict.fromkeys(paths))


def _has_denied_context_request(state: PaperiumState, worker_id: str) -> bool:
    return any(
        request.worker_id == worker_id and request.status == "denied"
        for request in state.context_requests
    )


def _ingest_context_request(repo: Path, state: PaperiumState, worker_id: str) -> None:
    request_dir = repo / ".paperium" / "context-requests"
    if not request_dir.exists():
        return
    existing = {request.id for request in state.context_requests}
    for request_path in sorted(request_dir.glob("*.json")):
        if request_path.name.endswith(".decision.json"):
            continue
        try:
            request = read_context_request(request_path)
        except Exception as exc:
            raise AnalyzeError(f"invalid_context_request: {exc}") from exc
        if request.worker_id != worker_id or request.id in existing:
            continue
        decision_path = f".paperium/context-requests/{request.id}.decision.json"
        state.context_requests.append(
            ContextRequestState.from_dict(
                context_request_state_from_request(request, decision_path=decision_path)
            )
        )
        existing.add(request.id)


def _analysis_complete(state: PaperiumState) -> bool:
    return bool(state.selected_experiments) and all(
        selected.status == "approved"
        or (selected.disposition is not None and selected.status != "approved")
        for selected in state.selected_experiments
    )


def _readable_paths(selected: SelectedExperiment, extra: list[str] | None = None) -> list[str]:
    _normalize_selected_paths(selected)
    paths = [selected.path]
    if selected.question_readme is not None:
        paths.append(selected.question_readme)
    if extra is not None:
        paths.extend(extra)
    return list(dict.fromkeys(paths))


def _worker_dir(worker_id: str) -> str:
    return f".paperium/workers/{worker_id}"


def _worker_output_path(worker_id: str) -> str:
    return f"{_worker_dir(worker_id)}/output.md"


def _worker_result_path(worker_id: str) -> str:
    return f"{_worker_dir(worker_id)}/result.json"


def _normalize_selected_paths(selected: SelectedExperiment) -> None:
    selected.path = _validate_repo_relative_posix(
        selected.path, field_name="selected experiment path"
    )
    selected.analysis_path = f"{selected.path}/.paperium/analysis.md"
    selected.fact_check_result_path = f"{selected.path}/.paperium/fact-check.json"
    if selected.question_readme is not None:
        selected.question_readme = _validate_repo_relative_posix(
            selected.question_readme, field_name="selected question README path"
        )


def _validate_repo_relative_posix(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise AnalyzeError(f"unsafe {field_name}: {value}")
    if value.startswith("/") or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise AnalyzeError(f"unsafe {field_name}: {value}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise AnalyzeError(f"unsafe {field_name}: {value}")
    return value


def _repo_relative_path(repo: Path, repo_relative_path: str) -> Path:
    safe_path = _validate_repo_relative_posix(
        repo_relative_path, field_name="selected experiment path"
    )
    path = (repo / safe_path).resolve(strict=False)
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise AnalyzeError(f"unsafe selected experiment path: {repo_relative_path}") from exc
    return path


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
    except UnicodeDecodeError as exc:
        raise FactCheckError("invalid fact-check file encoding: expected UTF-8") from exc
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
        _validate_fact_check_finding(finding, allowed_artifact_paths) for finding in findings
    ]
    return FactCheckResult(status=status, findings=validated_findings)


def next_fact_check_status(repair_attempts: int, fact_check_passed: bool) -> tuple[str, int]:
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
            raise FactCheckError("fact-check finding reason must include explanatory prose")


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
        if not (reason.startswith("unsupported:") or reason.startswith("no_artifact:")):
            raise FactCheckError("null artifact references require unsupported/no_artifact reason")
        return

    if reason.startswith(("contradicted:", "needs_correction:")):
        _validate_artifact_path(artifact_path, allowed_artifact_paths)
        _validate_selector(selector)
        return

    _validate_artifact_path(artifact_path, allowed_artifact_paths)
    _validate_selector(selector)


def _validate_artifact_path(artifact_path: Any, allowed_artifact_paths: set[str] | None) -> None:
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
    if selector.startswith("/"):
        return
    if selector.startswith("lines ") and selector.removeprefix("lines ").strip():
        return
    if selector.startswith("csv:") and selector.removeprefix("csv:").strip():
        return
    if not (selector.startswith("lines ") or selector.startswith("csv:")):
        raise FactCheckError(f"invalid selector: {selector}")
    raise FactCheckError("selector must include a non-empty payload")


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
