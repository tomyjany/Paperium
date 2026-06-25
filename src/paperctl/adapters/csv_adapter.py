from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from paperctl._support.redaction import redact_value_for_key


ADAPTER_NAME = "csv"
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
    numeric_columns: dict[str, list[float]] = {}
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader, start=1):
                if index <= preview_rows:
                    redacted_row: dict[str, str] = {}
                    for key, value in row.items():
                        redacted_value, count = redact_value_for_key(key or "", value or "")
                        redactions += count
                        redacted_row[key] = str(redacted_value)
                    previews.append(
                        _record(
                            source_path, source_hash, f"row {index}: {redacted_row}", index, index
                        )
                    )
                for key, value in row.items():
                    try:
                        numeric_columns.setdefault(key, []).append(float(value))
                    except (TypeError, ValueError):
                        pass
    except OSError as exc:
        diagnostics.append(_record(source_path, source_hash, f"could not read CSV: {exc}", 1, 1))
        return previews, diagnostics, redactions

    for key in sorted(numeric_columns):
        values = numeric_columns[key]
        if values:
            diagnostics.append(
                _record(
                    source_path,
                    source_hash,
                    f"numeric column {key}: count={len(values)} min={min(values)} max={max(values)}",
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
