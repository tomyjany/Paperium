# Paperium V2 — Sections Workbench Design

- Date: 2026-07-02
- Status: Approved design
- Scope: Replace the Paperium V1 writing phase with an ad-hoc sections workbench and report assembly. The V1 pipeline half (select, analyze, fact-check, rank, dispositions, question focus) is unchanged.
- Out of scope: PDF generation (stays in VS Code md2pdf), evidence-lifecycle fixes and bug fixes (boundary-audit crash, scoped re-analysis, progress visibility) — those form a separate small iteration.

## Motivation

Paperium V1 was used end-to-end on a real client report in the `datera` repository. The evidence pipeline (analysis, fact-check, ranking, dispositions, context requests) worked well. The writing phase did not: the user steered the report through a handwritten chapter/section outline, iterated sections via inline `/.../` notes and 36 hand-built Claude prompts, assembled `.paperium/REPORT.md` with a PDF-export formatting layer, and exported a PDF — all outside Paperium state. `state.json` ended with `sections: []` and `final_write: not_started` while the finished report existed.

Sources: `FEED_BACK_FROM_AGENT.md`, `paperium_bug_report.md`, and `.paperium/claude_prompts/*` in the datera instance.

V2 makes that real workflow first-class instead of gating a workflow nobody used.

## Decisions Made During Brainstorming

1. **Hybrid CLI/skill split.** The CLI owns state, prompt templates, and a one-shot section runner; every step is also usable piecemeal (emit prompt / record result) so the flow degrades gracefully to manual driving.
2. **Agent-curated facts.** The writer's fact whitelist per section is a free-form Markdown file curated by the main agent in conversation with the user. No machine provenance verification (trust level: agents do not misreport once `analysis.md` exists).
3. **Ad-hoc section registration.** No outline parsing and no outline file in the loop. Sections are registered by CLI commands as the user goes. The user's handwritten outline stays a private human reference.
4. **Single assemble target.** `paperium assemble` produces one export-ready `REPORT.md` (with the PDF formatting layer applied from a template). There is no separate clean-Markdown target; the PDF is the client deliverable.
5. **Living style file.** `.paperium/style.md` is injected verbatim into every writer prompt. The skill instructs the agent to append new term/tone rules (with user approval) when a revision note establishes one. No CLI parsing or linting of style rules.
6. **Approach: replace the writing subsystem in place.** Keep the pipeline half of `src/paperium` untouched; remove the question-level writing model (`expected_section_ids`, `final_write`, rigid writing phases); add a sections subsystem inside the same package and state file.

## Architecture

### State Schema v2

`.paperium/state.json` moves to `schema_version: 2`.

Unchanged from v1: `selected_experiments`, `workers`, `ranking`, `dispositions_path`, `question_focus`, `context_requests`.

Removed: `expected_section_ids`, `final_write`, and the writing-related `phase` values (`writing`, `reviewing`, `complete`).

Changed:

- `phase` enum simplifies to the pipeline phases plus a terminal `writing` value. Once a repo enters `writing`, progress is tracked per section, not by phase.

Added — `sections` becomes a flat registry of ad-hoc entries:

```json
{
  "id": "chapter2-section3-gpu-throughput",
  "title": "GPU propustnost",
  "path": ".paperium/sections/chapter2-section3-gpu-throughput.md",
  "facts_path": ".paperium/sections/chapter2-section3-gpu-throughput.facts.md",
  "status": "draft",
  "revision_rounds": 3,
  "order": 7,
  "break_before": false,
  "last_run_failed": null
}
```

- `status` enum: `draft | revised | approved | dropped`.
- `order`: integer position for assembly; `section add` defaults to end of list.
- `break_before`: explicit page-break flag (see Assembly).
- `last_run_failed`: `null` or a failure reason string from the most recent `section run`.

Added — `report` replaces `final_write`:

```json
{
  "path": ".paperium/REPORT.md",
  "assembled_at": "2026-07-02T12:00:00Z",
  "content_hash": "sha256:...",
  "stale": false
}
```

