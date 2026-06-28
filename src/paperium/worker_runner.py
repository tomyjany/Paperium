from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from paperium.backends import backend_command
from paperium.workers import WorkerResult, WorkerSpec


def run_worker(repo: Path, spec: WorkerSpec) -> WorkerResult:
    repo = Path(repo)
    worker_dir = _safe_worker_dir(repo, spec.worker_id)
    if worker_dir is None:
        return _failed_result(repo, spec, "invalid_worker_id")

    canonical_path = None
    if spec.canonical_result_path is not None:
        canonical_path = _safe_repo_relative_path(repo, spec.canonical_result_path)
        if canonical_path is None:
            return _failed_result(repo, spec, "invalid_canonical_result_path")

    worker_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = worker_dir / "stdout.txt"
    stderr_path = worker_dir / "stderr.txt"
    output_path = worker_dir / "output.md"
    result_json_path = worker_dir / "result.json"

    context_dir = repo / ".paperium" / "context-requests"
    baseline_requests = _request_snapshot(context_dir)

    started_at = _utc_now()
    process = subprocess.Popen(
        backend_command(spec.backend),
        cwd=repo,
        text=True,
        encoding="utf-8",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    timed_out = False
    returncode = None
    try:
        stdout, stderr = process.communicate(
            input=spec.prompt, timeout=spec.timeout_seconds
        )
        returncode = process.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        process.kill()
        final_stdout, final_stderr = _reap_after_timeout(process)
        stdout = _prefer_final_output(final_stdout, exc.output)
        stderr = _prefer_final_output(final_stderr, exc.stderr)

    ended_at = _utc_now()
    stdout_path.write_text(_text(stdout), encoding="utf-8")
    stderr_path.write_text(_text(stderr), encoding="utf-8")

    context_request_state = _context_request_state(
        context_dir, baseline_requests, spec.worker_id
    )
    context_request_allowed = ".paperium/context-requests" in spec.writable_paths

    status = "succeeded"
    failure_reason = None
    canonical_result_path = None

    if timed_out:
        status = "timed_out"
        failure_reason = "timeout"
    elif context_request_state == "current_worker" and not context_request_allowed:
        status = "failed"
        failure_reason = "write_boundary_violation"
    elif context_request_state == "current_worker":
        status = "needs_context"
    elif context_request_state == "invalid":
        status = "failed"
        failure_reason = "invalid_context_request"
    elif returncode != 0:
        status = "failed"
        failure_reason = f"nonzero_exit:{returncode}"
    elif spec.canonical_result_path is not None:
        if result_json_path.exists():
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(result_json_path, canonical_path)
            canonical_result_path = spec.canonical_result_path
        else:
            status = "failed"
            failure_reason = "missing_result_json"

    return WorkerResult(
        worker_id=spec.worker_id,
        status=status,
        stdout_path=_repo_path(repo, stdout_path),
        stderr_path=_repo_path(repo, stderr_path),
        output_path=_repo_path(repo, output_path),
        result_json_path=_repo_path(repo, result_json_path),
        canonical_result_path=canonical_result_path,
        started_at=started_at,
        ended_at=ended_at,
        failure_reason=failure_reason,
    )


def _safe_worker_dir(repo: Path, worker_id: str) -> Path | None:
    worker_path = Path(worker_id)
    if worker_path.is_absolute() or not worker_id or ".." in worker_path.parts:
        return None
    workers_root = repo / ".paperium" / "workers"
    worker_dir = workers_root / worker_path
    if not _is_relative_to(worker_dir.resolve(strict=False), workers_root.resolve(strict=False)):
        return None
    return worker_dir


def _safe_repo_relative_path(repo: Path, repo_relative_path: str) -> Path | None:
    path = Path(repo_relative_path)
    if path.is_absolute() or ".." in path.parts:
        return None
    resolved_repo = repo.resolve(strict=False)
    resolved_path = (repo / path).resolve(strict=False)
    if not _is_relative_to(resolved_path, resolved_repo):
        return None
    return repo / path


def _failed_result(repo: Path, spec: WorkerSpec, failure_reason: str) -> WorkerResult:
    worker_dir = repo / ".paperium" / "workers" / "invalid"
    result_json_path = worker_dir / "result.json"
    return WorkerResult(
        worker_id=spec.worker_id,
        status="failed",
        stdout_path=_repo_path(repo, worker_dir / "stdout.txt"),
        stderr_path=_repo_path(repo, worker_dir / "stderr.txt"),
        output_path=_repo_path(repo, worker_dir / "output.md"),
        result_json_path=_repo_path(repo, result_json_path),
        canonical_result_path=None,
        started_at=None,
        ended_at=None,
        failure_reason=failure_reason,
    )


def _request_snapshot(context_dir: Path) -> dict[Path, str]:
    if not context_dir.exists():
        return {}
    return {
        path: sha256(path.read_bytes()).hexdigest()
        for path in context_dir.glob("*.json")
        if path.is_file()
    }


def _context_request_state(
    context_dir: Path, baseline_requests: dict[Path, str], worker_id: str
) -> str:
    for request_path, digest in _request_snapshot(context_dir).items():
        if baseline_requests.get(request_path) == digest:
            continue
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "invalid"
        if request.get("worker_id") == worker_id:
            return "current_worker"
    return "none"


def _reap_after_timeout(process: subprocess.Popen) -> tuple[str | bytes | None, str | bytes | None]:
    try:
        return process.communicate()
    except subprocess.TimeoutExpired:
        return None, None


def _prefer_final_output(
    final: str | bytes | None, partial: str | bytes | None
) -> str | bytes | None:
    if final not in (None, b"", ""):
        return final
    return partial


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _repo_path(repo: Path, path: Path) -> str:
    return path.relative_to(repo).as_posix()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
