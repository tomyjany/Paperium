from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import copy_fixture_repo
from paperctl.analysis_menu import (
    ExperimentMenuError,
    ExperimentMenuRow,
    build_experiment_menu_groups,
    build_experiment_menu_rows,
    load_experiment_menu_rows,
    run_checkbox_menu,
)
from paperctl.config import load_config


COMPLETED_EXPERIMENT = "questions/q001-throughput/experiments/exp001-completed"
INCOMPLETE_EXPERIMENT = "questions/q001-throughput/experiments/exp002-incomplete"
CONFLICT_EXPERIMENT = "questions/q001-throughput/experiments/exp003-structured-conflict"
UNSUPPORTED_EXPERIMENT = (
    "questions/q001-throughput/experiments/exp005-unsupported-and-previews"
)


def _manifest(entries: list[dict]) -> dict:
    return {"schema_version": 1, "artifact_type": "manifest", "experiments": entries}


def _entry(question_path: str, experiment_path: str) -> dict:
    suffix = experiment_path.removeprefix("questions/")
    return {
        "question_ref": question_path.rsplit("/", 1)[-1],
        "question_path": question_path,
        "question_readme_path": f"{question_path}/README.md",
        "question_readme_sha256": "sha256:" + "0" * 64,
        "experiment_ref": experiment_path.rsplit("/", 1)[-1],
        "experiment_path": experiment_path,
        "inventory_path": f"paper/work/inventories/{suffix}.json",
        "evidence_path": f"paper/work/evidence/{suffix}.json",
    }


def _candidate_packet(entry: dict, *, facts: bool = True) -> dict:
    source = {
        "path": f"{entry['experiment_path']}/outputs/result.json",
        "source_hash": "sha256:" + "1" * 64,
        "selector_type": "json_pointer",
        "selector": "/value",
        "adapter": "json",
        "adapter_version": "1",
    }
    return {
        "schema_version": 1,
        "artifact_type": "evidence_packet",
        "question_path": entry["question_path"],
        "experiment_path": entry["experiment_path"],
        "inventory_path": entry["inventory_path"],
        "fingerprint": {},
        "preanalysis_disposition": "analysis_candidate",
        "execution_status": "completed",
        "evidence_status": "available",
        "reason_codes": [],
        "counts": {},
        "canonical_facts": (
            [
                {
                    "fact_id": "value",
                    "value": 1,
                    "value_type": "integer",
                    "unit": None,
                    "source": source,
                }
            ]
            if facts
            else []
        ),
        "observed_values": [],
        "previews": [],
        "diagnostics": [],
        "conflicts": [],
        "unsupported_artifacts": [],
        "warnings": [],
    }


