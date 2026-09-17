from paperium.notes import extract_notes

FACT_LOCK = "Keep all numbers, table rows, and claims unchanged unless a user note explicitly asks."

_OUTPUT_CONTRACT = (
    "Output only the final Markdown section. Write it to the output file below.\n"
    "Do not include commentary, experiment IDs, folder names, artifact paths,\n"
    "selectors, or internal validation terms."
)


def build_writer_prompt(
    *,
    title: str,
    facts: str,
    style: str,
    output_path: str,
    draft: str | None = None,
) -> str:
    if draft is None or not draft.strip():
        return _initial_prompt(title=title, facts=facts, style=style, output_path=output_path)
    return _revision_prompt(
        title=title, facts=facts, style=style, output_path=output_path, draft=draft
    )


def _initial_prompt(*, title: str, facts: str, style: str, output_path: str) -> str:
    return "\n".join(
        [
            "You are writing one section of a client-facing report.",
            "",
            _OUTPUT_CONTRACT,
            f"Output file: {output_path}",
            "",
            "Section heading (use verbatim):",
            f"## {title}",
            "",
            "Facts and purpose (use only these facts; do not add new claims):",
            facts,
            "",
            "Style (follow exactly):",
            style,
            "",
        ]
    )


def _revision_prompt(*, title: str, facts: str, style: str, output_path: str, draft: str) -> str:
    # `facts` is intentionally omitted here: FACT_LOCK instructs the writer to keep
    # existing claims unchanged, and the current draft already carries the content;
    # re-supplying facts would only invite drift between the two sources.
    notes = extract_notes(draft)
    numbered = [f"{index}. {note}" for index, note in enumerate(notes, start=1)]
    return "\n".join(
        [
            "You are revising one section of a client-facing report.",
            "",
            _OUTPUT_CONTRACT,
            f"Output file: {output_path}",
            "",
            FACT_LOCK,
            "",
            "Section heading (use verbatim):",
            f"## {title}",
            "",
            "User notes to address (remove the inline /.../ notes from the text):",
            *(numbered or ["(no inline notes found; improve per style only)"]),
            "",
            "Style (follow exactly):",
            style,
            "",
            "Current draft (inline notes still present):",
            "",
            draft,
            "",
        ]
    )
