import pytest

from paperium.repo import RepoError, ensure_relative_to_repo, resolve_repo


def test_resolve_repo_requires_existing_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert resolve_repo(str(repo), cwd=tmp_path) == repo.resolve()


def test_resolve_repo_relative_path_uses_cwd(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert resolve_repo("repo", cwd=tmp_path) == repo.resolve()


def test_resolve_repo_defaults_to_current_git_root(tmp_path):
    repo = tmp_path / "repo"
    nested = repo / "a/b"
    nested.mkdir(parents=True)
    (repo / ".git").mkdir()
    assert resolve_repo(None, cwd=nested) == repo.resolve()


def test_resolve_repo_rejects_missing(tmp_path):
    with pytest.raises(RepoError):
        resolve_repo(str(tmp_path / "missing"), cwd=tmp_path)


def test_ensure_relative_rejects_outside_repo(tmp_path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    with pytest.raises(RepoError):
        ensure_relative_to_repo(repo, outside)
