from __future__ import annotations

import subprocess
from hashlib import sha256
from pathlib import Path, PurePosixPath


Snapshot = dict[str, str | None]


class BoundaryAuditError(RuntimeError):
    pass


def git_status_porcelain(repo: Path) -> str:
    if not (repo / ".git").exists():
        return ""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise BoundaryAuditError("git status failed") from exc
    if result.returncode != 0:
        raise BoundaryAuditError("git status failed")
    return result.stdout


def changed_paths_from_porcelain(output: str) -> list[str]:
    paths = []
    for line in output.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", maxsplit=1)[1]
        paths.append(path)
    return paths


def snapshot_changed_paths(repo: Path, changed_paths: list[str]) -> Snapshot:
    snapshot = {}
    for changed_path in changed_paths:
        path = repo / changed_path
        snapshot[changed_path] = _file_hash(repo, path) if path.exists() else None
    return snapshot


def snapshot_generated_paths(
    repo: Path, generated_roots: list[str] | None = None
) -> Snapshot:
    snapshot = {}
    for generated_dir in _generated_dirs(repo, generated_roots):
        for path in sorted(generated_dir.rglob("*")):
            if path.is_symlink():
                raise BoundaryAuditError("generated path is a symlink")
            if path.is_file():
                repo_path = path.relative_to(repo).as_posix()
                snapshot[repo_path] = _file_hash(repo, path)
    return snapshot


def find_disallowed_writes(
    changed_paths: list[str],
    writable_paths: list[str],
    before_snapshot: Snapshot | None = None,
    after_snapshot: Snapshot | None = None,
) -> list[str]:
    ordered_paths = _ordered_paths(changed_paths, before_snapshot, after_snapshot)
    disallowed = []
    for changed_path in ordered_paths:
        if _is_writable_path(changed_path, writable_paths):
            continue
        if _is_violation(changed_path, before_snapshot, after_snapshot):
            disallowed.append(changed_path)
    return disallowed


def _ordered_paths(
    changed_paths: list[str],
    before_snapshot: Snapshot | None,
    after_snapshot: Snapshot | None,
) -> list[str]:
    ordered = dict.fromkeys(changed_paths)
    for snapshot in (before_snapshot, after_snapshot):
        if snapshot is None:
            continue
        for path in sorted(snapshot):
            ordered.setdefault(path, None)
    return list(ordered)


def _is_violation(
    changed_path: str,
    before_snapshot: Snapshot | None,
    after_snapshot: Snapshot | None,
) -> bool:
    if before_snapshot is None or after_snapshot is None:
        return True
    missing = object()
    before = before_snapshot.get(changed_path, missing)
    after = after_snapshot.get(changed_path, missing)
    return after is not missing and (before is missing or before != after)


def _is_writable_path(changed_path: str, writable_paths: list[str]) -> bool:
    changed = PurePosixPath(changed_path)
    for writable_path in writable_paths:
        writable = PurePosixPath(writable_path)
        try:
            changed.relative_to(writable)
        except ValueError:
            continue
        return True
    return False


def _generated_dirs(repo: Path, generated_roots: list[str] | None) -> list[Path]:
    dirs = []
    root_generated = repo / ".paperium"
    if root_generated.is_symlink():
        raise BoundaryAuditError("generated root is a symlink")
    if root_generated.is_dir():
        dirs.append(root_generated)
    for generated_root in generated_roots or []:
        path = _safe_generated_root(repo, generated_root)
        if path == root_generated or not path.exists():
            continue
        if path.is_symlink():
            raise BoundaryAuditError("generated root is a symlink")
        if path.is_dir():
            dirs.append(path)
    return dirs


def _safe_generated_root(repo: Path, generated_root: str) -> Path:
    root = Path(generated_root)
    if root.is_absolute() or ".." in root.parts:
        raise BoundaryAuditError("generated root escapes repository")
    path = repo / root
    if not _is_relative_to(path.resolve(strict=False), repo.resolve(strict=False)):
        raise BoundaryAuditError("generated root escapes repository")
    return path


def _file_hash(repo: Path, path: Path) -> str:
    if path.is_symlink():
        raise BoundaryAuditError("generated path is a symlink")
    if not _is_relative_to(path.resolve(strict=False), repo.resolve(strict=False)):
        raise BoundaryAuditError("generated path escapes repository")
    return sha256(path.read_bytes()).hexdigest()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
