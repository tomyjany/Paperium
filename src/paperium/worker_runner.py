from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from paperium import boundary_audit
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

    if _has_symlink_component(repo, worker_dir):
        return _failed_result(repo, spec, "boundary_audit_failed")

    worker_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = worker_dir / "stdout.txt"
    stderr_path = worker_dir / "stderr.txt"
    output_path = worker_dir / "output.md"
    result_json_path = worker_dir / "result.json"

    context_dir = repo / ".paperium" / "context-requests"
    baseline_requests = _request_snapshot(context_dir)
    try:
        before_paths, before_snapshot = _boundary_snapshot(repo, spec)
    except boundary_audit.BoundaryAuditError:
        return _failed_result(repo, spec, "boundary_audit_failed")

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
    try:
        after_paths, after_snapshot = _boundary_snapshot(repo, spec)
    except boundary_audit.BoundaryAuditError:
        return _failed_result(repo, spec, "boundary_audit_failed")
    changed_paths = list(dict.fromkeys([*before_paths, *after_paths]))
    changed_paths.extend(
        path for path in after_snapshot if path not in changed_paths
    )
    boundary_violations = boundary_audit.find_disallowed_writes(
        changed_paths=changed_paths,
        writable_paths=spec.writable_paths,
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )
    try:
        _write_managed_output(repo, stdout_path, _text(stdout))
        _write_managed_output(repo, stderr_path, _text(stderr))
    except boundary_audit.BoundaryAuditError:
        return _failed_result(repo, spec, "boundary_audit_failed")

    context_request_state = _context_request_state(
        context_dir, baseline_requests, spec.worker_id
    )
    context_request_allowed = ".paperium/context-requests" in spec.writable_paths

    status = "succeeded"
    failure_reason = None
    canonical_result_path = None

    if boundary_violations:
        status = "failed"
        failure_reason = "write_boundary_violation"
    elif timed_out:
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


def _boundary_snapshot(
    repo: Path, spec: WorkerSpec
) -> tuple[list[str], boundary_audit.Snapshot]:
    changed_paths = boundary_audit.changed_paths_from_porcelain(
        boundary_audit.git_status_porcelain(repo)
    )
    snapshot = boundary_audit.snapshot_changed_paths(repo, changed_paths)
    generated_snapshot = boundary_audit.snapshot_generated_paths(
        repo, generated_roots=_auditable_generated_roots(spec)
    )
    snapshot.update(generated_snapshot)
    return changed_paths, snapshot


def _auditable_generated_roots(spec: WorkerSpec) -> list[str]:
    roots = []
    for writable_path in spec.writable_paths:
        path = Path(writable_path)
        if path.name == ".paperium" or ".paperium" in path.parts:
            roots.append(path.as_posix())
    if spec.canonical_result_path is not None:
        canonical_parent = Path(spec.canonical_result_path).parent
        if canonical_parent.name == ".paperium" or ".paperium" in canonical_parent.parts:
            roots.append(canonical_parent.as_posix())
    return list(dict.fromkeys(roots))


def _write_managed_output(repo: Path, path: Path, text: str) -> None:
    _validate_managed_output_path(repo, path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o666)
    except OSError as exc:
        raise boundary_audit.BoundaryAuditError("managed output write failed") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(text)


def _validate_managed_output_path(repo: Path, path: Path) -> None:
    resolved_repo = repo.resolve(strict=False)
    if not _is_relative_to(path.resolve(strict=False), resolved_repo):
        raise boundary_audit.BoundaryAuditError("managed output path escapes repository")
    if _has_symlink_component(repo, path.parent):
        raise boundary_audit.BoundaryAuditError("managed output parent is a symlink")


def _has_symlink_component(repo: Path, path: Path) -> bool:
    relative = path.relative_to(repo)
    current = repo
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


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
    changed_requests = [
        request_path
        for request_path, digest in _request_snapshot(context_dir).items()
        if baseline_requests.get(request_path) != digest
    ]
    has_current_worker_request = False
    for request_path in sorted(changed_requests):
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "invalid"
        if request.get("worker_id") == worker_id:
            has_current_worker_request = True
    return "current_worker" if has_current_worker_request else "none"


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
