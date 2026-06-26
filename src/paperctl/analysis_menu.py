from __future__ import annotations

import json
import select
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TextIO

from jsonschema import ValidationError

from paperctl._support.schema import validate_artifact
from paperctl.analysis import preflight_experiment
from paperctl.inventory import load_manifest


class ExperimentMenuError(ValueError):
    pass


@dataclass(frozen=True)
class ExperimentMenuRow:
    question_path: str
    experiment_path: str
    evidence_path: str
    enabled: bool = True
    disabled_reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentMenuGroup:
    question_path: str
    rows: tuple[ExperimentMenuRow, ...]


def build_experiment_menu_rows(
    manifest: dict[str, Any],
    evidence_by_path: dict[str, Any],
    stale_evidence_paths: Iterable[str] | None = None,
) -> list[ExperimentMenuRow]:
    stale_paths = set(stale_evidence_paths or ())
    rows: list[ExperimentMenuRow] = []
    for entry in manifest.get("experiments", []):
        evidence_path = entry["evidence_path"]
        evidence_packet = evidence_by_path.get(evidence_path)
        disabled_reasons = _pure_disabled_reasons(
            entry,
            evidence_packet,
            stale=evidence_path in stale_paths,
        )
        rows.append(
            ExperimentMenuRow(
                question_path=entry["question_path"],
                experiment_path=entry["experiment_path"],
                evidence_path=evidence_path,
                enabled=not disabled_reasons,
                disabled_reasons=disabled_reasons,
            )
        )
    return rows


def build_experiment_menu_groups(rows: list[ExperimentMenuRow]) -> list[ExperimentMenuGroup]:
    groups: list[ExperimentMenuGroup] = []
    current_question: str | None = None
    current_rows: list[ExperimentMenuRow] = []
    for row in rows:
        if row.question_path != current_question:
            if current_question is not None:
                groups.append(
                    ExperimentMenuGroup(
                        question_path=current_question,
                        rows=tuple(current_rows),
                    )
                )
            current_question = row.question_path
            current_rows = []
        current_rows.append(row)
    if current_question is not None:
        groups.append(
            ExperimentMenuGroup(question_path=current_question, rows=tuple(current_rows))
        )
    return groups


def load_experiment_menu_rows(repo: Path, config: dict[str, Any]) -> list[ExperimentMenuRow]:
    repo = Path(repo).resolve()
    manifest = load_manifest(repo, config)
    evidence_by_path: dict[str, Any] = {}
    evidence_errors: dict[str, str] = {}
    stale_evidence_paths: set[str] = set()

    for entry in manifest["experiments"]:
        evidence_path = entry["evidence_path"]
        packet_or_error = _load_menu_evidence_packet(repo, evidence_path)
        if isinstance(packet_or_error, str):
            evidence_errors[evidence_path] = packet_or_error
            continue
        evidence_by_path[evidence_path] = packet_or_error

        preflight = preflight_experiment(repo, entry["experiment_path"])
        if not preflight.runnable:
            for diagnostic_code in preflight.diagnostic_codes:
                if diagnostic_code == "stale_evidence":
                    stale_evidence_paths.add(evidence_path)
                elif diagnostic_code in {"missing_evidence", "malformed_evidence"}:
                    evidence_errors[evidence_path] = diagnostic_code

    rows = build_experiment_menu_rows(manifest, evidence_by_path, stale_evidence_paths)
    by_evidence_path = {row.evidence_path: row for row in rows}
    final_rows: list[ExperimentMenuRow] = []
    for entry in manifest["experiments"]:
        row = by_evidence_path[entry["evidence_path"]]
        reasons = list(row.disabled_reasons)
        evidence_error = evidence_errors.get(row.evidence_path)
        if evidence_error is not None:
            reasons = [evidence_error]
        else:
            preflight = preflight_experiment(repo, row.experiment_path)
            if not preflight.runnable:
                reasons = list(preflight.diagnostic_codes)
        final_rows.append(_row_with_reasons(row, reasons))
    return final_rows


