import pytest

from paperium.sections import (
    SectionError,
    add_section,
    approve_section_v2,
    drop_section,
    find_section,
    record_section,
)
from paperium.state import PaperiumState


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".paperium").mkdir(parents=True)
    return repo


def test_add_section_creates_stub_files_and_defaults_order(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    first = add_section(repo, state, "ch1-s1", title="Dataset")
    second = add_section(repo, state, "ch2-s1", title="CPU", break_before=True)
    assert first.order == 1 and second.order == 2
    assert second.break_before is True
    assert (repo / ".paperium/sections/ch1-s1.md").exists()
    assert (repo / ".paperium/sections/ch1-s1.facts.md").exists()
    assert first.path == ".paperium/sections/ch1-s1.md"
    assert first.facts_path == ".paperium/sections/ch1-s1.facts.md"


def test_add_section_rejects_duplicate_and_unsafe_ids(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    add_section(repo, state, "ch1-s1", title="Dataset")
    with pytest.raises(SectionError):
        add_section(repo, state, "ch1-s1", title="Again")
    for bad in ["../escape", "a/b", "", "UPPER CASE"]:
        with pytest.raises(SectionError):
            add_section(repo, state, bad, title="Bad")


def test_record_requires_non_empty_draft(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    add_section(repo, state, "ch1-s1", title="Dataset")
    with pytest.raises(SectionError):
        record_section(repo, state, "ch1-s1")


def test_record_bumps_rounds_sets_status_and_hash(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    add_section(repo, state, "ch1-s1", title="Dataset")
    draft = repo / ".paperium/sections/ch1-s1.md"
    draft.write_text("## Dataset\ntext\n")
    section = record_section(repo, state, "ch1-s1")
    assert section.revision_rounds == 1
    assert section.status == "draft"
    assert section.draft_hash is not None
    draft.write_text("## Dataset\nrevised\n")
    section = record_section(repo, state, "ch1-s1")
    assert section.revision_rounds == 2
    assert section.status == "revised"


def test_approve_requires_a_recorded_round(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    add_section(repo, state, "ch1-s1", title="Dataset")
    with pytest.raises(SectionError):
        approve_section_v2(state, "ch1-s1")
    (repo / ".paperium/sections/ch1-s1.md").write_text("text")
    record_section(repo, state, "ch1-s1")
    approve_section_v2(state, "ch1-s1")
    assert find_section(state, "ch1-s1").status == "approved"


def test_drop_and_unknown_section(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    add_section(repo, state, "ch1-s1", title="Dataset")
    drop_section(state, "ch1-s1")
    assert find_section(state, "ch1-s1").status == "dropped"
    with pytest.raises(SectionError):
        find_section(state, "missing")


def test_mutations_mark_assembled_report_stale(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    state.report.assembled_at = "2026-07-02T00:00:00+00:00"
    add_section(repo, state, "ch1-s1", title="Dataset")
    (repo / ".paperium/sections/ch1-s1.md").write_text("text")
    record_section(repo, state, "ch1-s1")
    assert state.report.stale is True
