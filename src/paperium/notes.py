import re

_NOTE_PATTERN = re.compile(
    r"(?:(?<=\s)|(?<=^)|(?<=\|)|(?<=\())/([^/\n]+?)/(?=[\s.,;:)|]|$)",
    re.MULTILINE,
)


def extract_notes(text: str) -> list[str]:
    notes: list[str] = []
    for match in _NOTE_PATTERN.finditer(text):
        content = match.group(1).strip()
        if " " in content:
            notes.append(content)
    return notes
