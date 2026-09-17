from paperium.gitignore import ensure_paperium_gitignore


PAPERIUM_BLOCK = """# Paperium generated working files
.paperium/
**/.paperium/
"""


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


def test_existing_content_without_newline_is_separated_before_paperium_content(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("dist/", encoding="utf-8")

    ensure_paperium_gitignore(repo)

    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"dist/\n\n{PAPERIUM_BLOCK}"


def test_existing_content_with_one_newline_gets_one_blank_line_before_paperium_content(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("dist/\n", encoding="utf-8")

    ensure_paperium_gitignore(repo)

    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"dist/\n\n{PAPERIUM_BLOCK}"


def test_existing_content_with_blank_line_does_not_gain_extra_blank_lines(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("dist/\n\n", encoding="utf-8")

    ensure_paperium_gitignore(repo)

    assert (repo / ".gitignore").read_text(encoding="utf-8") == f"dist/\n\n{PAPERIUM_BLOCK}"


def test_complete_paperium_rules_without_final_newline_are_already_applied(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    existing = "# generated files\n.paperium/\n**/.paperium/"
    (repo / ".gitignore").write_text(existing, encoding="utf-8")

    ensure_paperium_gitignore(repo)

    assert (repo / ".gitignore").read_text(encoding="utf-8") == existing


def test_partial_preexisting_root_rule_is_not_duplicated(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text(".paperium/\n", encoding="utf-8")

    ensure_paperium_gitignore(repo)

    content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert content.count(".paperium/") == 2
    assert content.count("\n.paperium/\n") == 0
    assert content.count("**/.paperium/") == 1


def test_partial_preexisting_nested_rule_is_not_duplicated(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".gitignore").write_text("**/.paperium/\n", encoding="utf-8")

    ensure_paperium_gitignore(repo)

    content = (repo / ".gitignore").read_text(encoding="utf-8")
    assert content.count(".paperium/") == 2
    assert content.count("\n**/.paperium/\n") == 0
    assert content.count("**/.paperium/") == 1
