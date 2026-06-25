from __future__ import annotations

import csv
import io
import math
from pathlib import Path
from typing import Any

from paperctl.adapters._text import read_utf8
from paperctl._support.redaction import key_is_secret_like, redact_value_for_key


ADAPTER_NAME = "csv"
ADAPTER_VERSION = "1"


def extract(
    path: Path,
    *,
    source_path: str,
    source_hash: str,
    preview_rows: int,
    max_bytes: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    previews: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    redactions = 0
    numeric_columns: dict[str, list[float]] = {}
    non_finite_counts: dict[str, int] = {}
    row_count = 0
    try:
        bounded = read_utf8(path, max_bytes=max_bytes)
        reader = csv.DictReader(io.StringIO(bounded.text, newline=""))
        for index, row in enumerate(reader, start=1):
            row_count = index
            if index <= preview_rows:
                redacted_row: dict[str, str] = {}
                for key, value in row.items():
                    redacted_value, count = redact_value_for_key(key or "", value or "")
                    redactions += count
                    redacted_row[key] = str(redacted_value)
                previews.append(
                    _record(
                        source_path,
                        source_hash,
                        f"row {index}: {redacted_row}",
                        index + 1,
                        index + 1,
                    )
                )
            for key, value in row.items():
                if key_is_secret_like(key or ""):
                    continue
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    pass
                else:
                    if math.isfinite(numeric_value):
                        numeric_columns.setdefault(key, []).append(numeric_value)
                    else:
                        non_finite_counts[key] = non_finite_counts.get(key, 0) + 1
                        warnings.append(
                            _record(
                                source_path,
                                source_hash,
                                f"non-finite numeric value omitted from column {key}",
                                index + 1,
                                index + 1,
                                warning_type="non_finite_numeric",
                                column=key,
                                numeric_value_kind=_non_finite_kind(numeric_value),
                            )
                        )
        if bounded.truncated:
            warnings.append(
                _record(
                    source_path,
                    source_hash,
                    "file truncated at extraction byte limit",
                    1,
                    max(1, row_count + 1),
                    warning_type="byte_limit_truncated",
                    inspected_byte_count=bounded.inspected_byte_count,
                    omitted_byte_count=bounded.omitted_byte_count,
                )
            )
    except UnicodeDecodeError as exc:
        diagnostics.append(
            _record(source_path, source_hash, f"could not decode CSV as UTF-8: {exc}", 1, 1)
        )
        return previews, diagnostics, warnings, redactions
    except OSError as exc:
        diagnostics.append(_record(source_path, source_hash, f"could not read CSV: {exc}", 1, 1))
        return previews, diagnostics, warnings, redactions

    for key in sorted(set(numeric_columns) | set(non_finite_counts)):
        values = numeric_columns.get(key, [])
        if values:
            diagnostics.append(
                _record(
                    source_path,
                    source_hash,
                    f"numeric column {key}: count={len(values)} min={min(values)} max={max(values)}",
                    2,
                    row_count + 1,
                    calculation_label="csv_numeric_column_summary",
                    column=key,
                    inspected_row_start=1,
                    inspected_row_end=row_count,
                    inspected_row_count=row_count,
                    numeric_value_count=len(values),
                    omitted_value_count=row_count - len(values),
                    non_finite_omitted_count=non_finite_counts.get(key, 0),
                    summary={"count": len(values), "max": max(values), "min": min(values)},
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


def _non_finite_kind(value: float) -> str:
    if math.isnan(value):
        return "nan"
    return "infinity"
