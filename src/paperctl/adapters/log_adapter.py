from __future__ import annotations

from pathlib import Path
from typing import Any

from paperctl._support.redaction import escape_markdown_text, redact_text


ADAPTER_NAME = "log"
ADAPTER_VERSION = "1"


def extract(
    path: Path,
    *,
    source_path: str,
    source_hash: str,
    head_lines: int,
    tail_lines: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    previews: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    redactions = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        diagnostics.append(_record(source_path, source_hash, f"could not read log: {exc}", 1, 1))
        return previews, diagnostics, redactions

    selected: list[tuple[int, str]] = []
    for index, line in enumerate(lines[:head_lines], start=1):
        selected.append((index, line))
    tail_start = max(head_lines, len(lines) - tail_lines)
    for index, line in enumerate(lines[tail_start:], start=tail_start + 1):
        selected.append((index, line))
    seen: set[int] = set()
    for line_number, line in selected:
        if line_number in seen:
            continue
        seen.add(line_number)
        redacted, count = redact_text(line)
        redactions += count
        previews.append(
            _record(
                source_path,
                source_hash,
                escape_markdown_text(redacted),
                line_number,
                line_number,
            )
        )
    warning_count = sum(1 for line in lines if "warning" in line.lower())
    error_count = sum(1 for line in lines if "error" in line.lower())
    diagnostics.append(
        _record(
            source_path,
            source_hash,
            f"line_count={len(lines)} warning_count={warning_count} error_count={error_count}",
            1,
            max(1, len(lines)),
        )
    )
    return previews, diagnostics, redactions


def _record(
    source_path: str, source_hash: str, message: str, line_start: int, line_end: int
) -> dict[str, Any]:
    return {
        "source": {
            "path": source_path,
            "source_hash": source_hash,
            "selector_type": "line_range",
            "line_start": line_start,
            "line_end": line_end,
            "adapter": ADAPTER_NAME,
            "adapter_version": ADAPTER_VERSION,
        },
        "message": message,
    }
