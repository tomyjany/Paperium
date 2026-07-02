# Paperium V2 Sections Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Paperium V1 writing phase with an ad-hoc sections workbench: dynamic section registry, inline-note revision loop, templated writer prompts, and `REPORT.md` assembly.

**Architecture:** State schema moves to v2 (sections registry + report state replace `expected_section_ids`/`final_write`, with auto-migration). New modules handle note extraction, writer prompt building, section lifecycle, assembly, and reconcile. The existing pipeline half (select/analyze/fact-check/rank/dispositions) and `worker_runner` are reused unchanged.

**Tech Stack:** Python 3.11, argparse, dataclasses, pathlib, subprocess (via existing `worker_runner`), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-02-paperium-v2-sections-workbench-design.md`

## Global Constraints

- All tests are LLM-free; worker execution is tested with monkeypatched `run_worker`.
- All state writes go through `paperium.state.save_state` (atomic).
- Section/report file writes must be atomic (temp file + `os.replace`).
- Repo-relative path safety: reuse `commands._safe_repo_relative` semantics — no absolute paths, no `..`, no backslashes.
- Existing test naming convention: `tests/paperium/test_paperium_<module>.py`.
- `--allow-draft` assembly writes only `.paperium/REPORT.draft.md`; it never touches `REPORT.md` or `report` state.
- Failed section runs must never clobber an existing draft.
- v1 state files auto-migrate to v2 with a one-time backup at `.paperium/state.v1.backup.json`.
- Run tests with `uv run pytest <path> -q`; lint with `uv run ruff check .` before each commit.

---

## File Structure

Create:
- `src/paperium/notes.py` — inline `/.../` note extraction
- `src/paperium/writer_prompts.py` — initial/revision writer prompt builders
- `src/paperium/templates.py` — `style.md` and `report-template.md` scaffold text
- `src/paperium/sections.py` — section registry operations + section run orchestration
- `src/paperium/assemble.py` — report assembly and image validation
- `src/paperium/reconcile.py` — state/disk drift detection

Modify:
- `src/paperium/state.py` — schema v2, migration, new `SectionState`/`ReportState`
- `src/paperium/paths.py` — new path helpers
- `src/paperium/cli.py` — new `section` subcommands, `assemble`, `reconcile`; remove `write`
- `src/paperium/commands.py` — remove V1 writing functions; stop touching removed state fields
- `src/paperium/output.py` — section table in status output
- `skills/paperium-write-paper/SKILL.md`, `skills/paperium-writer/SKILL.md` — new workflow

Delete:
- `src/paperium/writing.py`, `tests/paperium/test_paperium_writing.py`

Tests:
- `tests/paperium/test_paperium_state.py` (extend), `test_paperium_paths.py` (extend), `test_paperium_notes.py`, `test_paperium_writer_prompts.py`, `test_paperium_sections.py`, `test_paperium_assemble.py`, `test_paperium_reconcile.py`, `test_paperium_cli.py` (extend)

---

### Task 1: State Schema v2 With Migration

**Files:**
- Modify: `src/paperium/state.py`
- Test: `tests/paperium/test_paperium_state.py`

**Interfaces:**
- Produces: `SectionState(id, title, path, facts_path, status="draft", revision_rounds=0, order=0, break_before=False, draft_hash=None, last_run_failed=None)`; `ReportState(path=".paperium/REPORT.md", assembled_at=None, content_hash=None, stale=False)`; `PaperiumState.report`, `PaperiumState.sections`; `SCHEMA_VERSION = 2`; `SECTION_STATUSES = {"draft", "revised", "approved", "dropped"}`; `PHASES = {"selecting", "analyzing", "fact_checking", "ranking", "mapping", "writing", "failed"}`; `migrate_v1_to_v2(data: dict) -> dict`; `load_state` auto-migrates v1 with backup.
- Removes: `FinalWriteState`, `FINAL_WRITE_STATUSES`, `FACTUAL_REVIEW_STATUSES`, `PaperiumState.expected_section_ids`, `PaperiumState.final_write`, old `SectionState` fields (`factual_review_status`, `factual_review_result_path`).

- [ ] **Step 1: Write failing state v2 tests**

Replace the v1 section/final-write assertions in `tests/paperium/test_paperium_state.py` (the round-trip test currently asserts `expected_section_ids`, `final_write`, and `schema_version == 1`) and add:

```python
import json
import shutil

import pytest

