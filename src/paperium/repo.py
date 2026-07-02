from pathlib import Path


class RepoError(Exception):
    pass


def find_git_root(cwd: Path) -> Path | None:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def resolve_repo(repo_arg: str | None, cwd: Path) -> Path:
    if repo_arg is None:
        root = find_git_root(cwd)
        if root is None:
            raise RepoError(
                "could not resolve target repo: no --repo provided and cwd is not inside a Git repo"
            )
        path = root
    else:
        raw = Path(repo_arg).expanduser()
        path = raw if raw.is_absolute() else cwd / raw
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise RepoError(f"target repo does not exist: {path}")
    return resolved


def ensure_relative_to_repo(repo: Path, path: Path) -> Path:
    resolved_repo = repo.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_repo)
    except ValueError as exc:
        raise RepoError(f"path escapes target repo: {path}") from exc