- `stale` flips to `true` whenever an approved section's draft changes after the last assembly.
- `content_hash` is the hash of the last assembled `REPORT.md`, used to detect hand-edits.

Migration: loading a v1 state auto-migrates to v2. The v1 `sections` list was empty in practice, so migration drops `expected_section_ids`/`final_write` and maps the phase. The original file is backed up once to `.paperium/state.v1.backup.json`.

### Files Under `.paperium/`

| Path | Owner | Purpose |
|---|---|---|
| `sections/<id>.md` | writer worker / user | section draft; user adds inline `/.../` notes here |
| `sections/<id>.facts.md` | agent + user | per-section purpose, whitelisted facts, interpretation guardrails, optional structure skeleton |
| `style.md` | agent + user | living style/glossary file, injected into every writer prompt |
| `prompts/<id>.round<N>.prompt.md` | CLI | archived prompt per writing round, auto-versioned |
| `report-template.md` | user (scaffolded by init) | export formatting layer for assembly |
| `REPORT.md` | CLI (assemble) | assembled export-ready report |
| `images/*` | agent + user | images referenced by sections |

`init` scaffolds `style.md` (language, audience, terminology table, phrasing rules, numeric formatting rules — with the datera lessons as editable defaults) and `report-template.md`.

## Command Surface

Pipeline commands are unchanged. New/changed commands:

### Section Management

- `paperium section add <id> --title "..." [--order N] [--break-before]` — register a section; creates empty draft and facts-file stubs.
- `paperium section list` — table: id, title, status, revision rounds, stale-vs-report.
- `paperium section drop <id>` — mark `dropped`; kept in state for traceability, excluded from assembly.
- `paperium section approve <id>` — mark `approved`.

### Writing Loop

Each step usable alone; `run` is the one-shot combination.

- `paperium section prompt <id>` — build the writer prompt (initial or revision, auto-selected by whether a non-empty draft exists), archive it to `prompts/<id>.round<N>.prompt.md`, and print it. No LLM call — supports manual driving.
- `paperium section notes <id>` — extract and list inline `/.../` notes from the draft, numbered. Also reports notes still present after a revision (i.e. not consumed by the writer).
- `paperium section record <id> [--approve]` — record that a new draft round landed after a manual run: bump `revision_rounds`, set status (`draft` on round 1, `revised` after), optionally approve.
- `paperium section run <id> [--backend claude|codex]` — one-shot: build prompt, archive it, invoke the writer worker via the existing `worker_runner`, write the draft atomically, update state. Failed runs never clobber the existing draft (write to temp, promote on success) and set `last_run_failed`.

### Assembly and Hygiene

- `paperium assemble [--allow-draft]` — concatenate approved sections by `order` into `REPORT.md` through the export template; refuse if any non-dropped section is unapproved (unless `--allow-draft`); validate referenced images; atomic write; set `report.stale = false` and record `content_hash`.
- `paperium reconcile [--fix]` — scan `.paperium/sections/*` against state; report drift (files without records, records without files, drafts newer than the recorded round, report staleness). `--fix` updates state to match disk. Never deletes files.
- `paperium status` — extended with the section table and report staleness.

### Division of Labor

The CLI never decides what to write. Facts files, `style.md` content, revision notes, and approval decisions belong to the user and the main agent. The reworked `paperium-write-paper` / `paperium-writer` skills instruct the main agent to:

1. curate each section's facts file with the user before the first draft;
2. register sections ad hoc as the report structure emerges;
3. use `section run` by default, falling back to `section prompt` + manual Claude invocation + `section record` when launcher behavior blocks the runner;
4. propose a `style.md` addition whenever a revision note establishes a term or tone rule (user approves the addition);
5. keep approval decisions with the user.

## The Writer Contract (Prompt Templates)

Prompt building codifies the anatomy that emerged over 36 hand-built prompts in datera.

### Initial Draft Prompt

