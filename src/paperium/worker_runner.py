from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from paperium.backends import backend_command
from paperium.workers import WorkerResult, WorkerSpec


def run_worker(repo: Path, spec: WorkerSpec) -> WorkerResult:
    worker_dir = repo / ".paperium" / "workers" / spec.worker_id
    worker_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = worker_dir / "stdout.txt"
    stderr_path = worker_dir / "stderr.txt"
    output_path = worker_dir / "output.md"
    result_json_path = worker_dir / "result.json"

    context_dir = repo / ".paperium" / "context-requests"
    baseline_requests = _request_files(context_dir)

    started_at = _utc_now()
    process = subprocess.Popen(
        backend_command(spec.backend),
        cwd=repo,
        text=True,
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
        stdout = exc.output
        stderr = exc.stderr

    ended_at = _utc_now()
    stdout_path.write_text(_text(stdout))
    stderr_path.write_text(_text(stderr))

    current_worker_context_request = _has_new_context_request(
        context_dir, baseline_requests, spec.worker_id
    )
    context_request_allowed = ".paperium/context-requests" in spec.writable_paths

    status = "succeeded"
    failure_reason = None
    canonical_result_path = None

    if timed_out:
        status = "timed_out"
        failure_reason = "timeout"
    elif current_worker_context_request and not context_request_allowed:
        status = "failed"
        failure_reason = "write_boundary_violation"
    elif current_worker_context_request:
        status = "needs_context"
    elif returncode != 0:
        status = "failed"
        failure_reason = f"nonzero_exit:{returncode}"
    elif spec.canonical_result_path is not None:
        if result_json_path.exists():
            canonical_path = repo / spec.canonical_result_path
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


def _request_files(context_dir: Path) -> set[Path]:
    if not context_dir.exists():
        return set()
    return {path for path in context_dir.glob("*.json") if path.is_file()}


def _has_new_context_request(
    context_dir: Path, baseline_requests: set[Path], worker_id: str
) -> bool:
    for request_path in _request_files(context_dir) - baseline_requests:
        try:
            request = json.loads(request_path.read_text())
        except json.JSONDecodeError:
            continue
        if request.get("worker_id") == worker_id:
            return True
    return False


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
