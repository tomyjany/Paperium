from pathlib import Path


PAPERIUM_GITIGNORE_COMMENT = "# Paperium generated working files"
PAPERIUM_GITIGNORE_RULES = (".paperium/", "**/.paperium/")


def ensure_paperium_gitignore(repo: Path) -> None:
    gitignore = repo / ".gitignore"
    content = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    existing_rules = {line.strip() for line in content.splitlines()}
    missing_rules = [rule for rule in PAPERIUM_GITIGNORE_RULES if rule not in existing_rules]
    if not missing_rules:
        return

    separator = ""
    if content and not content.endswith("\n\n"):
        separator = "\n" if content.endswith("\n") else "\n\n"

    paperium_content = "\n".join([PAPERIUM_GITIGNORE_COMMENT, *missing_rules, ""])
    gitignore.write_text(f"{content}{separator}{paperium_content}", encoding="utf-8")
