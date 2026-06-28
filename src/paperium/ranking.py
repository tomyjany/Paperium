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
ENTRY_KEYS = {"experiment", "bucket", "reason"}


class RankingError(Exception):
    pass


def validate_ranking_entries(
    approved_experiment_paths: set[str], entries: Any
) -> list[dict[str, str]]:
    validated_entries = _validate_entry_list(entries)
    approved = _validate_approved_experiment_paths(approved_experiment_paths)
    seen: set[str] = set()

    for entry in validated_entries:
        experiment = entry["experiment"]
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
                lines.append(f"| {entry['experiment']} | {entry['reason']} |")

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
    if not isinstance(approved_experiment_paths, set) or not all(
        isinstance(path, str) for path in approved_experiment_paths
    ):
        raise RankingError("approved experiment paths must be a set of strings")
    return approved_experiment_paths


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

    experiment = entry["experiment"]
    if not isinstance(experiment, str) or not experiment:
        raise RankingError("ranking entry experiment must be a non-empty string")

    bucket = entry["bucket"]
    if not isinstance(bucket, str) or bucket not in ALLOWED_BUCKETS:
        raise RankingError(f"invalid ranking bucket: {bucket}")

    reason = entry["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise RankingError("ranking entry reason must be a non-empty string")

    return {"experiment": experiment, "bucket": bucket, "reason": reason}