def run_checkbox_menu(
    rows: list[ExperimentMenuRow],
    input_keys: Iterable[str] | None = None,
    console: TextIO | None = None,
) -> list[str]:
    if not rows:
        return []

    selected: set[str] = set()
    current = _first_enabled_index(rows)
    keys = iter(input_keys) if input_keys is not None else None
    output = console if console is not None else sys.stdout

    while True:
        _render_menu(rows, selected, current, output)
        key = _read_key(keys)
        if key in {"escape", "q"}:
            raise ExperimentMenuError("experiment menu cancelled")
        if key in {"enter", "\n", "\r"}:
            selected_paths = [
                row.experiment_path
                for row in rows
                if row.enabled and row.experiment_path in selected
            ]
            if not selected_paths:
                raise ExperimentMenuError("no experiments selected")
            return selected_paths
        if key in {" ", "space"} and rows[current].enabled:
            experiment_path = rows[current].experiment_path
            if experiment_path in selected:
                selected.remove(experiment_path)
            else:
                selected.add(experiment_path)
            continue
        if key == "down":
            current = _move(rows, current, 1)
            continue
        if key == "up":
            current = _move(rows, current, -1)


def choose_experiments_interactively(repo: Path, config: dict[str, Any]) -> list[str]:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ExperimentMenuError("--experiments-menu requires an interactive terminal")
    rows = load_experiment_menu_rows(repo, config)
    return run_checkbox_menu(rows)


def _pure_disabled_reasons(
    manifest_entry: dict[str, Any],
    evidence_packet: Any,
    *,
    stale: bool,
) -> tuple[str, ...]:
    if evidence_packet is None:
        return ("missing_evidence",)
    if not isinstance(evidence_packet, dict):
        return ("malformed_evidence",)
    if stale:
        return ("stale_evidence",)
    disposition = evidence_packet.get("preanalysis_disposition")
    if disposition != "analysis_candidate":
        return (str(disposition or "non_candidate_experiment"),)
    return ()


def _has_claimable_structured_evidence(evidence_packet: dict[str, Any]) -> bool:
    for collection_name in ("canonical_facts", "observed_values"):
        for item in evidence_packet.get(collection_name, []):
            source = item.get("source", {})
            if source.get("selector_type") == "json_pointer" and source.get("adapter") in {
                "json",
                "yaml",
            }:
                return True
    return False


def _load_menu_evidence_packet(repo: Path, evidence_path: str) -> dict[str, Any] | str:
    try:
        with (repo / evidence_path).open(encoding="utf-8") as handle:
            packet = json.load(handle)
    except FileNotFoundError:
        return "missing_evidence"
    except (OSError, json.JSONDecodeError):
        return "malformed_evidence"
    try:
        validate_artifact("evidence-packet.schema.json", packet)
    except ValidationError:
        return "malformed_evidence"
    return packet


def _row_with_reasons(row: ExperimentMenuRow, reasons: list[str]) -> ExperimentMenuRow:
    unique_reasons = tuple(dict.fromkeys(reasons))
    return ExperimentMenuRow(
        question_path=row.question_path,
        experiment_path=row.experiment_path,
        evidence_path=row.evidence_path,
        enabled=not unique_reasons,
        disabled_reasons=unique_reasons,
    )


def _first_enabled_index(rows: list[ExperimentMenuRow]) -> int:
    for index, row in enumerate(rows):
        if row.enabled:
            return index
    return 0


def _move(rows: list[ExperimentMenuRow], current: int, step: int) -> int:
    if not rows:
        return current
    return (current + step) % len(rows)


def _read_key(keys: Iterable[str] | None) -> str:
    if keys is not None:
        try:
            return next(keys)  # type: ignore[arg-type]
        except StopIteration as exc:
            raise ExperimentMenuError("experiment menu input ended") from exc
    return _read_tty_key()


def _read_tty_key() -> str:
    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        char = sys.stdin.read(1)
        if char == "\x1b":
            if not select.select([sys.stdin], [], [], 0)[0]:
                return "escape"
            suffix = sys.stdin.read(2)
            if suffix == "[A":
                return "up"
            if suffix == "[B":
                return "down"
            return "escape"
        if char in {"\n", "\r"}:
            return "enter"
        return char
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _render_menu(
    rows: list[ExperimentMenuRow],
    selected: set[str],
    current: int,
    console: TextIO,
) -> None:
    if console is None:
        return
    console.write("\r")
    for index, row in enumerate(rows):
        cursor = ">" if index == current else " "
        checked = "x" if row.experiment_path in selected else " "
        marker = "[ ]" if row.enabled else "[-]"
        if row.enabled:
            marker = f"[{checked}]"
        suffix = (
            f" ({', '.join(row.disabled_reasons)})" if row.disabled_reasons else ""
        )
        console.write(f"{cursor} {marker} {row.experiment_path}{suffix}\n")
    console.flush()
