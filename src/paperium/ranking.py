from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALLOWED_BUCKETS = {"include", "exclude", "defer"}
BUCKET_ORDER = (
    ("include", "Include"),
    ("exclude", "Exclude"),
    ("defer", "Defer"),
)
ENTRY_KEYS = {"experiment_path", "bucket", "reason"}


class RankingError(Exception):
    pass


def validate_ranking_entries(approved_experiment_paths: Any, entries: Any) -> list[dict[str, str]]:
    validated_entries = _validate_entry_list(entries)
    approved = _validate_approved_experiment_paths(approved_experiment_paths)
    seen: set[str] = set()

    for entry in validated_entries:
        experiment = entry["experiment_path"]
        if experiment not in approved:
            raise RankingError(f"ranking includes unapproved experiment: {experiment}")
        if experiment in seen:
            raise RankingError(f"ranking includes duplicate experiment: {experiment}")
        seen.add(experiment)

    missing = approved - seen
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise RankingError(f"ranking missing approved experiment(s): {missing_list}")

    return validated_entries


def render_ranking_markdown(entries: Any) -> str:
    validated_entries = _validate_entry_list(entries)
    lines: list[str] = []

    for bucket, heading in BUCKET_ORDER:
        if lines:
            lines.append("")
        lines.extend(
            [
                f"## {heading}",
                "",
                "| Experiment | Reason |",
                "| --- | --- |",
            ]
        )
        for entry in validated_entries:
            if entry["bucket"] == bucket:
                experiment = _markdown_table_cell(entry["experiment_path"])
                reason = _markdown_table_cell(entry["reason"])
                lines.append(f"| {experiment} | {reason} |")

    return "\n".join(lines) + "\n"


def write_ranking_artifacts(md_path: Path, json_path: Path, entries: Any) -> None:
    validated_entries = _validate_entry_list(entries)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_ranking_markdown(validated_entries))
    json_path.write_text(
        json.dumps({"entries": validated_entries}, indent=2, sort_keys=True) + "\n"
    )


def _validate_approved_experiment_paths(approved_experiment_paths: Any) -> set[str]:
    if isinstance(approved_experiment_paths, str) or not isinstance(
        approved_experiment_paths, (list, tuple, set)
    ):
        raise RankingError("approved experiment paths must be a list of strings")

    approved = set()
    for path in approved_experiment_paths:
        if not isinstance(path, str) or not path:
            raise RankingError("approved experiment paths must be non-empty strings")
        if path in approved:
            raise RankingError(f"duplicate approved experiment path: {path}")
        approved.add(path)

    return approved


def _validate_entry_list(entries: Any) -> list[dict[str, str]]:
    if not isinstance(entries, list):
        raise RankingError("ranking entries must be a list")

    validated_entries = []
    for entry in entries:
        validated_entries.append(_validate_entry(entry))
    return validated_entries


def _validate_entry(entry: Any) -> dict[str, str]:
    if not isinstance(entry, dict):
        raise RankingError("ranking entry must be an object")
    if set(entry) != ENTRY_KEYS:
        raise RankingError("ranking entry has invalid fields")

    experiment = entry["experiment_path"]
    if not isinstance(experiment, str) or not experiment:
        raise RankingError("ranking entry experiment_path must be a non-empty string")

    bucket = entry["bucket"]
    if not isinstance(bucket, str) or bucket not in ALLOWED_BUCKETS:
        raise RankingError(f"invalid ranking bucket: {bucket}")

    reason = entry["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise RankingError("ranking entry reason must be a non-empty string")

    return {"experiment_path": experiment, "bucket": bucket, "reason": reason}


def _markdown_table_cell(value: str) -> str:
    return " ".join(value.splitlines()).replace("|", "\\|")
