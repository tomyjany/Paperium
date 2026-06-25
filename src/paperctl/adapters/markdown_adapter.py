from __future__ import annotations

from pathlib import Path
from typing import Any

from paperctl.adapters._text import read_utf8
from paperctl._support.redaction import escape_markdown_text, redact_text


ADAPTER_NAME = "markdown"
ADAPTER_VERSION = "1"


def extract(
    path: Path,
    *,
    source_path: str,
    source_hash: str,
    preview_lines: int,
    max_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    previews: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    redactions = 0
    try:
        bounded = read_utf8(path, max_bytes=max_bytes)
    except OSError as exc:
        diagnostics.append(
            _record(source_path, source_hash, f"could not read Markdown: {exc}", 1, 1)
        )
        return previews, diagnostics, warnings, redactions
    except UnicodeDecodeError as exc:
        diagnostics.append(
            _record(source_path, source_hash, f"could not decode Markdown as UTF-8: {exc}", 1, 1)
        )
        return previews, diagnostics, warnings, redactions

    lines = bounded.text.splitlines()

    for line_number, line in enumerate(lines, start=1):
        if len(previews) >= preview_lines:
            break
        if line.lstrip().startswith("#"):
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
    if not previews and lines:
        excerpt = "\n".join(lines[:preview_lines])
        redacted, count = redact_text(excerpt)
        redactions += count
        previews.append(
            _record(
                source_path,
                source_hash,
                escape_markdown_text(redacted),
                1,
                min(len(lines), preview_lines),
            )
        )
    diagnostics.append(
        _record(source_path, source_hash, f"line_count={len(lines)}", 1, max(1, len(lines)))
    )
    if bounded.truncated:
        warnings.append(
            _record(
                source_path,
                source_hash,
                "file truncated at extraction byte limit",
                1,
                max(1, len(lines)),
                warning_type="byte_limit_truncated",
                inspected_byte_count=bounded.inspected_byte_count,
                omitted_byte_count=bounded.omitted_byte_count,
            )
        )
    return previews, diagnostics, warnings, redactions


def _record(
    source_path: str,
    source_hash: str,
    message: str,
    line_start: int,
    line_end: int,
    **fields: Any,
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
        **fields,
    }
