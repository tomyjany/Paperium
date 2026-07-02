from hashlib import sha256

from paperium.reconcile import reconcile_state
from paperium.state import PaperiumState, SectionState


def _repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".paperium/sections").mkdir(parents=True)
    return repo


def _section(section_id, draft_hash=None, rounds=1):
    return SectionState(
        id=section_id,
        title=section_id,
        path=f".paperium/sections/{section_id}.md",
        facts_path=f".paperium/sections/{section_id}.facts.md",
        revision_rounds=rounds,
        draft_hash=draft_hash,
        order=1,
    )


def test_clean_state_reports_nothing(tmp_path):
    repo = _repo(tmp_path)
    draft = repo / ".paperium/sections/s1.md"
    draft.write_text("body")
    state = PaperiumState(phase="writing")
    state.sections.append(_section("s1", draft_hash=sha256(b"body").hexdigest()))
    assert reconcile_state(repo, state) == []


def test_file_without_record_is_reported_and_fixable(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".paperium/sections/orphan.md").write_text("text")
    (repo / ".paperium/sections/orphan.facts.md").write_text("facts are ignored")
    state = PaperiumState(phase="writing")
    drift = reconcile_state(repo, state)
    assert drift == ["section file without record: .paperium/sections/orphan.md"]
    reconcile_state(repo, state, fix=True)
    assert state.sections[0].id == "orphan"
    assert state.sections[0].revision_rounds == 1
    assert state.sections[0].draft_hash == sha256(b"text").hexdigest()
    assert reconcile_state(repo, state) == []


def test_record_without_file_is_reported_never_deleted(tmp_path):
    repo = _repo(tmp_path)
    state = PaperiumState(phase="writing")
    state.sections.append(_section("gone"))
    drift = reconcile_state(repo, state, fix=True)
    assert drift == ["section record without file: gone"]
    assert len(state.sections) == 1


def test_hash_drift_is_reported_and_fixable(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".paperium/sections/s1.md").write_text("edited by hand")
    state = PaperiumState(phase="writing")
    state.report.assembled_at = "2026-07-02T00:00:00+00:00"
    state.sections.append(_section("s1", draft_hash=sha256(b"old").hexdigest()))
    drift = reconcile_state(repo, state)
    assert drift == ["section draft changed since last recorded round: s1"]
    reconcile_state(repo, state, fix=True)
    section = state.sections[0]
    assert section.draft_hash == sha256(b"edited by hand").hexdigest()
    assert section.revision_rounds == 2
    assert state.report.stale is True
    assert reconcile_state(repo, state) == []


def test_empty_stub_draft_is_not_drift(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".paperium/sections/s1.md").write_text("")
    state = PaperiumState(phase="writing")
    state.sections.append(_section("s1", draft_hash=None, rounds=0))
    assert reconcile_state(repo, state) == []


def test_manually_written_draft_without_recorded_round_is_drift_and_fixable(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".paperium/sections/s1.md").write_text("hand written content")
    state = PaperiumState(phase="writing")
    state.sections.append(_section("s1", draft_hash=None, rounds=0))
    drift = reconcile_state(repo, state)
    assert drift == ["section draft exists but no round recorded: s1"]
    reconcile_state(repo, state, fix=True)
    section = state.sections[0]
    assert section.draft_hash == sha256(b"hand written content").hexdigest()
    assert section.revision_rounds == 1
    assert section.status == "draft"
    assert reconcile_state(repo, state) == []
