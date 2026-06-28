from __future__ import annotations

from pathlib import Path
from typing import Any

ALLOWED_DISPOSITIONS = {
    "included",
    "excluded",
    "deferred",
    "artifact_missing",
    "fact_check_failed",
    "needs_human_review",
    "skipped",
}
ROW_KEYS = {"path", "disposition", "reason"}


class DispositionError(Exception):
    pass


def validate_dispositions(selected_paths: Any, rows: Any) -> list[dict[str, str]]:
    selected = _validate_selected_paths(selected_paths)
    validated_rows = _validate_rows(rows)
    seen: set[str] = set()

    for row in validated_rows:
        path = row["path"]
        if path not in selected:
            raise DispositionError(f"dispositions include unselected experiment: {path}")
        if path in seen:
            raise DispositionError(f"dispositions include duplicate experiment: {path}")
        seen.add(path)

    missing = selected - seen
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise DispositionError(f"dispositions missing selected experiment(s): {missing_list}")

    return validated_rows


def render_dispositions_markdown(rows: Any) -> str:
    validated_rows = _validate_rows(rows)
    lines = [
        "# Paperium Experiment Dispositions",
        "",
        "| Experiment | Disposition | Reason |",
        "|---|---|---|",
    ]

    for row in validated_rows:
        path = _markdown_table_cell(row["path"])
        disposition = _markdown_table_cell(row["disposition"])
        reason = _markdown_table_cell(row["reason"])
        lines.append(f"| {path} | {disposition} | {reason} |")

    return "\n".join(lines) + "\n"


def write_dispositions(path: Path, selected_paths: Any, rows: Any) -> None:
    validated_rows = validate_dispositions(selected_paths, rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dispositions_markdown(validated_rows))


def _validate_selected_paths(selected_paths: Any) -> set[str]:
    if isinstance(selected_paths, str) or not isinstance(selected_paths, (list, tuple, set)):
        raise DispositionError("selected paths must be a list of strings")

    selected = set()
    for path in selected_paths:
        if not isinstance(path, str) or not path:
            raise DispositionError("selected paths must be non-empty strings")
        if path in selected:
            raise DispositionError(f"duplicate selected path: {path}")
        selected.add(path)

    return selected


def _validate_rows(rows: Any) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        raise DispositionError("disposition rows must be a list")

    validated_rows = []
    for row in rows:
        validated_rows.append(_validate_row(row))
    return validated_rows


def _validate_row(row: Any) -> dict[str, str]:
    if not isinstance(row, dict):
        raise DispositionError("disposition row must be an object")
    if set(row) != ROW_KEYS:
        raise DispositionError("disposition row has invalid fields")

    path = row["path"]
    if not isinstance(path, str) or not path:
        raise DispositionError("disposition row path must be a non-empty string")

    disposition = row["disposition"]
    if not isinstance(disposition, str) or disposition not in ALLOWED_DISPOSITIONS:
        raise DispositionError(f"invalid disposition: {disposition}")

    reason = row["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise DispositionError("disposition row reason must be a non-empty string")

    return {"path": path, "disposition": disposition, "reason": reason}


def _markdown_table_cell(value: str) -> str:
    return " ".join(value.splitlines()).replace("|", "\\|")
