from __future__ import annotations

from pathlib import Path
from typing import Any

ENTRY_KEYS = {"question_path", "included_experiments", "answer_focus"}


class QuestionFocusError(Exception):
    pass


def validate_question_focus(
    approved_included_experiments: Any,
    entries: Any,
) -> list[dict[str, Any]]:
    approved = _validate_approved_included_experiments(approved_included_experiments)
    validated_entries = _validate_entries(entries)
    seen: set[str] = set()

    for entry in validated_entries:
        question_path = entry["question_path"]
        entry_seen: set[str] = set()
        for experiment_path in entry["included_experiments"]:
            if experiment_path in entry_seen:
                raise QuestionFocusError(
                    f"question focus duplicates included experiment within entry: {experiment_path}"
                )
            entry_seen.add(experiment_path)

            if experiment_path in seen:
                raise QuestionFocusError(
                    f"question focus duplicates included experiment: {experiment_path}"
                )
            if experiment_path not in approved:
                raise QuestionFocusError(
                    f"question focus includes unapproved experiment: {experiment_path}"
                )
            if _question_folder_for_experiment(experiment_path) != question_path:
                raise QuestionFocusError(
                    f"experiment is not under question folder {question_path}: {experiment_path}"
                )
            seen.add(experiment_path)

    missing = approved - seen
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise QuestionFocusError(f"question focus missing approved experiment(s): {missing_list}")

    return validated_entries


def render_question_focus_markdown(entries: Any) -> str:
    validated_entries = _validate_entries(entries)
    lines = ["# Paperium Question Focus", ""]

    for index, entry in enumerate(validated_entries):
        if index:
            lines.append("")
        lines.extend(
            [
                f"## {_markdown_list_text(entry['question_path'])}",
                "",
                f"- Answer focus: {_markdown_list_text(entry['answer_focus'])}",
                "- Included experiments:",
            ]
        )
        for experiment_path in entry["included_experiments"]:
            lines.append(f"  - {_markdown_list_text(experiment_path)}")

    return "\n".join(lines) + "\n"


def write_question_focus(
    path: Path,
    approved_included_experiments: Any,
    entries: Any,
) -> None:
    validated_entries = validate_question_focus(approved_included_experiments, entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_question_focus_markdown(validated_entries))


def _validate_approved_included_experiments(
    approved_included_experiments: Any,
) -> set[str]:
    if isinstance(approved_included_experiments, str) or not isinstance(
        approved_included_experiments, (list, tuple, set)
    ):
        raise QuestionFocusError("approved included experiments must be a collection")

    approved = set()
    for experiment_path in approved_included_experiments:
        if not isinstance(experiment_path, str) or not experiment_path:
            raise QuestionFocusError("approved included experiments must be non-empty strings")
        if experiment_path in approved:
            raise QuestionFocusError(f"duplicate approved included experiment: {experiment_path}")
        approved.add(experiment_path)

    return approved


def _validate_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise QuestionFocusError("question focus entries must be a list")

    return [_validate_entry(entry) for entry in entries]


def _validate_entry(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise QuestionFocusError("question focus entry must be an object")
    if set(entry) != ENTRY_KEYS:
        raise QuestionFocusError("question focus entry has invalid fields")

    question_path = entry["question_path"]
    if not isinstance(question_path, str) or not question_path.strip():
        raise QuestionFocusError("question_path must be a non-empty string")

    included_experiments = entry["included_experiments"]
    if not isinstance(included_experiments, list) or not included_experiments:
        raise QuestionFocusError("included_experiments must be a non-empty list of strings")
    for experiment_path in included_experiments:
        if not isinstance(experiment_path, str) or not experiment_path:
            raise QuestionFocusError("included_experiments must contain non-empty strings")

    answer_focus = entry["answer_focus"]
    if not isinstance(answer_focus, str) or not answer_focus.strip():
        raise QuestionFocusError("answer_focus must be a non-empty string")

    return {
        "question_path": question_path,
        "included_experiments": included_experiments,
        "answer_focus": answer_focus,
    }


def _question_folder_for_experiment(experiment_path: str) -> str:
    marker = "/experiments/"
    if marker not in experiment_path:
        raise QuestionFocusError(f"experiment path is not mappable: {experiment_path}")
    return experiment_path.split(marker, maxsplit=1)[0]


def _markdown_list_text(value: str) -> str:
    return " ".join(value.splitlines())
