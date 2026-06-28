from paperium.gitignore import ensure_paperium_gitignore


def test_adds_paperium_ignore_rules(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ensure_paperium_gitignore(repo)
    assert ".paperium/" in (repo / ".gitignore").read_text()
    assert "**/.paperium/" in (repo / ".gitignore").read_text()


def test_gitignore_update_is_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    ensure_paperium_gitignore(repo)
    first = (repo / ".gitignore").read_text()
    ensure_paperium_gitignore(repo)
    assert (repo / ".gitignore").read_text() == first
