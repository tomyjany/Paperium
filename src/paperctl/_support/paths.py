from __future__ import annotations

import re
from pathlib import Path, PurePosixPath


_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def is_repo_relative_posix(path: str) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or _WINDOWS_DRIVE_RE.match(path) or "\\" in path:
        return False
    return ".." not in PurePosixPath(path).parts


def resolve_repo_relative_path(repo: Path, path: str) -> Path:
    if not is_repo_relative_posix(path):
        raise ValueError(f"path must be repository-relative POSIX: {path!r}")

    repo_root = repo.resolve()
    resolved = (repo_root / Path(*PurePosixPath(path).parts)).resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"resolved path is outside repository: {path!r}") from exc
    return resolved
