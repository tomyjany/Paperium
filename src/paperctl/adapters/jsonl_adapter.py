from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paperctl._support.redaction import redact_text


ADAPTER_NAME = "jsonl"
ADAPTER_VERSION = "1"


def extract(
    path: Path,
    *,
    source_path: str,
    source_hash: str,
    preview_rows: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    previews: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    redactions = 0
    numeric_fields: dict[str, list[float]] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.rstrip("\n")
                if line_number <= preview_rows:
                    redacted, count = redact_text(text)
                    redactions += count
                    previews.append(
                        _record(source_path, source_hash, redacted, line_number, line_number)
                    )
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    for key, child in value.items():
                        if isinstance(child, int | float) and not isinstance(child, bool):
                            numeric_fields.setdefault(key, []).append(float(child))
    except OSError as exc:
        diagnostics.append(_record(source_path, source_hash, f"could not read JSONL: {exc}", 1, 1))
        return previews, diagnostics, redactions

    for key in sorted(numeric_fields):
        values = numeric_fields[key]
        if values:
            diagnostics.append(
                _record(
                    source_path,
                    source_hash,
                    f"numeric field {key}: count={len(values)} min={min(values)} max={max(values)}",
                    1,
                    max(1, len(values)),
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
