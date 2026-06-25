from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from paperctl.adapters import json_adapter


ADAPTER_NAME = "yaml"
ADAPTER_VERSION = "1"


class YamlAdapterError(ValueError):
    pass


def load(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise YamlAdapterError(str(exc)) from exc


def resolve_pointer(document: Any, pointer: str) -> Any:
    return json_adapter.resolve_pointer(document, pointer)


def scalar_observations(
    document: Any,
    *,
    source_path: str,
    source_hash: str,
    limit: int,
    max_depth: int,
    excluded_selectors: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    values, warnings, redactions, truncated = json_adapter.scalar_observations(
        document,
        source_path=source_path,
        source_hash=source_hash,
        limit=limit,
        max_depth=max_depth,
        excluded_selectors=excluded_selectors,
    )
    for value in values:
        value["source"]["adapter"] = ADAPTER_NAME
        value["source"]["adapter_version"] = ADAPTER_VERSION
    for warning in warnings:
        warning["source"]["adapter"] = ADAPTER_NAME
        warning["source"]["adapter_version"] = ADAPTER_VERSION
    return values, warnings, redactions, truncated
