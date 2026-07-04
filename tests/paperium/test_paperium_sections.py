import pytest

from paperium.sections import (
    SectionError,
    add_section,
    approve_section_v2,
    drop_section,
    find_section,
    prepare_prompt,
    record_section,
    run_section,
)
from paperium.state import PaperiumState
from paperium.workers import WorkerResult


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


def _prepared_repo(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".paperium/style.md").write_text("- style rule\n")
    state = PaperiumState(phase="writing")
    add_section(repo, state, "ch1-s1", title="Dataset")
    (repo / ".paperium/sections/ch1-s1.facts.md").write_text("- fact one\n")
    return repo, state


def _fake_result(worker_id, status, failure_reason=None):
    worker_dir = f".paperium/workers/{worker_id}"
    return WorkerResult(
        worker_id=worker_id,
        status=status,
        stdout_path=f"{worker_dir}/stdout.txt",
        stderr_path=f"{worker_dir}/stderr.txt",
        output_path=f"{worker_dir}/output.md",
        result_json_path=f"{worker_dir}/result.json",
        canonical_result_path=None,
        started_at="2026-07-02T00:00:00+00:00",
        ended_at="2026-07-02T00:01:00+00:00",
        failure_reason=failure_reason,
    )


def test_prepare_prompt_archives_round_file(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    archive, prompt = prepare_prompt(repo, state, "ch1-s1")
    assert archive == repo / ".paperium/prompts/ch1-s1.round1.prompt.md"
    assert archive.read_text() == prompt
    assert "- fact one" in prompt
    assert "- style rule" in prompt
    assert "You are writing one section" in prompt
    # re-emitting before any recorded round overwrites the same file
    archive_again, _ = prepare_prompt(repo, state, "ch1-s1")
    assert archive_again == archive


def test_prepare_prompt_switches_to_revision_when_draft_exists(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    draft = repo / ".paperium/sections/ch1-s1.md"
    draft.write_text("## Dataset\ntext /shorten this paragraph please/\n")
    record_section(repo, state, "ch1-s1")
    archive, prompt = prepare_prompt(repo, state, "ch1-s1")
    assert archive.name == "ch1-s1.round2.prompt.md"
    assert "You are revising one section" in prompt
    assert "1. shorten this paragraph please" in prompt


def test_run_section_promotes_output_and_records_round(tmp_path):
    repo, state = _prepared_repo(tmp_path)

    def fake_runner(run_repo, spec):
        worker_dir = run_repo / ".paperium/workers" / spec.worker_id
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "output.md").write_text("## Dataset\nwritten by worker\n")
        return _fake_result(spec.worker_id, "succeeded")

    section = run_section(repo, state, "ch1-s1", runner=fake_runner)
    assert section.revision_rounds == 1
    assert section.status == "draft"
    assert section.last_run_failed is None
    assert "written by worker" in (repo / ".paperium/sections/ch1-s1.md").read_text()
    assert state.workers[-1].role == "write"
    assert state.workers[-1].status == "succeeded"


def test_run_section_failure_preserves_previous_draft(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    draft = repo / ".paperium/sections/ch1-s1.md"
    draft.write_text("previous good draft")
    record_section(repo, state, "ch1-s1")

    def failing_runner(run_repo, spec):
        return _fake_result(spec.worker_id, "failed", failure_reason="nonzero_exit:2")

    section = run_section(repo, state, "ch1-s1", runner=failing_runner)
    assert section.last_run_failed == "nonzero_exit:2"
    assert section.revision_rounds == 1
    assert draft.read_text() == "previous good draft"


def test_run_section_missing_output_is_failure(tmp_path):
    repo, state = _prepared_repo(tmp_path)

    def empty_runner(run_repo, spec):
        return _fake_result(spec.worker_id, "succeeded")

    section = run_section(repo, state, "ch1-s1", runner=empty_runner)
    assert section.last_run_failed == "missing_output"
    assert section.revision_rounds == 0


def test_run_section_does_not_promote_stale_worker_output(tmp_path):
    repo, state = _prepared_repo(tmp_path)

    def writing_runner(run_repo, spec):
        worker_dir = run_repo / ".paperium/workers" / spec.worker_id
        worker_dir.mkdir(parents=True, exist_ok=True)
        (worker_dir / "output.md").write_text("## Dataset\nround one\n")
        return _fake_result(spec.worker_id, "succeeded")

    section = run_section(repo, state, "ch1-s1", runner=writing_runner)
    assert section.revision_rounds == 1
    draft = repo / ".paperium/sections/ch1-s1.md"
    assert "round one" in draft.read_text()

    def silent_runner(run_repo, spec):
        # Same deterministic worker_id/dir as before; writes nothing this time.
        return _fake_result(spec.worker_id, "succeeded")

    section = run_section(repo, state, "ch1-s1", runner=silent_runner)
    assert section.last_run_failed == "missing_output"
    assert section.revision_rounds == 1
    assert "round one" in draft.read_text()


def test_prepare_prompt_rejects_escaping_section_path(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    state.sections[0].path = "../escape.md"
    with pytest.raises(SectionError):
        prepare_prompt(repo, state, "ch1-s1")


def test_prepare_prompt_rejects_absolute_facts_path(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    state.sections[0].facts_path = "/etc/passwd"
    with pytest.raises(SectionError):
        prepare_prompt(repo, state, "ch1-s1")


def test_record_section_rejects_escaping_path(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    state.sections[0].path = "../escape.md"
    with pytest.raises(SectionError):
        record_section(repo, state, "ch1-s1")


def test_record_section_approve_sets_status_approved(tmp_path):
    repo, state = _prepared_repo(tmp_path)
    draft = repo / ".paperium/sections/ch1-s1.md"
    draft.write_text("## Dataset\ntext\n")
    section = record_section(repo, state, "ch1-s1", approve=True)
    assert section.status == "approved"


def test_record_section_clears_previous_failure(tmp_path):
    repo, state = _prepared_repo(tmp_path)

    def failing_runner(run_repo, spec):
        return _fake_result(spec.worker_id, "failed", failure_reason="nonzero_exit:2")

    run_section(repo, state, "ch1-s1", runner=failing_runner)
    assert find_section(state, "ch1-s1").last_run_failed == "nonzero_exit:2"

    draft = repo / ".paperium/sections/ch1-s1.md"
    draft.write_text("## Dataset\ntext\n")
    section = record_section(repo, state, "ch1-s1")
    assert section.last_run_failed is None
