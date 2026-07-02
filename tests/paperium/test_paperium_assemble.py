from hashlib import sha256

import pytest

from paperium.assemble import AssembleError, assemble_report
from paperium.state import PaperiumState, SectionState


def _repo_with_sections(tmp_path, statuses=("approved", "approved")):
    repo = tmp_path / "repo"
    sections_dir = repo / ".paperium/sections"
    sections_dir.mkdir(parents=True)
    (repo / ".paperium/report-template.md").write_text("<style>x</style>\n\n{{sections}}\n")
    state = PaperiumState(phase="writing")
    for index, status in enumerate(statuses, start=1):
        (sections_dir / f"s{index}.md").write_text(f"## Section {index}\nbody {index}\n")
        state.sections.append(
            SectionState(
                id=f"s{index}",
                title=f"Section {index}",
                path=f".paperium/sections/s{index}.md",
                facts_path=f".paperium/sections/s{index}.facts.md",
                status=status,
                revision_rounds=1,
                order=index,
                break_before=index == 2,
            )
        )
    return repo, state


def test_assemble_writes_report_and_updates_state(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    target = assemble_report(repo, state)
    text = target.read_text()
    assert target == repo / ".paperium/REPORT.md"
    assert text.index("Section 1") < text.index("Section 2")
    assert '<div class="page-break"></div>' in text
    assert text.index("Section 1") < text.index("page-break") < text.index("Section 2")
    assert "<style>x</style>" in text
    assert state.report.assembled_at is not None
    assert state.report.content_hash == sha256(text.encode()).hexdigest()
    assert state.report.stale is False


def test_assemble_is_deterministic(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    first = assemble_report(repo, state).read_text()
    second = assemble_report(repo, state).read_text()
    assert first == second


def test_assemble_refuses_unapproved_sections(tmp_path):
    repo, state = _repo_with_sections(tmp_path, statuses=("approved", "draft"))
    with pytest.raises(AssembleError, match="s2"):
        assemble_report(repo, state)


def test_allow_draft_writes_draft_path_only(tmp_path):
    repo, state = _repo_with_sections(tmp_path, statuses=("approved", "draft"))
    target = assemble_report(repo, state, allow_draft=True)
    assert target == repo / ".paperium/REPORT.draft.md"
    assert not (repo / ".paperium/REPORT.md").exists()
    assert state.report.assembled_at is None
    assert state.report.content_hash is None


def test_dropped_sections_are_excluded(tmp_path):
    repo, state = _repo_with_sections(tmp_path, statuses=("approved", "dropped"))
    text = assemble_report(repo, state).read_text()
    assert "Section 2" not in text


def test_missing_images_fail_with_listing(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    (repo / ".paperium/sections/s1.md").write_text(
        '![diagram](.paperium/images/missing-a.png)\n<img src=".paperium/images/missing-b.png">\n'
    )
    with pytest.raises(AssembleError) as excinfo:
        assemble_report(repo, state)
    assert "missing-a.png" in str(excinfo.value)
    assert "missing-b.png" in str(excinfo.value)


def test_existing_images_pass(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    images = repo / ".paperium/images"
    images.mkdir(parents=True)
    (images / "ok.png").write_bytes(b"png")
    (repo / ".paperium/sections/s1.md").write_text("![ok](.paperium/images/ok.png)\n")
    assemble_report(repo, state)


def test_hand_edit_requires_force(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    assemble_report(repo, state)
    report = repo / ".paperium/REPORT.md"
    report.write_text(report.read_text() + "\nhand edit\n")
    with pytest.raises(AssembleError, match="hand-edited"):
        assemble_report(repo, state)
    assemble_report(repo, state, force=True)
    assert "hand edit" not in report.read_text()


def test_preexisting_report_without_content_hash_requires_force(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    report = repo / ".paperium/REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("hand built report\n")
    assert state.report.content_hash is None
    with pytest.raises(AssembleError, match="paperium"):
        assemble_report(repo, state)
    assert report.read_text() == "hand built report\n"
    assemble_report(repo, state, force=True)
    assert "hand built report" not in report.read_text()


def test_report_path_traversal_is_rejected(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    state.report.path = "/etc/passwd"
    with pytest.raises(AssembleError):
        assemble_report(repo, state)


def test_section_path_traversal_is_rejected(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    state.sections[0].path = "../escape.md"
    with pytest.raises(AssembleError):
        assemble_report(repo, state)


def test_markdown_image_with_title_is_validated(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    (repo / ".paperium/sections/s1.md").write_text(
        '![diagram](.paperium/images/missing.png "a title")\n'
    )
    with pytest.raises(AssembleError) as excinfo:
        assemble_report(repo, state)
    assert "missing.png" in str(excinfo.value)


def test_single_quoted_html_image_is_validated(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    (repo / ".paperium/sections/s1.md").write_text("<img src='.paperium/images/missing.png'>\n")
    with pytest.raises(AssembleError) as excinfo:
        assemble_report(repo, state)
    assert "missing.png" in str(excinfo.value)


def test_image_ref_escaping_repo_is_rejected_even_if_file_exists(tmp_path):
    repo, state = _repo_with_sections(tmp_path)
    outside = repo.parent / "outside.png"
    outside.write_bytes(b"png")
    (repo / ".paperium/sections/s1.md").write_text("![x](../outside.png)\n")
    with pytest.raises(AssembleError) as excinfo:
        assemble_report(repo, state)
    assert "outside.png" in str(excinfo.value)
