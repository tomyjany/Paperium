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
MARKDOWN_ESCAPE_RE = re.compile(r"([\\`*_{}\[\]()#+\-!|<>])")
REDACTED_SENTINEL = "\0REDACTED\0"


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


def redact_nested_value(value: Any, key: str = "") -> tuple[Any, int]:
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        redactions = 0
        for child_key, child_value in value.items():
            child, count = redact_nested_value(child_value, str(child_key))
            redacted[child_key] = child
            redactions += count
        return redacted, redactions
    if isinstance(value, list):
        redacted_items = []
        redactions = 0
        for item in value:
            child, count = redact_nested_value(item, key)
            redacted_items.append(child)
            redactions += count
        return redacted_items, redactions
    return redact_value_for_key(key, value)


def escape_markdown_text(text: str) -> str:
    protected = text.replace(REDACTED, REDACTED_SENTINEL)
    escaped = MARKDOWN_ESCAPE_RE.sub(r"\\\1", protected)
    return escaped.replace(REDACTED_SENTINEL, REDACTED)
