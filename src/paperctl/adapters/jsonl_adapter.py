from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from paperctl.adapters._text import read_utf8
from paperctl._support.redaction import redact_nested_value, redact_text


ADAPTER_NAME = "jsonl"
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
    numeric_fields: dict[str, list[float]] = {}
    non_finite_counts: dict[str, int] = {}
    line_count = 0
    try:
        bounded = read_utf8(path, max_bytes=max_bytes)
    except UnicodeDecodeError as exc:
        diagnostics.append(
            _record(source_path, source_hash, f"could not decode JSONL as UTF-8: {exc}", 1, 1)
        )
        return previews, diagnostics, warnings, redactions
    except OSError as exc:
        diagnostics.append(_record(source_path, source_hash, f"could not read JSONL: {exc}", 1, 1))
        return previews, diagnostics, warnings, redactions

    for line_number, line in enumerate(bounded.text.splitlines(), start=1):
        line_count = line_number
        text = line.rstrip("\n")
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            if line_number <= preview_rows:
                redacted, count = redact_text(text)
                redactions += count
                previews.append(
                    _record(source_path, source_hash, redacted, line_number, line_number)
                )
            continue
        if line_number <= preview_rows:
            redacted_value, count = redact_nested_value(value)
            redactions += count
            rendered = json.dumps(redacted_value, sort_keys=True)
            previews.append(_record(source_path, source_hash, rendered, line_number, line_number))
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, int | float) and not isinstance(child, bool):
                    numeric_value = float(child)
                    if math.isfinite(numeric_value):
                        numeric_fields.setdefault(key, []).append(numeric_value)
                    else:
                        non_finite_counts[key] = non_finite_counts.get(key, 0) + 1
                        warnings.append(
                            _record(
                                source_path,
                                source_hash,
                                f"non-finite numeric value omitted from field {key}",
                                line_number,
                                line_number,
                                warning_type="non_finite_numeric",
                                field=key,
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
                max(1, line_count),
                warning_type="byte_limit_truncated",
                inspected_byte_count=bounded.inspected_byte_count,
                omitted_byte_count=bounded.omitted_byte_count,
            )
        )

    for key in sorted(set(numeric_fields) | set(non_finite_counts)):
        values = numeric_fields.get(key, [])
        if values:
            diagnostics.append(
                _record(
                    source_path,
                    source_hash,
                    f"numeric field {key}: count={len(values)} min={min(values)} max={max(values)}",
                    1,
                    max(1, line_count),
                    calculation_label="jsonl_numeric_field_summary",
                    field=key,
                    inspected_line_start=1,
                    inspected_line_end=line_count,
                    inspected_line_count=line_count,
                    byte_limit_truncated=bounded.truncated,
                    inspected_byte_count=bounded.inspected_byte_count,
                    omitted_byte_count=bounded.omitted_byte_count,
                    numeric_value_count=len(values),
                    omitted_value_count=line_count - len(values),
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
