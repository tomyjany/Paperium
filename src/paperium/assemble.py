from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

from paperium.paths import PaperiumPaths
from paperium.sections import safe_state_path
from paperium.state import PaperiumState

PAGE_BREAK = '<div class="page-break"></div>'
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)(?:\s+[^)]*)?\)")
_HTML_IMAGE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']")


class AssembleError(Exception):
    pass


def assemble_report(
    repo: Path,
    state: PaperiumState,
    *,
    allow_draft: bool = False,
    force: bool = False,
) -> Path:
    paths = PaperiumPaths(repo)
    sections = sorted(
        (section for section in state.sections if section.status != "dropped"),
        key=lambda section: (section.order, section.id),
    )
    if not sections:
        raise AssembleError("no sections to assemble")
    unapproved = [section.id for section in sections if section.status != "approved"]
    if unapproved and not allow_draft:
        raise AssembleError(f"sections are not approved: {', '.join(unapproved)}")

    template_path = paths.report_template_path
    if not template_path.exists():
        raise AssembleError(f"report template missing: {template_path}")
    template = template_path.read_text(encoding="utf-8")
    if "{{sections}}" not in template:
        raise AssembleError("report template is missing the {{sections}} placeholder")

    bodies: list[str] = []
    missing_images: list[str] = []
    for index, section in enumerate(sections):
        section_path = safe_state_path(repo, section.path, "section path", exc_cls=AssembleError)
        body = section_path.read_text(encoding="utf-8").rstrip()
        missing_images.extend(_missing_images(repo, body))
        if section.break_before and index > 0:
            bodies.append(PAGE_BREAK)
        bodies.append(body)
    if missing_images:
        raise AssembleError(f"missing images: {', '.join(sorted(set(missing_images)))}")

    text = template.replace("{{sections}}", "\n\n".join(bodies) + "\n")

    if allow_draft:
        target = paths.report_draft_path
    else:
        target = safe_state_path(repo, state.report.path, "report path", exc_cls=AssembleError)
        if target.exists() and not force:
            if state.report.content_hash is None:
                raise AssembleError(
                    f"{state.report.path} exists but was not assembled by paperium; "
                    "use --force to overwrite"
                )
            if sha256(target.read_bytes()).hexdigest() != state.report.content_hash:
                raise AssembleError(
                    f"{state.report.path} looks hand-edited; use --force to overwrite"
                )

    _atomic_write(target, text)
    if not allow_draft:
        state.report.assembled_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        state.report.content_hash = sha256(text.encode("utf-8")).hexdigest()
        state.report.stale = False
    return target


def _missing_images(repo: Path, body: str) -> list[str]:
    references = _MD_IMAGE.findall(body) + _HTML_IMAGE.findall(body)
    missing = []
    for reference in references:
        if reference.startswith(("http://", "https://", "data:")):
            continue
        ref_path = PurePosixPath(reference)
        if ref_path.is_absolute() or ".." in ref_path.parts:
            missing.append(reference)
            continue
        if not (repo / reference).exists():
            missing.append(reference)
    return missing


def _atomic_write(destination: Path, text: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=destination.parent,
        encoding="utf-8",
        prefix=f".{destination.name}.",
        suffix=".tmp",
    ) as temp_file:
        temp_file.write(text)
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_path = Path(temp_file.name)
    os.replace(temp_path, destination)
