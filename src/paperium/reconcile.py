from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from paperium.paths import PaperiumPaths
from paperium.sections import mark_report_stale
from paperium.state import PaperiumState, SectionState


def reconcile_state(repo: Path, state: PaperiumState, *, fix: bool = False) -> list[str]:
    paths = PaperiumPaths(repo)
    sections_dir = paths.root_dir / "sections"
    drift: list[str] = []

    known_paths = {section.path for section in state.sections}
    draft_files = (
        sorted(path for path in sections_dir.glob("*.md") if not path.name.endswith(".facts.md"))
        if sections_dir.exists()
        else []
    )

    for draft in draft_files:
        relative = draft.relative_to(repo).as_posix()
        if relative in known_paths:
            continue
        drift.append(f"section file without record: {relative}")
        if fix:
            section_id = draft.stem
            order = max((section.order for section in state.sections), default=0) + 1
            state.sections.append(
                SectionState(
                    id=section_id,
                    title=section_id,
                    path=relative,
                    facts_path=paths.section_facts_path(section_id).relative_to(repo).as_posix(),
                    status="draft",
                    revision_rounds=1,
                    order=order,
                    draft_hash=sha256(draft.read_bytes()).hexdigest(),
                )
            )

    for section in state.sections:
        draft = repo / section.path
        if not draft.exists():
            drift.append(f"section record without file: {section.id}")
            continue
        if section.draft_hash is None:
            continue
        current = sha256(draft.read_bytes()).hexdigest()
        if current != section.draft_hash:
            drift.append(f"section draft changed since last recorded round: {section.id}")
            if fix:
                section.draft_hash = current
                section.revision_rounds += 1
                if section.status in {"draft", "revised", "approved"}:
                    section.status = "revised" if section.revision_rounds > 1 else "draft"
                mark_report_stale(state)

    return drift