def _run_prerequisites(repo: Path) -> None:
    for command in ("discover", "inventory", "normalize"):
        result = subprocess.run(
            [sys.executable, "-m", "paperctl", "--repo", str(repo), command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, result.stderr


def test_build_rows_preserves_manifest_order_and_disables_missing_evidence():
    first = _entry("questions/q001", "questions/q001/experiments/exp001")
    second = _entry("questions/q001", "questions/q001/experiments/exp002")
    manifest = _manifest([first, second])

    rows = build_experiment_menu_rows(
        manifest,
        {first["evidence_path"]: _candidate_packet(first)},
    )

    assert rows == [
        ExperimentMenuRow(
            question_path="questions/q001",
            experiment_path="questions/q001/experiments/exp001",
            evidence_path=first["evidence_path"],
            enabled=True,
            disabled_reasons=(),
        ),
        ExperimentMenuRow(
            question_path="questions/q001",
            experiment_path="questions/q001/experiments/exp002",
            evidence_path=second["evidence_path"],
            enabled=False,
            disabled_reasons=("missing_evidence",),
        ),
    ]


def test_build_rows_disables_blocked_stale_and_unclaimable_evidence():
    blocked = _entry("questions/q001", "questions/q001/experiments/blocked")
    stale = _entry("questions/q001", "questions/q001/experiments/stale")
    unclaimable = _entry("questions/q001", "questions/q001/experiments/unclaimable")
    blocked_packet = _candidate_packet(blocked)
    blocked_packet["preanalysis_disposition"] = "blocked"

    rows = build_experiment_menu_rows(
        _manifest([blocked, stale, unclaimable]),
        {
            blocked["evidence_path"]: blocked_packet,
            stale["evidence_path"]: _candidate_packet(stale),
            unclaimable["evidence_path"]: _candidate_packet(unclaimable, facts=False),
        },
        stale_evidence_paths={stale["evidence_path"]},
    )

    assert [(row.experiment_path, row.enabled, row.disabled_reasons) for row in rows] == [
        (blocked["experiment_path"], False, ("blocked_experiment",)),
        (stale["experiment_path"], False, ("stale_evidence",)),
        (unclaimable["experiment_path"], False, ("no_claimable_structured_evidence",)),
    ]


def test_build_groups_preserves_first_seen_question_order():
    rows = [
        ExperimentMenuRow("questions/q002", "questions/q002/experiments/a", "a.json"),
        ExperimentMenuRow("questions/q001", "questions/q001/experiments/a", "b.json"),
        ExperimentMenuRow("questions/q002", "questions/q002/experiments/b", "c.json"),
    ]

    groups = build_experiment_menu_groups(rows)

    assert [group.question_path for group in groups] == ["questions/q002", "questions/q001"]
    assert [row.experiment_path for row in groups[0].rows] == [
        "questions/q002/experiments/a",
        "questions/q002/experiments/b",
    ]


def test_checkbox_menu_toggles_enabled_rows_only_and_returns_selected_paths():
    rows = [
        ExperimentMenuRow("questions/q001", "enabled-a", "a.json"),
        ExperimentMenuRow(
            "questions/q001",
            "disabled",
            "b.json",
            enabled=False,
            disabled_reasons=("blocked_experiment",),
        ),
        ExperimentMenuRow("questions/q001", "enabled-b", "c.json"),
    ]

    selected = run_checkbox_menu(rows, input_keys=[" ", "down", " ", "down", " ", "enter"])

    assert selected == ["enabled-a", "enabled-b"]


@pytest.mark.parametrize("key", ["q", "escape"])
def test_checkbox_menu_cancel_raises_menu_error(key):
    rows = [ExperimentMenuRow("questions/q001", "enabled", "a.json")]

    with pytest.raises(ExperimentMenuError, match="cancelled"):
        run_checkbox_menu(rows, input_keys=[key])


def test_real_loader_reports_missing_stale_and_non_candidate_rows(tmp_path):
    repo = copy_fixture_repo(tmp_path)
    _run_prerequisites(repo)
    config = load_config(repo)

    missing_path = repo / "paper/work/evidence" / f"{COMPLETED_EXPERIMENT}.json"
    missing_path.unlink()
    stale_source = repo / INCOMPLETE_EXPERIMENT / "outputs/status.json"
    stale_source.write_text('{"status": "completed"}\n', encoding="utf-8")

    rows = load_experiment_menu_rows(repo, config)
    by_path = {row.experiment_path: row for row in rows}

    assert by_path[COMPLETED_EXPERIMENT].enabled is False
    assert by_path[COMPLETED_EXPERIMENT].disabled_reasons == ("missing_evidence",)
    assert by_path[INCOMPLETE_EXPERIMENT].enabled is False
    assert "stale_inventory" in by_path[INCOMPLETE_EXPERIMENT].disabled_reasons
    assert by_path[CONFLICT_EXPERIMENT].enabled is False
    assert by_path[CONFLICT_EXPERIMENT].disabled_reasons == ("needs_human_review",)
    assert by_path[UNSUPPORTED_EXPERIMENT].enabled is False
    assert by_path[UNSUPPORTED_EXPERIMENT].disabled_reasons == (
        "no_claimable_structured_evidence",
    )
