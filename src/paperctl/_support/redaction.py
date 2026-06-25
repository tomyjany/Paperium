from __future__ import annotations

import re
from typing import Any


SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api_key|apikey|access_key|private_key)",
    re.IGNORECASE,
)
ASSIGNMENT_SECRET_RE = re.compile(
    r"(?P<prefix>\b[\w.-]*(?:password|passwd|secret|token|api_key|apikey|access_key|private_key)"
    r"[\w.-]*\s*[:=]\s*)(?P<quote>['\"]?)(?P<value>[^\s,'\"]+)(?P=quote)",
    re.IGNORECASE,
)
REDACTED = "[REDACTED]"


def key_is_secret_like(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key))


def redact_text(text: str) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"{match.group('prefix')}{match.group('quote')}{REDACTED}{match.group('quote')}"

    return ASSIGNMENT_SECRET_RE.sub(replace, text), count


def redact_value_for_key(key: str, value: Any) -> tuple[Any, int]:
    if key_is_secret_like(key) and isinstance(value, str):
        return REDACTED, 1
    if isinstance(value, str):
        return redact_text(value)
    return value, 0
