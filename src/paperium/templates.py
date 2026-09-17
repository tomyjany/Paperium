from pathlib import Path

from paperium.paths import PaperiumPaths

STYLE_SCAFFOLD = """\
# Report Style

Conversation language with the user may differ from the report language.

## Audience And Language

- Write clear, simple prose for the client audience.
- State the report language here (for example: Czech for a client in Czechia).

## Writing Rules

- Do not mention experiment IDs, folder names, internal run names, selectors,
  log states, or validation mechanics.
- Do not write like an audit log; write like a concise technical recommendation.
- Use exact numbers mainly in tables; round to 3 decimals in tables unless
  exactness matters. In prose, explain what a number means for the decision.
- One central claim per paragraph. No walls of text.

## Terminology

| Avoid | Use instead |
|---|---|
| collector status, invalid profiles, reason_codes | (do not mention) |
| accuracy | relative text quality |

Add a row whenever a revision note establishes a term rule.
"""

REPORT_TEMPLATE_SCAFFOLD = """\
<style>
img { max-width: 100%; }
.page-break { page-break-after: always; }
figure.dataset-example { text-align: center; }
figure.dataset-example img { max-height: 480px; }
</style>

{{sections}}
"""


def ensure_scaffolds(repo: Path) -> None:
    paths = PaperiumPaths(repo)
    paths.root_dir.mkdir(parents=True, exist_ok=True)
    if not paths.style_path.exists():
        paths.style_path.write_text(STYLE_SCAFFOLD, encoding="utf-8")
    if not paths.report_template_path.exists():
        paths.report_template_path.write_text(REPORT_TEMPLATE_SCAFFOLD, encoding="utf-8")
