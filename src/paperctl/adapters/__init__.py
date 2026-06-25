from __future__ import annotations

from paperctl.adapters import (
    csv_adapter,
    json_adapter,
    jsonl_adapter,
    log_adapter,
    markdown_adapter,
    yaml_adapter,
)


ADAPTERS_BY_KIND = {
    "json": json_adapter,
    "yaml": yaml_adapter,
    "csv": csv_adapter,
    "jsonl": jsonl_adapter,
    "markdown": markdown_adapter,
    "log": log_adapter,
    "text": log_adapter,
}

ADAPTER_VERSIONS = {
    "json": json_adapter.ADAPTER_VERSION,
    "yaml": yaml_adapter.ADAPTER_VERSION,
    "csv": csv_adapter.ADAPTER_VERSION,
    "jsonl": jsonl_adapter.ADAPTER_VERSION,
    "markdown": markdown_adapter.ADAPTER_VERSION,
    "log": log_adapter.ADAPTER_VERSION,
}