from paperium.state import (
    PaperiumState,
    ReportState,
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
```

Keep the existing tests for `SelectedExperiment`, `WorkerRecord`, `RankingState`, `QuestionFocusState`, and `ContextRequestState` unchanged; update the main round-trip test to stop asserting removed fields.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_state.py -q`
Expected: FAIL — `ImportError: cannot import name 'ReportState'` (and related).

- [ ] **Step 3: Implement schema v2**

In `src/paperium/state.py`:

Set constants:

```python
SCHEMA_VERSION = 2
PHASES = {
    "selecting",
    "analyzing",
    "fact_checking",
    "ranking",
    "mapping",
    "writing",
    "failed",
}
SECTION_STATUSES = {"draft", "revised", "approved", "dropped"}
```

Delete `FINAL_WRITE_STATUSES`, `FACTUAL_REVIEW_STATUSES`, and the `FinalWriteState` class. Replace `SectionState` with:

```python
@dataclass
class SectionState:
    id: str
    title: str
    path: str
    facts_path: str
    status: str = "draft"
    revision_rounds: int = 0
    order: int = 0
    break_before: bool = False
    draft_hash: str | None = None
    last_run_failed: str | None = None

    def __post_init__(self) -> None:
        _validate_enum("section status", self.status, SECTION_STATUSES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "break_before": self.break_before,
            "draft_hash": self.draft_hash,
            "facts_path": self.facts_path,
            "id": self.id,
            "last_run_failed": self.last_run_failed,
            "order": self.order,
            "path": self.path,
            "revision_rounds": self.revision_rounds,
            "status": self.status,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectionState:
        data = _expect_mapping(data, "section")
        try:
            return cls(
                id=data["id"],
                title=data["title"],
                path=data["path"],
                facts_path=data["facts_path"],
                status=data.get("status", "draft"),
                revision_rounds=data.get("revision_rounds", 0),
                order=data.get("order", 0),
                break_before=data.get("break_before", False),
                draft_hash=data.get("draft_hash"),
                last_run_failed=data.get("last_run_failed"),
            )
        except KeyError as exc:
            raise StateError(f"missing section field: {exc.args[0]}") from exc
```

Add `ReportState`:

```python
@dataclass
class ReportState:
    path: str = ".paperium/REPORT.md"
    assembled_at: str | None = None
    content_hash: str | None = None
    stale: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "assembled_at": self.assembled_at,
            "content_hash": self.content_hash,
            "path": self.path,
            "stale": self.stale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReportState:
        data = _expect_mapping(data, "report")
        return cls(
            path=data.get("path", ".paperium/REPORT.md"),
            assembled_at=data.get("assembled_at"),
            content_hash=data.get("content_hash"),
            stale=data.get("stale", False),
        )
```

In `PaperiumState`: replace `expected_section_ids` and `final_write` fields with `report: ReportState = field(default_factory=ReportState)`. Update `to_dict()` (emit `"report"`, drop `"expected_section_ids"` and `"final_write"`) and `from_dict()` (`report=ReportState.from_dict(data.get("report", {}))`).

Add migration and wire it into `load_state`:

```python
def migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    data["schema_version"] = 2
    phase = data.get("phase", "selecting")
    if phase in {"reviewing", "complete"}:
        phase = "writing"
    data["phase"] = phase
    data.pop("expected_section_ids", None)
    data.pop("final_write", None)
    # v1 section records have an incompatible shape and were empty in practice
    data["sections"] = []
    data["report"] = {}
    return data


def load_state(path: str | Path) -> PaperiumState:
    source = Path(path)
    try:
        with source.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise StateError(f"invalid state JSON: {exc}") from exc
    if isinstance(data, dict) and data.get("schema_version") == 1:
        backup = source.with_name("state.v1.backup.json")
        if not backup.exists():
            shutil.copyfile(source, backup)
        data = migrate_v1_to_v2(data)
    return PaperiumState.from_dict(data)
```

Add `import shutil` at the top. `PaperiumState.from_dict` keeps raising `StateError` for any `schema_version != SCHEMA_VERSION`.

- [ ] **Step 4: Run state tests**

Run: `uv run pytest tests/paperium/test_paperium_state.py -q`
Expected: PASS. Other test files will fail until later tasks — that is expected; do not run the full suite yet.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/state.py tests/paperium/test_paperium_state.py
git commit -m "Move Paperium state to schema v2 with sections registry"
```

### Task 2: Path Helpers

**Files:**
- Modify: `src/paperium/paths.py`
- Test: `tests/paperium/test_paperium_paths.py`

**Interfaces:**
- Produces on `PaperiumPaths`: `style_path`, `report_template_path`, `report_path`, `report_draft_path` (properties), `section_facts_path(section_id) -> Path`, `section_prompt_path(section_id, round_number) -> Path`. Existing `section_path(section_id)` unchanged.

- [ ] **Step 1: Write failing path tests**

Add to `tests/paperium/test_paperium_paths.py`:

```python
def test_v2_paths(tmp_path):
    paths = PaperiumPaths(tmp_path / "repo")
    root = tmp_path / "repo/.paperium"
    assert paths.style_path == root / "style.md"
    assert paths.report_template_path == root / "report-template.md"
    assert paths.report_path == root / "REPORT.md"
    assert paths.report_draft_path == root / "REPORT.draft.md"
    assert paths.section_facts_path("ch1-s1") == root / "sections/ch1-s1.facts.md"
    assert paths.section_prompt_path("ch1-s1", 2) == root / "prompts/ch1-s1.round2.prompt.md"
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_paths.py -q`
Expected: FAIL — `AttributeError: 'PaperiumPaths' object has no attribute 'style_path'`.

- [ ] **Step 3: Implement path helpers**

Add to `PaperiumPaths` in `src/paperium/paths.py`:

```python
    @property
    def style_path(self) -> Path:
        return self.root_dir / "style.md"

    @property
    def report_template_path(self) -> Path:
        return self.root_dir / "report-template.md"

    @property
    def report_path(self) -> Path:
        return self.root_dir / "REPORT.md"

    @property
    def report_draft_path(self) -> Path:
        return self.root_dir / "REPORT.draft.md"

    def section_facts_path(self, section_id: str) -> Path:
        return self.root_dir / "sections" / f"{section_id}.facts.md"

    def section_prompt_path(self, section_id: str, round_number: int) -> Path:
        return self.root_dir / "prompts" / f"{section_id}.round{round_number}.prompt.md"
```

- [ ] **Step 4: Run path tests**

Run: `uv run pytest tests/paperium/test_paperium_paths.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/paths.py tests/paperium/test_paperium_paths.py
git commit -m "Add Paperium v2 path helpers"
```

### Task 3: Inline Note Extraction

**Files:**
- Create: `src/paperium/notes.py`
- Test: `tests/paperium/test_paperium_notes.py`

**Interfaces:**
- Produces: `extract_notes(text: str) -> list[str]` — ordered inline `/.../` note contents, stripped. A span only counts as a note when its content contains at least one space (filters path segments like `questions/q001/...`).

- [ ] **Step 1: Write failing note tests**

```python
from paperium.notes import extract_notes


def test_extracts_simple_note():
    assert extract_notes("Text /remove this sentence/ more text") == ["remove this sentence"]


def test_extracts_multiple_notes_in_order():
    text = "A /first note here/ B\nrow | cell /second note too/ |\n"
    assert extract_notes(text) == ["first note here", "second note too"]


def test_ignores_paths_and_slashes_without_spaces():
    text = "See questions/q001/experiments/exp001 and a/b pairs."
    assert extract_notes(text) == []


def test_note_inside_table_cell():
    text = "| Nastavení | HPI /remove that it was already mentioned/ | Výsledek |"
    assert extract_notes(text) == ["remove that it was already mentioned"]


def test_no_notes_returns_empty():
    assert extract_notes("Plain text without any markers.") == []


def test_unterminated_marker_is_not_a_note():
    assert extract_notes("Broken /note without closing slash") == []
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_notes.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'paperium.notes'`.

- [ ] **Step 3: Implement extraction**

`src/paperium/notes.py`:

```python
import re

_NOTE_PATTERN = re.compile(r"/([^/\n]+?)/")


def extract_notes(text: str) -> list[str]:
    notes: list[str] = []
    for match in _NOTE_PATTERN.finditer(text):
        content = match.group(1).strip()
        if " " in content:
            notes.append(content)
    return notes
```

Note: `test_ignores_paths_and_slashes_without_spaces` passes because path segments (`q001`, `experiments`) contain no spaces. If the multi-segment path test fails because the regex pairs across segments, that is still filtered by the space rule — segments never contain spaces.

- [ ] **Step 4: Run note tests**

Run: `uv run pytest tests/paperium/test_paperium_notes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/notes.py tests/paperium/test_paperium_notes.py
git commit -m "Extract Paperium inline revision notes"
```

### Task 4: Writer Prompt Builders

**Files:**
- Create: `src/paperium/writer_prompts.py`
- Test: `tests/paperium/test_paperium_writer_prompts.py`

**Interfaces:**
- Consumes: `paperium.notes.extract_notes`.
- Produces: `build_writer_prompt(*, title: str, facts: str, style: str, output_path: str, draft: str | None = None) -> str`. When `draft` is `None` or blank, returns the initial-draft prompt; otherwise returns the revision prompt with fact-lock and extracted notes.
- Produces: `FACT_LOCK = "Keep all numbers, table rows, and claims unchanged unless a user note explicitly asks."`

- [ ] **Step 1: Write failing prompt tests**

```python
from paperium.writer_prompts import FACT_LOCK, build_writer_prompt


def test_initial_prompt_contains_contract_facts_and_style():
    prompt = build_writer_prompt(
        title="GPU propustnost",
        facts="- throughput 13,585 pages/s",
        style="- Czech decimal commas",
        output_path=".paperium/workers/w1/output.md",
    )
    assert "You are writing one section of a client-facing report." in prompt
    assert "Output only the final Markdown section" in prompt
    assert "## GPU propustnost" in prompt
    assert "- throughput 13,585 pages/s" in prompt
    assert "- Czech decimal commas" in prompt
    assert ".paperium/workers/w1/output.md" in prompt
    assert FACT_LOCK not in prompt


def test_revision_prompt_has_fact_lock_notes_and_draft():
    draft = "Text /remove this sentence/ rest.\nMore /use word run instead/ text."
    prompt = build_writer_prompt(
        title="GPU propustnost",
        facts="- facts",
        style="- style rule",
        output_path=".paperium/workers/w1/output.md",
        draft=draft,
    )
    assert "You are revising one section of a client-facing report." in prompt
    assert FACT_LOCK in prompt
    assert "1. remove this sentence" in prompt
    assert "2. use word run instead" in prompt
    assert draft in prompt
    assert "- style rule" in prompt


def test_blank_draft_selects_initial_prompt():
    prompt = build_writer_prompt(
        title="T", facts="f", style="s", output_path="o.md", draft="  \n"
    )
    assert "You are writing one section" in prompt
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_writer_prompts.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement prompt builders**

`src/paperium/writer_prompts.py`:

```python
from paperium.notes import extract_notes

FACT_LOCK = (
    "Keep all numbers, table rows, and claims unchanged unless a user note explicitly asks."
)

_OUTPUT_CONTRACT = (
    "Output only the final Markdown section. Write it to the output file below.\n"
    "Do not include commentary, experiment IDs, folder names, artifact paths,\n"
    "selectors, or internal validation terms."
)


def build_writer_prompt(
    *,
    title: str,
    facts: str,
    style: str,
    output_path: str,
    draft: str | None = None,
) -> str:
    if draft is None or not draft.strip():
        return _initial_prompt(title=title, facts=facts, style=style, output_path=output_path)
    return _revision_prompt(
        title=title, facts=facts, style=style, output_path=output_path, draft=draft
    )


def _initial_prompt(*, title: str, facts: str, style: str, output_path: str) -> str:
    return "\n".join(
        [
            "You are writing one section of a client-facing report.",
            "",
            _OUTPUT_CONTRACT,
            f"Output file: {output_path}",
            "",
            "Section heading (use verbatim):",
            f"## {title}",
            "",
            "Facts and purpose (use only these facts; do not add new claims):",
            facts,
            "",
            "Style (follow exactly):",
            style,
            "",
        ]
    )


def _revision_prompt(
    *, title: str, facts: str, style: str, output_path: str, draft: str
) -> str:
    notes = extract_notes(draft)
    numbered = [f"{index}. {note}" for index, note in enumerate(notes, start=1)]
    return "\n".join(
        [
            "You are revising one section of a client-facing report.",
            "",
            _OUTPUT_CONTRACT,
            f"Output file: {output_path}",
            "",
            FACT_LOCK,
            "",
            "Section heading (use verbatim):",
            f"## {title}",
            "",
            "User notes to address (remove the inline /.../ notes from the text):",
            *(numbered or ["(no inline notes found; improve per style only)"]),
            "",
            "Style (follow exactly):",
            style,
            "",
            "Current draft (inline notes still present):",
            "",
            draft,
            "",
        ]
    )
```

Design note: per the spec, the revision template contains notes, style, and the draft — not the facts block. Facts remain represented through the existing draft, and the fact-lock forbids changing claims. The signature still accepts `facts` so `build_writer_prompt` has one call shape for both modes.

- [ ] **Step 4: Run prompt tests**

Run: `uv run pytest tests/paperium/test_paperium_writer_prompts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/writer_prompts.py tests/paperium/test_paperium_writer_prompts.py
git commit -m "Add Paperium writer prompt templates"
```

### Task 5: Init Scaffolds For Style And Report Template

**Files:**
- Create: `src/paperium/templates.py`
- Modify: `src/paperium/cli.py` (`_run_init`)
- Test: `tests/paperium/test_paperium_cli.py`

**Interfaces:**
- Produces: `templates.STYLE_SCAFFOLD: str`, `templates.REPORT_TEMPLATE_SCAFFOLD: str` (contains the literal placeholder `{{sections}}`), `templates.ensure_scaffolds(repo: Path) -> None` — writes both files only if missing.

- [ ] **Step 1: Write failing init scaffold test**

Add to `tests/paperium/test_paperium_cli.py`:

```python
def test_init_scaffolds_style_and_report_template(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    style = (repo / ".paperium/style.md").read_text()
    template = (repo / ".paperium/report-template.md").read_text()
    assert "Terminology" in style
    assert "{{sections}}" in template
    # idempotent: user edits survive re-init
    (repo / ".paperium/style.md").write_text("user edited")
    assert main(["--repo", str(repo), "init"]) == 0
    assert (repo / ".paperium/style.md").read_text() == "user edited"
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_cli.py::test_init_scaffolds_style_and_report_template -q`
Expected: FAIL — style.md not created.

- [ ] **Step 3: Implement scaffolds**

`src/paperium/templates.py`:

```python
from pathlib import Path

from paperium.paths import PaperiumPaths

STYLE_SCAFFOLD = """\
# Report Style

Conversation language with the user may differ from the report language.

## Audience And Language

- Write clear, simple prose for the client audience.
- State the report language here (for example: Czech for a client in Czechia).

## Writing Rules

- Do not mention experiment IDs, folder names, internal run names, selectors,
  log states, or validation mechanics.
- Do not write like an audit log; write like a concise technical recommendation.
- Use exact numbers mainly in tables; round to 3 decimals in tables unless
  exactness matters. In prose, explain what a number means for the decision.
- One central claim per paragraph. No walls of text.

## Terminology

| Avoid | Use instead |
|---|---|
| collector status, invalid profiles, reason_codes | (do not mention) |
| accuracy | relative text quality |

Add a row whenever a revision note establishes a term rule.
"""

REPORT_TEMPLATE_SCAFFOLD = """\
<style>
img { max-width: 100%; }
.page-break { page-break-after: always; }
figure.dataset-example { text-align: center; }
figure.dataset-example img { max-height: 480px; }
</style>

{{sections}}
"""


def ensure_scaffolds(repo: Path) -> None:
    paths = PaperiumPaths(repo)
    paths.root_dir.mkdir(parents=True, exist_ok=True)
    if not paths.style_path.exists():
        paths.style_path.write_text(STYLE_SCAFFOLD, encoding="utf-8")
    if not paths.report_template_path.exists():
        paths.report_template_path.write_text(REPORT_TEMPLATE_SCAFFOLD, encoding="utf-8")
```

In `src/paperium/cli.py`, inside `_run_init` after `save_state`:

```python
import paperium.templates  # top of file

    paperium.templates.ensure_scaffolds(repo)
```

- [ ] **Step 4: Run CLI tests**

Run: `uv run pytest tests/paperium/test_paperium_cli.py::test_init_scaffolds_style_and_report_template -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/templates.py src/paperium/cli.py tests/paperium/test_paperium_cli.py
git commit -m "Scaffold Paperium style and report template on init"
```

### Task 6: Section Registry Operations

**Files:**
- Create: `src/paperium/sections.py`
- Test: `tests/paperium/test_paperium_sections.py`

**Interfaces:**
- Consumes: `SectionState`, `PaperiumState` from Task 1; `PaperiumPaths` from Task 2.
- Produces: `SectionError(Exception)`; `find_section(state, section_id) -> SectionState` (raises `SectionError` if unknown); `add_section(repo, state, section_id, *, title, order=None, break_before=False) -> SectionState` (creates empty draft + facts stub files, rejects duplicate ids and unsafe ids); `drop_section(state, section_id)`; `approve_section_v2(state, section_id)` (requires `revision_rounds >= 1`); `record_section(repo, state, section_id, *, approve=False) -> SectionState` (requires non-empty draft file; bumps `revision_rounds`; sets status `draft` on round 1 else `revised`; stores `draft_hash`; clears `last_run_failed`; optional approve); `mark_report_stale(state)` (sets `report.stale = True` only when `report.assembled_at` is not None). `record_section` and `approve_section_v2` call `mark_report_stale`.

- [ ] **Step 1: Write failing registry tests**

```python
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_sections.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement registry operations**

`src/paperium/sections.py`:

```python
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
```

- [ ] **Step 4: Run registry tests**

Run: `uv run pytest tests/paperium/test_paperium_sections.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/sections.py tests/paperium/test_paperium_sections.py
git commit -m "Add Paperium section registry operations"
```

### Task 7: Section Prompt Archiving And Run

**Files:**
- Modify: `src/paperium/sections.py`
- Test: `tests/paperium/test_paperium_sections.py`

**Interfaces:**
- Consumes: `build_writer_prompt`, `FACT_LOCK` (Task 4); `run_worker`, `WorkerSpec`, `build_worker_record`, `worker_id_for` (existing); `WorkerRecord.from_dict` (existing).
- Produces: `prepare_prompt(repo, state, section_id) -> tuple[Path, str]` — builds the prompt from facts + style + draft, archives it to `prompts/<id>.round<N>.prompt.md` where `N = revision_rounds + 1`, returns `(archive_path, prompt_text)`. Re-emitting overwrites the same round file.
- Produces: `run_section(repo, state, section_id, *, backend="claude", timeout_seconds=1800, runner=run_worker) -> SectionState` — prepares the prompt, runs a `write` worker, promotes non-empty `output.md` atomically to the section draft, records the round; on any failure sets `last_run_failed` and preserves the previous draft. Appends a `WorkerRecord` to `state.workers` in both cases.

- [ ] **Step 1: Write failing prompt/run tests**

Add to `tests/paperium/test_paperium_sections.py`:

```python
from paperium.sections import prepare_prompt, run_section
from paperium.workers import WorkerResult


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
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_sections.py -q`
Expected: FAIL — `ImportError: cannot import name 'prepare_prompt'`.

- [ ] **Step 3: Implement prompt archiving and run**

Add to `src/paperium/sections.py`:

```python
import os
import tempfile

from paperium.state import WorkerRecord
from paperium.worker_runner import run_worker
from paperium.workers import WorkerSpec, build_worker_record, worker_id_for
from paperium.writer_prompts import build_writer_prompt

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
```

- [ ] **Step 4: Run section tests**

Run: `uv run pytest tests/paperium/test_paperium_sections.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/sections.py tests/paperium/test_paperium_sections.py
git commit -m "Run Paperium section writer workers"
```

### Task 8: Report Assembly

**Files:**
- Create: `src/paperium/assemble.py`
- Test: `tests/paperium/test_paperium_assemble.py`

**Interfaces:**
- Consumes: `PaperiumPaths`, `PaperiumState`, `SectionState`.
- Produces: `AssembleError(Exception)`; `assemble_report(repo, state, *, allow_draft=False, force=False) -> Path`. Full mode writes `state.report.path`, sets `assembled_at` (UTC ISO), `content_hash` (sha256 hex of written text), `stale=False`. Draft mode writes `PaperiumPaths.report_draft_path` and does not touch `report` state. Page-break div `<div class="page-break"></div>` is inserted before each section with `break_before=True` (except when it is the first assembled section). Missing referenced images raise `AssembleError` listing all of them. Hand-edited `REPORT.md` (hash mismatch with `content_hash`) requires `force=True`.

- [ ] **Step 1: Write failing assemble tests**

```python
import re
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
        "![diagram](.paperium/images/missing-a.png)\n"
        '<img src=".paperium/images/missing-b.png">\n'
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_assemble.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement assembly**

`src/paperium/assemble.py`:

```python
from __future__ import annotations

import os
import re
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from paperium.paths import PaperiumPaths
from paperium.state import PaperiumState, SectionState

PAGE_BREAK = '<div class="page-break"></div>'
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
_HTML_IMAGE = re.compile(r"<img[^>]+src=\"([^\"]+)\"")


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
        body = (repo / section.path).read_text(encoding="utf-8").rstrip()
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
        target = repo / state.report.path
        if (
            target.exists()
            and state.report.content_hash is not None
            and sha256(target.read_bytes()).hexdigest() != state.report.content_hash
            and not force
        ):
            raise AssembleError(
                f"{state.report.path} looks hand-edited; use --force to overwrite"
            )

    _atomic_write(target, text)
    if not allow_draft:
        state.report.assembled_at = (
            datetime.now(UTC).replace(microsecond=0).isoformat()
        )
        state.report.content_hash = sha256(text.encode("utf-8")).hexdigest()
        state.report.stale = False
    return target


def _missing_images(repo: Path, body: str) -> list[str]:
    references = _MD_IMAGE.findall(body) + _HTML_IMAGE.findall(body)
    missing = []
    for reference in references:
        if reference.startswith(("http://", "https://", "data:")):
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
```

- [ ] **Step 4: Run assemble tests**

Run: `uv run pytest tests/paperium/test_paperium_assemble.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/assemble.py tests/paperium/test_paperium_assemble.py
git commit -m "Assemble Paperium report from approved sections"
```

### Task 9: Reconcile

**Files:**
- Create: `src/paperium/reconcile.py`
- Test: `tests/paperium/test_paperium_reconcile.py`

**Interfaces:**
- Consumes: `PaperiumPaths`, `PaperiumState`, `SectionState`, `sections.mark_report_stale`.
- Produces: `reconcile_state(repo, state, *, fix=False) -> list[str]` — human-readable drift messages, deterministic order. Detects: draft file without a section record (fix: add a record with `status="draft"`, `revision_rounds=1`, computed hash, `order` after existing); record whose draft file is missing (report only, never fixed by deletion); recorded `draft_hash` differing from the file on disk (fix: update hash, bump `revision_rounds`, mark report stale). Facts files (`*.facts.md`) and review files are ignored during the scan. Returns `[]` when nothing drifted.

- [ ] **Step 1: Write failing reconcile tests**

```python
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
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_reconcile.py -q`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement reconcile**

`src/paperium/reconcile.py`:

```python
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
    draft_files = sorted(
        path
        for path in sections_dir.glob("*.md")
        if not path.name.endswith(".facts.md")
    ) if sections_dir.exists() else []

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
                    facts_path=paths.section_facts_path(section_id)
                    .relative_to(repo)
                    .as_posix(),
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
```

Note on `test_hash_drift_is_reported_and_fixable`: the fix path is exercised via the second `reconcile_state(..., fix=True)` call, whose messages are not asserted — assertions target the mutated state.

- [ ] **Step 4: Run reconcile tests**

Run: `uv run pytest tests/paperium/test_paperium_reconcile.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/paperium/reconcile.py tests/paperium/test_paperium_reconcile.py
git commit -m "Reconcile Paperium section state with disk"
```

### Task 10: CLI Wiring And V1 Writing Removal

**Files:**
- Modify: `src/paperium/cli.py`, `src/paperium/commands.py`, `src/paperium/output.py`
- Delete: `src/paperium/writing.py`, `tests/paperium/test_paperium_writing.py`
- Test: `tests/paperium/test_paperium_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 6–9.
- Produces CLI surface: `section add <id> --title T [--order N] [--break-before]`, `section list`, `section drop <id>`, `section approve <id>`, `section record <id> [--approve]`, `section notes <id>`, `section prompt <id>`, `section run <id> [--backend claude|codex]`, `assemble [--allow-draft] [--force]`, `reconcile [--fix]`. Removes the `write` command and the V1 `section approve --title --path` / `section skip` forms.
- In `commands.py`: delete `approve_section`, `skip_section`, `write_paper`, `_recompute_final_write_status`, `_ordered_writable_sections`, `_require_expected_section`, `_section_id_for`, and the `can_write_paper`/`render_paper`/`SectionState` imports; in `run_rank` delete the four lines setting `state.expected_section_ids`, `state.sections = []`, `state.final_write.status`, and `state.final_write.written_at` (keep the two `approved = False` resets and `state.phase = "mapping"`).
- In `output.py`: `format_status_plain(state)` gains a section table (`id`, `status`, `rounds`, `order`) and a report line (`report: <path> stale=<bool>` when `assembled_at` is set, else `report: not assembled`).

- [ ] **Step 1: Write failing CLI tests**

Replace the V1 `write`/`section approve --title --path` tests in `tests/paperium/test_paperium_cli.py` with:

```python
def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert main(["--repo", str(repo), "init"]) == 0
    return repo


def test_section_add_list_and_approve_flow(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    (repo / ".paperium/sections/ch1-s1.md").write_text("## Dataset\nbody\n")
    assert main(["--repo", str(repo), "section", "record", "ch1-s1"]) == 0
    assert main(["--repo", str(repo), "section", "approve", "ch1-s1"]) == 0
    assert main(["--repo", str(repo), "section", "list"]) == 0
    output = capsys.readouterr().out
    assert "ch1-s1" in output
    assert "approved" in output


def test_section_notes_and_prompt(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    (repo / ".paperium/sections/ch1-s1.md").write_text("Text /fix this wording/ more.\n")
    assert main(["--repo", str(repo), "section", "record", "ch1-s1"]) == 0
    assert main(["--repo", str(repo), "section", "notes", "ch1-s1"]) == 0
    assert "fix this wording" in capsys.readouterr().out
    assert main(["--repo", str(repo), "section", "prompt", "ch1-s1"]) == 0
    assert "You are revising one section" in capsys.readouterr().out
    assert (repo / ".paperium/prompts/ch1-s1.round2.prompt.md").exists()


def test_assemble_and_reconcile_commands(tmp_path):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    (repo / ".paperium/sections/ch1-s1.md").write_text("## Dataset\nbody\n")
    assert main(["--repo", str(repo), "section", "record", "ch1-s1", "--approve"]) == 0
    assert main(["--repo", str(repo), "assemble"]) == 0
    assert (repo / ".paperium/REPORT.md").exists()
    assert main(["--repo", str(repo), "reconcile"]) == 0
    # unapproved section blocks full assembly, draft mode succeeds
    assert main(["--repo", str(repo), "section", "add", "ch2-s1", "--title", "CPU"]) == 0
    (repo / ".paperium/sections/ch2-s1.md").write_text("## CPU\nbody\n")
    assert main(["--repo", str(repo), "section", "record", "ch2-s1"]) == 0
    assert main(["--repo", str(repo), "assemble"]) == 2
    assert main(["--repo", str(repo), "assemble", "--allow-draft"]) == 0
    assert (repo / ".paperium/REPORT.draft.md").exists()


def test_write_command_is_gone(tmp_path):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "write"]) == 4


def test_status_shows_sections(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    assert main(["--repo", str(repo), "section", "add", "ch1-s1", "--title", "Dataset"]) == 0
    assert main(["--repo", str(repo), "status"]) == 0
    output = capsys.readouterr().out
    assert "ch1-s1" in output
    assert "report: not assembled" in output
```

Also update `test_command_surface_lists_v1_commands` to assert `assemble` and `reconcile` appear in `--help` and `write` does not.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/paperium/test_paperium_cli.py -q`
Expected: FAIL — new subcommands unknown.

- [ ] **Step 3: Implement CLI wiring and removals**

In `src/paperium/cli.py`:

Replace the `section` and `write` parser setup in `build_parser()` with:

```python
    section_parser = subparsers.add_parser("section")
    section_subparsers = section_parser.add_subparsers(dest="section_action")
    section_add = section_subparsers.add_parser("add")
    section_add.add_argument("section_id")
    section_add.add_argument("--title", required=True)
    section_add.add_argument("--order", type=int, default=None)
    section_add.add_argument("--break-before", action="store_true", dest="break_before")
    section_subparsers.add_parser("list")
    for name in ("drop", "approve", "notes", "prompt"):
        simple = section_subparsers.add_parser(name)
        simple.add_argument("section_id")
    section_record = section_subparsers.add_parser("record")
    section_record.add_argument("section_id")
    section_record.add_argument("--approve", action="store_true")
    section_run = section_subparsers.add_parser("run")
    section_run.add_argument("section_id")
    section_run.add_argument("--backend", choices=["claude", "codex"], default="claude")
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--allow-draft", action="store_true", dest="allow_draft")
    assemble_parser.add_argument("--force", action="store_true")
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--fix", action="store_true")
```

Delete the `subparsers.add_parser("write")` line and the whole `_run_write` function; delete the old `_run_section`. Add the new handlers:

```python
import paperium.assemble
import paperium.reconcile
import paperium.sections
from paperium.notes import extract_notes


def _run_section_v2(repo: Path, args: argparse.Namespace) -> int:
    action = args.section_action
    if action is None:
        print("paperium: section requires a subcommand", file=sys.stderr)
        return INVALID_INVOCATION
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        if action == "add":
            paperium.sections.add_section(
                repo,
                state,
                args.section_id,
                title=args.title,
                order=args.order,
                break_before=args.break_before,
            )
        elif action == "list":
            for section in sorted(state.sections, key=lambda item: (item.order, item.id)):
                print(
                    f"{section.order:>3}  {section.id}  {section.status}"
                    f"  rounds={section.revision_rounds}  {section.title}"
                )
        elif action == "drop":
            paperium.sections.drop_section(state, args.section_id)
        elif action == "approve":
            paperium.sections.approve_section_v2(state, args.section_id)
        elif action == "record":
            paperium.sections.record_section(
                repo, state, args.section_id, approve=args.approve
            )
        elif action == "notes":
            section = paperium.sections.find_section(state, args.section_id)
            draft = repo / section.path
            text = draft.read_text(encoding="utf-8") if draft.exists() else ""
            for index, note in enumerate(extract_notes(text), start=1):
                print(f"{index}. {note}")
        elif action == "prompt":
            archive, prompt = paperium.sections.prepare_prompt(repo, state, args.section_id)
            print(prompt)
            print(f"archived: {archive.relative_to(repo).as_posix()}", file=sys.stderr)
        elif action == "run":
            section = paperium.sections.run_section(
                repo, state, args.section_id, backend=args.backend
            )
            if section.last_run_failed is not None:
                save_state(state_path, state)
                print(
                    f"paperium: section run failed: {section.last_run_failed}",
                    file=sys.stderr,
                )
                return DETERMINISTIC_FAILURE
        else:
            print(f"paperium: unknown section action: {action}", file=sys.stderr)
            return INVALID_INVOCATION
    except paperium.sections.SectionError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    return SUCCESS


def _run_assemble(repo: Path, *, allow_draft: bool, force: bool) -> int:
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    try:
        target = paperium.assemble.assemble_report(
            repo, state, allow_draft=allow_draft, force=force
        )
    except paperium.assemble.AssembleError as exc:
        print(f"paperium: {exc}", file=sys.stderr)
        return DETERMINISTIC_FAILURE
    save_state(state_path, state)
    print(f"Assembled: {target.relative_to(repo).as_posix()}")
    return SUCCESS


def _run_reconcile(repo: Path, *, fix: bool) -> int:
    loaded = _load_state_for_command(repo)
    if isinstance(loaded, int):
        return loaded
    state_path, state = loaded
    drift = paperium.reconcile.reconcile_state(repo, state, fix=fix)
    for message in drift:
        print(message)
    if fix:
        save_state(state_path, state)
    if not drift:
        print("no drift")
    return SUCCESS
```

Wire dispatch in `main()` (replace the `section` and `write` branches):

```python
    if args.command == "section":
        return _run_section_v2(repo, args)
    if args.command == "assemble":
        return _run_assemble(repo, allow_draft=args.allow_draft, force=args.force)
    if args.command == "reconcile":
        return _run_reconcile(repo, fix=args.fix)
```

In `src/paperium/commands.py`: apply the removals listed in **Interfaces** (functions, imports, and the four `run_rank` lines). In `src/paperium/output.py`: extend `format_status_plain` to append, after existing content:

```python
    lines.append("sections:")
    for section in sorted(state.sections, key=lambda item: (item.order, item.id)):
        lines.append(
            f"  {section.order:>3}  {section.id}  {section.status}"
            f"  rounds={section.revision_rounds}"
        )
    if state.report.assembled_at is None:
        lines.append("report: not assembled")
    else:
        lines.append(f"report: {state.report.path} stale={state.report.stale}")
```

(Adapt variable names to the existing function body; it builds and joins a list of lines.)

Delete `src/paperium/writing.py` and `tests/paperium/test_paperium_writing.py`:

```bash
git rm src/paperium/writing.py tests/paperium/test_paperium_writing.py
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest tests/paperium -q`
Expected: PASS. Fix any remaining v1 references (search for `expected_section_ids`, `final_write`, `can_write_paper` across `src/` and `tests/` — all must be gone).

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add -A src/paperium tests/paperium
git commit -m "Wire Paperium v2 section, assemble, and reconcile commands"
```

### Task 11: Skill Updates

**Files:**
- Modify: `skills/paperium-write-paper/SKILL.md`
- Modify: `skills/paperium-writer/SKILL.md`

**Interfaces:**
- Consumes: the CLI surface from Task 10.
- Produces: skill instructions matching the V2 workflow. No code.

- [ ] **Step 1: Rewrite `skills/paperium-write-paper/SKILL.md`**

Replace the body (keep the frontmatter block with `name` and `description`, updating the description to mention the sections workbench) with:

```markdown
You are using the paperium-write-paper skill.

PURPOSE

Drive the Paperium V2 sections workbench: register report sections ad hoc,
curate per-section facts, run writer workers, iterate via inline notes, and
assemble the final report.

WORKFLOW

1. Ensure the pipeline half is done: analyses fact-check-approved, ranking and
   question focus approved (`paperium status`).
2. Discuss report structure with the user. The user may keep a private outline
   file; never edit it. Register sections as they are decided:
   `paperium section add <id> --title "..." [--break-before]`.
3. For each section, curate `.paperium/sections/<id>.facts.md` with the user:
   purpose, what the section is NOT, whitelisted facts from approved
   `analysis.md` files, interpretation guardrails, optional structure skeleton.
4. Draft with `paperium section run <id>` (default). If the launcher blocks,
   fall back to `paperium section prompt <id>`, run the writer manually, save
   the section file, then `paperium section record <id>`.
5. The user adds inline `/.../` notes to drafts. Check them with
   `paperium section notes <id>`, then re-run `paperium section run <id>` —
   the revision prompt carries the notes and a fact-lock automatically.
6. When a revision note establishes a term or tone rule, propose adding it to
   `.paperium/style.md` (user approves). style.md is injected into every
   writer prompt.
7. Approve finished sections: `paperium section approve <id>`.
8. Assemble: `paperium assemble` (all sections approved) or
   `paperium assemble --allow-draft` for a preview at
   `.paperium/REPORT.draft.md`. PDF export happens outside Paperium.
9. If state and files drift, run `paperium reconcile` (add `--fix` to sync).

RULES

- Never edit the user's outline or hand-written structure files.
- Facts files contain only facts traceable to approved analyses.
- Do not hand-edit `.paperium/REPORT.md`; edit sections and re-assemble.
```

- [ ] **Step 2: Update `skills/paperium-writer/SKILL.md`**

Update its workflow overview so the writing stage references the section
commands above instead of `paperium write` / `section approve --title --path`.
Keep the pipeline-stage instructions (select/analyze/rank/approve) unchanged.

- [ ] **Step 3: Verify no stale command references**

Run: `grep -rn "paperium write\|--path\|section skip\|expected_section" skills/`
Expected: no matches referencing removed commands.

- [ ] **Step 4: Commit**

```bash
git add skills/paperium-write-paper/SKILL.md skills/paperium-writer/SKILL.md
git commit -m "Update Paperium skills for v2 sections workbench"
```

### Task 12: Full Verification

**Files:**
- None new.

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest tests -q`
Expected: PASS (paperctl tests included — they must be unaffected).

- [ ] **Step 2: Lint**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: clean.

- [ ] **Step 3: Smoke the CLI end to end against a scratch repo**

```bash
scratch=$(mktemp -d)
git -C "$scratch" init -q
uv run paperium --repo "$scratch" init
uv run paperium --repo "$scratch" section add ch1-s1 --title "Dataset"
printf '## Dataset\nbody /tighten this sentence now/\n' > "$scratch/.paperium/sections/ch1-s1.md"
uv run paperium --repo "$scratch" section record ch1-s1
uv run paperium --repo "$scratch" section notes ch1-s1
uv run paperium --repo "$scratch" section prompt ch1-s1 | head -5
uv run paperium --repo "$scratch" section approve ch1-s1
uv run paperium --repo "$scratch" assemble
uv run paperium --repo "$scratch" status
uv run paperium --repo "$scratch" reconcile
```

Expected: notes list the inline note; prompt shows the revision template; assemble reports `.paperium/REPORT.md`; status shows the section table and report line; reconcile prints `no drift`.

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "Finalize Paperium v2 sections workbench"
```
