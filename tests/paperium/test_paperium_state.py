import json

import pytest

from paperium.state import (
    PaperiumState,
    SectionState,
    StateError,
    load_state,
    migrate_v1_to_v2,
    save_state,
)


def test_state_v2_round_trip(tmp_path):
    path = tmp_path / ".paperium/state.json"
    state = PaperiumState(
        phase="writing",
        sections=[
            SectionState(
                id="chapter1-section1-dataset",
                title="Dataset",
                path=".paperium/sections/chapter1-section1-dataset.md",
                facts_path=".paperium/sections/chapter1-section1-dataset.facts.md",
                order=1,
                break_before=True,
            )
        ],
    )
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.schema_version == 2
    section = loaded.sections[0]
    assert section.id == "chapter1-section1-dataset"
    assert section.status == "draft"
    assert section.revision_rounds == 0
    assert section.order == 1
    assert section.break_before is True
    assert section.draft_hash is None
    assert section.last_run_failed is None
    assert loaded.report.path == ".paperium/REPORT.md"
    assert loaded.report.assembled_at is None
    assert loaded.report.content_hash is None
    assert loaded.report.stale is False
    assert not hasattr(loaded, "expected_section_ids")
    assert not hasattr(loaded, "final_write")


def test_invalid_section_status_fails():
    with pytest.raises(StateError):
        SectionState(id="a", title="A", path="p", facts_path="f", status="skipped")


def test_invalid_phase_fails():
    with pytest.raises(StateError):
        PaperiumState(phase="reviewing")


def test_migrate_v1_to_v2_maps_phase_and_drops_dead_fields():
    v1 = {
        "schema_version": 1,
        "phase": "complete",
        "expected_section_ids": ["questions-q001"],
        "final_write": {"paper_path": "PAPER.md", "status": "written", "written_at": None},
        "sections": [{"id": "questions-q001", "title": "Q1", "path": "x.md"}],
        "selected_experiments": [],
        "workers": [],
        "context_requests": [],
    }
    v2 = migrate_v1_to_v2(v1)
    assert v2["schema_version"] == 2
    assert v2["phase"] == "writing"
    assert "expected_section_ids" not in v2
    assert "final_write" not in v2
    assert v2["sections"] == []
    assert v2["report"] == {}


def test_load_state_migrates_v1_with_one_time_backup(tmp_path):
    path = tmp_path / ".paperium/state.json"
    path.parent.mkdir(parents=True)
    v1 = {"schema_version": 1, "phase": "writing"}
    path.write_text(json.dumps(v1))
    state = load_state(path)
    assert state.schema_version == 2
    backup = tmp_path / ".paperium/state.v1.backup.json"
    assert json.loads(backup.read_text())["schema_version"] == 1
    # backup is written once; a second load must not overwrite it
    backup.write_text("sentinel")
    load_state(path)
    assert backup.read_text() == "sentinel"


def test_unknown_schema_version_fails(tmp_path):
    path = tmp_path / ".paperium/state.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version": 999}')
    with pytest.raises(StateError):
        load_state(path)
