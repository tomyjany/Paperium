from __future__ import annotations

import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path

from paperium.paths import PaperiumPaths
from paperium.state import PaperiumState, SectionState, WorkerRecord
from paperium.worker_runner import run_worker
from paperium.workers import WorkerSpec, build_worker_record, worker_id_for
from paperium.writer_prompts import build_writer_prompt

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


WRITE_TIMEOUT_SECONDS = 1800


def prepare_prompt(repo: Path, state: PaperiumState, section_id: str) -> tuple[Path, str]:
    section = find_section(state, section_id)
    paths = PaperiumPaths(repo)
    facts = _read_optional(repo / section.facts_path)
    style = _read_optional(paths.style_path)
    draft = _read_optional(repo / section.path)
    worker_id = worker_id_for("write", section.path)
    prompt = build_writer_prompt(
        title=section.title,
        facts=facts,
        style=style,
        output_path=f".paperium/workers/{worker_id}/output.md",
        draft=draft,
    )
    archive = paths.section_prompt_path(section_id, section.revision_rounds + 1)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(prompt, encoding="utf-8")
    return archive, prompt


def run_section(
    repo: Path,
    state: PaperiumState,
    section_id: str,
    *,
    backend: str = "claude",
    timeout_seconds: int = WRITE_TIMEOUT_SECONDS,
    runner=run_worker,
) -> SectionState:
    section = find_section(state, section_id)
    _, prompt = prepare_prompt(repo, state, section_id)
    worker_id = worker_id_for("write", section.path)
    worker_dir = f".paperium/workers/{worker_id}"
    spec = WorkerSpec(
        worker_id=worker_id,
        backend=backend,
        role="write",
        readable_paths=[],
        writable_paths=[worker_dir],
        prompt=prompt,
        timeout_seconds=timeout_seconds,
    )
    record = build_worker_record(spec)
    result = runner(repo, spec)
    for name in (
        "status",
        "started_at",
        "ended_at",
        "stdout_path",
        "stderr_path",
        "output_path",
        "result_json_path",
        "failure_reason",
    ):
        record[name] = getattr(result, name)
    state.workers.append(WorkerRecord.from_dict(record))

    if result.status != "succeeded":
        section.last_run_failed = result.failure_reason or result.status
        return section

    output_path = repo / result.output_path
    if not output_path.exists() or not output_path.read_text(encoding="utf-8").strip():
        section.last_run_failed = "missing_output"
        return section

    _promote_draft(output_path, repo / section.path)
    return record_section(repo, state, section_id)


def _promote_draft(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=destination.parent,
        encoding="utf-8",
        prefix=f".{destination.name}.",
        suffix=".tmp",
    ) as temp_file:
        temp_file.write(source.read_text(encoding="utf-8"))
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_path = Path(temp_file.name)
    os.replace(temp_path, destination)


def _read_optional(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")
