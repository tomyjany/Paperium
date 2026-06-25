from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paperctl._support.redaction import redact_value_for_key


ADAPTER_NAME = "json"
ADAPTER_VERSION = "1"


class JsonAdapterError(ValueError):
    pass


def load(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise JsonAdapterError(str(exc)) from exc


def resolve_pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise JsonAdapterError(f"invalid JSON Pointer: {pointer}")
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(pointer)
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                index = int(part)
            except ValueError as exc:
                raise KeyError(pointer) from exc
            try:
                current = current[index]
            except IndexError as exc:
                raise KeyError(pointer) from exc
            continue
        raise KeyError(pointer)
    return current


def scalar_observations(
    document: Any,
    *,
    source_path: str,
    source_hash: str,
    limit: int,
    max_depth: int,
    excluded_selectors: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    excluded = excluded_selectors or set()
    values: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    redactions = 0
    truncated = False

    def visit(value: Any, pointer: str, depth: int, key: str | None) -> None:
        nonlocal redactions, truncated
        if truncated:
            return
        if depth > max_depth:
            warnings.append(
                _record(source_path, source_hash, pointer, "maximum nesting depth reached")
            )
            return
        if _is_scalar(value):
            if not _is_excluded(pointer, excluded):
                redacted, count = redact_value_for_key(key or "", value)
                redactions += count
                if len(values) >= limit:
                    truncated = True
                    return
                values.append(
                    {
                        "value": redacted,
                        "value_type": value_type(redacted),
                        "unit": None,
                        "source": {
                            "path": source_path,
                            "source_hash": source_hash,
                            "selector_type": "json_pointer",
                            "selector": pointer,
                            "adapter": ADAPTER_NAME,
                            "adapter_version": ADAPTER_VERSION,
                        },
                    }
                )
            return
        if isinstance(value, dict):
            for child_key in sorted(value):
                visit(
                    value[child_key],
                    f"{pointer}/{_escape_pointer(child_key)}",
                    depth + 1,
                    child_key,
                )
            return
        if isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{pointer}/{index}", depth + 1, None)

    visit(document, "", 0, None)
    return values, warnings, redactions, truncated


def value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def is_expected_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    if expected_type == "string":
        return isinstance(value, str)
    return False


def _record(source_path: str, source_hash: str, selector: str, message: str) -> dict[str, Any]:
    return {
        "source": {
            "path": source_path,
            "source_hash": source_hash,
            "selector_type": "json_pointer",
            "selector": selector,
            "adapter": ADAPTER_NAME,
            "adapter_version": ADAPTER_VERSION,
        },
        "message": message,
    }


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _escape_pointer(part: str) -> str:
    return part.replace("~", "~0").replace("/", "~1")


def _is_excluded(pointer: str, excluded: set[str]) -> bool:
    return pointer in excluded or any(
        pointer.startswith(f"{excluded_pointer}/") for excluded_pointer in excluded
    )
