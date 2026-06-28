from pathlib import Path


PAPERIUM_GITIGNORE_BLOCK = """# Paperium generated working files
.paperium/
**/.paperium/
"""


def ensure_paperium_gitignore(repo: Path) -> None:
    gitignore = repo / ".gitignore"
    content = gitignore.read_text() if gitignore.exists() else ""
    if PAPERIUM_GITIGNORE_BLOCK in content:
        return

    separator = ""
    if content and not content.endswith("\n\n"):
        separator = "\n" if content.endswith("\n") else "\n\n"

    gitignore.write_text(f"{content}{separator}{PAPERIUM_GITIGNORE_BLOCK}")
