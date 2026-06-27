import pytest

from paperium.state import (
    PaperiumState,
    SelectedExperiment,
    StateError,
    load_state,
    save_state,
)


def test_state_round_trip(tmp_path):
    path = tmp_path / ".paperium/state.json"
    state = PaperiumState(
        phase="selecting",
        selected_experiments=[
            SelectedExperiment(
                path="questions/q001/experiments/exp001",
                question_readme="questions/q001/README.md",
                analysis_path="questions/q001/experiments/exp001/.paperium/analysis.md",
                fact_check_result_path="questions/q001/experiments/exp001/.paperium/fact-check.json",
                disposition=None,
                status="pending",
                repair_attempts=0,
            )
        ],
    )
    save_state(path, state)
    loaded = load_state(path)
    assert loaded.schema_version == 1
    assert loaded.selected_experiments[0].path == "questions/q001/experiments/exp001"
    assert loaded.ranking.path == ".paperium/ranking.md"
    assert loaded.ranking.json_path == ".paperium/ranking.json"
    assert loaded.dispositions_path == ".paperium/dispositions.md"
    assert loaded.question_focus.path == ".paperium/question-focus.md"
    assert loaded.question_focus.json_path == ".paperium/question-focus.json"
    assert loaded.context_requests == []
    assert loaded.sections == []
    assert loaded.expected_section_ids == []
    assert loaded.final_write.paper_path == "PAPER.md"
    assert loaded.final_write.status == "not_started"


def test_save_state_creates_parent_directories(tmp_path):
    path = tmp_path / "repo/.paperium/state.json"
    save_state(path, PaperiumState())
    assert path.exists()


def test_invalid_schema_version_fails(tmp_path):
    path = tmp_path / ".paperium/state.json"
    path.parent.mkdir()
    path.write_text('{"schema_version": 999}\n')
    with pytest.raises(StateError):
        load_state(path)


def test_invalid_enum_value_fails(tmp_path):
    path = tmp_path / ".paperium/state.json"
    path.parent.mkdir()
    path.write_text('{"schema_version": 1, "phase": "nonsense"}\n')
    with pytest.raises(StateError):
        load_state(path)