```
1. Role line       — "You are writing one section of a client-facing report."
2. Output contract — output only the final Markdown section; no commentary,
                     no experiment IDs, folder names, artifact paths, selectors,
                     or internal validation terms.
3. Section heading — the registered title, verbatim; the writer does not invent
                     headings.
4. Facts & purpose — <id>.facts.md injected verbatim (purpose, what the section
                     is NOT, whitelisted facts, interpretation guardrails,
                     optional numbered structure skeleton).
5. Style           — style.md injected verbatim.
```

### Revision Prompt

Auto-selected when a non-empty draft exists.

```
1. Role line       — "You are revising one section of a client-facing report."
2. Output contract — same as initial.
3. Fact-lock       — "Keep all numbers, table rows, and claims unchanged unless
                     a user note explicitly asks."
4. User notes      — extracted /.../ notes, numbered.
5. Style           — style.md injected verbatim.
6. Current draft   — full section text with the inline notes still present, so
                     the writer sees their anchors.
```

### Details

- Prompts are archived before the run; history is automatic.
- The writer worker needs no repository read access: everything it may use is in the prompt. Repository reading remains the analysis workers' job.
- Note syntax is `/.../` anywhere in a line, matching existing user practice. The extractor is a deliberately simple regex over `/...text.../` spans; ambiguous matches simply appear in `section notes` output for the user to inspect before running.
- After a successful revision the new draft replaces the old one, consuming the notes. Any note the writer left in place shows up as still pending in `section notes`.
- Numeric precision and formatting (Czech decimal commas, rounding in tables) are `style.md` rules, not CLI-enforced transforms.

## Assembly Mechanics

- Deterministic: approved sections sorted by `order`, joined through `report-template.md`, one atomic write.
- Page breaks: a break divider is inserted before any section whose `break_before` flag is set. Convention: set it on each chapter's first section. (No id-parsing magic.)
- The template documents the figure-wrapper HTML for the agent to use inside sections when large images need PDF-friendly sizing.
- Image validation: every image path referenced by an assembled section must exist under the repo; assembly fails listing all missing images.
- Idempotent re-runs. If `REPORT.md`'s current hash differs from `report.content_hash` (hand-edit), assembly warns and requires `--force` to overwrite. The intended flow is to edit sections, not the report.

## Error Handling

- `section run` inherits `worker_runner` semantics: timeout, non-zero exit, missing output are recorded as `last_run_failed` on the section; the previous draft is preserved.
- `reconcile` is read-only by default and never deletes.
- All state writes are atomic via existing `jsonio`/`atomic` helpers.
- v1→v2 migration is automatic, backed up once, and refuses unknown schema versions with a clear error.

## Testing

All tests LLM-free, following existing `tests/paperium/` conventions:

- state v2 round-trip, enum validation, v1→v2 migration (including backup creation and refusal of unknown versions);
- section registry CRUD, ordering, `dropped` exclusion, `break_before`;
- note extraction: multiple notes per line/file, notes inside tables, no notes, unterminated markers;
- prompt builder golden tests: initial vs revision selection, fact-lock presence, facts/style verbatim injection, archive naming (`round<N>`);
- assemble golden test: fixture sections produce byte-stable `REPORT.md`; unapproved-section refusal; `--allow-draft`; missing-image failure; hand-edit hash warning and `--force`;
- reconcile drift matrix: file-without-record, record-without-file, draft newer than recorded round, staleness reporting, `--fix` behavior;
- `section run` with a fake worker: success, failure, timeout, draft preservation, `last_run_failed` recording;
- CLI surface test covering the new subcommands.

## Non-Goals

- PDF generation (VS Code md2pdf remains the export path).
- Clean-Markdown/Jira render target (the PDF is the deliverable).
- Outline file parsing or generation.
- Fact provenance verification against analyses.
- Style linting or glossary enforcement in the CLI.
- Image registry beyond existence validation.
- Evidence-lifecycle changes (scoped re-analysis, late-evidence dispositions) and the datera bug fixes — separate iteration.
