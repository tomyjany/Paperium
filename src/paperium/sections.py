from __future__ import annotations

import re
from hashlib import sha256
from pathlib import Path

from paperium.paths import PaperiumPaths
from paperium.state import PaperiumState, SectionState

_SECTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SectionError(Exception):
    pass


def find_section(state: PaperiumState, section_id: str) -> SectionState:
    for section in state.sections:
        if section.id == section_id:
            return section
    raise SectionError(f"unknown section: {section_id}")


def add_section(
    repo: Path,
    state: PaperiumState,
    section_id: str,
    *,
    title: str,
    order: int | None = None,
    break_before: bool = False,
) -> SectionState:
    if not _SECTION_ID_PATTERN.match(section_id):
        raise SectionError(f"invalid section id: {section_id!r}")
    if any(section.id == section_id for section in state.sections):
        raise SectionError(f"duplicate section id: {section_id}")

    paths = PaperiumPaths(repo)
    draft_path = paths.section_path(section_id)
    facts_path = paths.section_facts_path(section_id)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    if not draft_path.exists():
        draft_path.write_text("", encoding="utf-8")
    if not facts_path.exists():
        facts_path.write_text(
            f"# Facts: {title}\n\nPurpose:\n\nFacts you may use:\n\nGuardrails:\n",
            encoding="utf-8",
        )

    if order is None:
        order = max((section.order for section in state.sections), default=0) + 1
    section = SectionState(
        id=section_id,
        title=title,
        path=draft_path.relative_to(repo).as_posix(),
        facts_path=facts_path.relative_to(repo).as_posix(),
        order=order,
        break_before=break_before,
    )
    state.sections.append(section)
    mark_report_stale(state)
    return section


def drop_section(state: PaperiumState, section_id: str) -> SectionState:
    section = find_section(state, section_id)
    section.status = "dropped"
    mark_report_stale(state)
    return section


def approve_section_v2(state: PaperiumState, section_id: str) -> SectionState:
    section = find_section(state, section_id)
    if section.revision_rounds < 1:
        raise SectionError(f"section has no recorded draft: {section_id}")
    section.status = "approved"
    mark_report_stale(state)
    return section


def record_section(
    repo: Path,
    state: PaperiumState,
    section_id: str,
    *,
    approve: bool = False,
) -> SectionState:
    section = find_section(state, section_id)
    draft_path = repo / section.path
    if not draft_path.exists() or not draft_path.read_text(encoding="utf-8").strip():
        raise SectionError(f"section draft is missing or empty: {section.path}")
    section.revision_rounds += 1
    section.status = "draft" if section.revision_rounds == 1 else "revised"
    section.draft_hash = sha256(draft_path.read_bytes()).hexdigest()
    section.last_run_failed = None
    if approve:
        section.status = "approved"
    mark_report_stale(state)
    return section


def mark_report_stale(state: PaperiumState) -> None:
    if state.report.assembled_at is not None:
        state.report.stale = True
