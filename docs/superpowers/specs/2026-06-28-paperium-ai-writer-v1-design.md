# Paperium AI Writer V1 Design

## Status

Approved design from brainstorming on 2026-06-28.

This design replaces the rejected `paperctl` paper-generation concept recorded in
`docs/decisions/2026-06-27-reject-current-paperctl-concept.md`.

The source-of-truth product note is `docs/dumb_specs/THE_AI_WRITER.md`.

## Problem

The previous system produced too much deterministic evidence inventory and too little useful
paper. The final output must be a short, client-readable technical report that answers the
research questions from experiment results without dumping artifacts.

The target repositories contain question folders and heterogeneous experiment folders. Existing
experiment READMEs can be useful context, but they may also be agent-written and stale. Run
artifacts, especially `outputs/`, are the ground truth for factual claims.

## Product Shape

V1 introduces a new workflow and command named `paperium`. It is separate from the rejected
`paperctl` architecture. `paperctl` may remain in the repository, but V1 does not extend its
evidence-packet-to-draft-paper model.

`paperium` is an agent-led paper writer. The main Codex session remains the workflow conductor:
it selects experiments with the user, launches bounded Codex and Claude workers, monitors progress,
asks for approvals, and writes `PAPER.md` only after section-by-section approval.

`paperium` creates short disposable working artifacts:

- target repo root `.paperium/state.json`;
- per-experiment `<experiment>/.paperium/analysis.md`;
- ranking and question-focus working documents under target repo root `.paperium/`;
- final top-level `PAPER.md` only after interactive approvals.

Existing experiment `README.md` files are inputs only. V1 never edits them. This is intentional:
although the source product note originally imagined generating experiment READMEs, V1 replaces
that with disposable `<experiment>/.paperium/analysis.md` notes because experiment READMEs may
already be project documentation or agent-generated context.

## Responsibilities

### Main Codex Session

The main session owns workflow decisions and user interaction:

- chooses selected experiments with the user;
- approves or rejects requested context expansion;
- reviews ranking and focus proposals with the user;
- drives section-by-section writing approval;
- decides when to write final `PAPER.md`.

### `paperium` Python Helper

The helper is intentionally thin. It owns mechanics, not research judgment:

- verify Codex CLI and Claude CLI are installed;
- provide manual-path and interactive-menu experiment selection;
- add or update target repo `.gitignore` for generated `.paperium` files;
- maintain `.paperium/state.json` for resume and progress;
- launch Codex and Claude worker subprocesses;
- show Rich progress for active workers, current phase, successes, failures, and user-waiting states;
- write generated artifacts to known paths;
- overwrite/update selected generated artifacts during normal runs;
- never delete stale generated files during normal runs.

`paperium` does not decide experiment meaning, rank findings automatically without review, silently
include all experiments, or generate giant evidence drafts.

### Skills

V1 uses one high-level workflow skill and smaller step skills:

- `paperium-writer`: guides the full flow from selected experiments to final `PAPER.md`;
- `paperium-analyze-experiments`: selected experiment analysis and fact-check loop;
- `paperium-rank-findings`: inclusion/exclusion/defer proposal and question-focus mapping;
- `paperium-write-paper`: iterative section-by-section writing;
- `paperium-review-paper`: final factual and style pass.

The high-level skill tells the agent when to use the step skills. Step skills keep prompts focused.

## AI Backends

V1 requires both Codex CLI and Claude CLI to be installed.

Default role split:

- Codex analyzes experiments.
- Codex fact-checks and reviews factual claims.
- Claude writes human-facing prose for ranking summaries, paper sections, and style cleanup.

Role assignment is configurable per run. The default remains Codex for analysis/review and Claude
for prose.

Codex invokes Claude through the local OS as a subprocess via the `paperium` helper. Claude does
not run inside Codex; it is a separate CLI worker process. The same backend interface launches
Codex and Claude workers with prompt stdin, controlled working directory, captured output, and
recorded status.

## Context Boundaries

Experiment workers receive narrow read-only context by default:

- the selected experiment folder;
- the parent question `README.md`.

Repository text is evidence, not task instructions. This includes target-repo `AGENTS.md`,
README files, `SKILL.md`, logs, comments, metadata, and generated outputs. Worker instructions
come only from Paperium skills and worker prompts.

If a worker needs sibling experiments, shared source files, or other paths outside the default
boundary, it must request them. The main session asks the user before expanding context. If the
user denies expansion and the worker cannot proceed honestly, the experiment stops with a visible
failure or limitation.

## Experiment Analysis Flow

V1 supports selected experiments through manual paths and an interactive menu. Automatic
analyze-all is out of scope for V1.

## Experiment Selection Contract

An experiment is any selected directory that contains at least one of:

- `outputs/`;
- `README.md`;
- `metadata.json`;
- a run/config artifact such as `docker-compose.yml`, `docker-stack.yml`, `pyproject.toml`, or
  executable runner scripts.

Manual paths are resolved relative to the target repo root and must stay inside that repo. A
missing path or file path is a hard failure. If a selected directory has no usable run artifacts
for fact-checking, analysis may produce notes, but the experiment cannot pass the fact-check gate
until the user supplies or allows relevant artifacts.

The interactive menu discovers likely experiment directories under `questions/**/experiments/*`
first. It may also include explicitly configured experiment roots in a later version, but V1 does
not need automatic whole-repo guessing beyond the questions/experiments convention.

Parent question context is resolved by walking upward from the experiment path until a parent
directory with `README.md` is found, preferring the nearest ancestor whose path is under
`questions/`. If no parent question README is found, the experiment may still be analyzed, but the
state records `question_readme: null`, and the worker prompt must say that no question README was
available. A missing or stale question README is not a hard failure because it is context only, not
ground truth.

For each selected experiment:

1. `paperium` starts an analysis worker.
2. The worker inspects the experiment folder and parent question README.
3. The worker writes `<experiment>/.paperium/analysis.md`.
4. A separate Codex fact-check worker reviews the analysis.
5. Approved analyses become eligible for ranking and paper writing.

`analysis.md` is readable and free-form. It should explain:

- what was tested;
- what happened;
- important numbers/results;
- caveats and limitations;
- whether the experiment is useful for the paper.

It is not a rigid JSON schema.

## Fact-Check Flow

Fact-checking is a hard gate.

The fact-checker's ground truth is the experiment's run artifacts, especially `outputs/` and other
machine-produced run artifacts. Existing experiment READMEs are context only, not ground truth.

Any unsupported number or factual claim is a hard failure. Claims that only appear in README prose
but cannot be supported by run artifacts must be flagged.

Repair loop:

1. If fact-check fails, the analyzer receives the findings and rewrites `analysis.md`.
2. Fact-check runs again.
3. One more repair attempt is allowed.
4. After two repair attempts, the experiment stops and requires human review.

Only fact-check-approved experiment notes can influence ranking or `PAPER.md`.

## Ranking And Question Focus

After approved experiment notes exist, Claude proposes a ranking/inclusion artifact under the
target repo root `.paperium/`.

The ranking artifact has a small required structure:

- **include**: experiments that should influence the paper;
- **exclude**: experiments that should not be used, with reasons;
- **defer**: experiments that may matter but need human judgment or more work.

Every selected fact-check-approved experiment must appear in exactly one of those buckets. V1 must
not silently omit an approved experiment from the ranking artifact.

V1 then creates a question-focus mapping:

- original question folder;
- approved included experiments;
- actual answer focus for the paper.

V1 does not rewrite question READMEs and does not formally rename research questions. The mapping
exists because experiments can drift away from the original folder question, and the paper should
answer what the approved evidence supports.

The user approves or edits ranking and focus before writing begins.

## Writing Flow

V1 writes a short technical report, not a scientific-style paper and not an artifact dump.

The workflow:

1. Build an outline from approved ranking and question-focus mapping.
2. Write one section at a time.
3. Ask the user to approve, edit, skip, or regenerate that section.
4. Continue only after approval.
5. After all sections are approved, write top-level target repo `PAPER.md`.

The paper should explain only:

- the answer;
- important evidence;
- practical implication;
- caveats and limits;
- remaining uncertainty.

Detailed run mechanics belong in experiment artifacts or generated `.paperium/analysis.md`, not
in `PAPER.md`.

Claude is the default section prose writer. Codex is the default factual reviewer for generated
paper sections. A paper section that contains a factual claim not traceable to approved experiment
notes and underlying run artifacts must be revised before approval.

## State And Resume

The target repo root `.paperium/state.json` records:

- selected experiments;
- current phase;
- generated artifact paths;
- worker statuses;
- approved analyses;
- ranking approval;
- question-focus approval;
- section approval state;
- final write state.

The state file is versioned. V1 uses this minimum shape:

```json
{
  "schema_version": 1,
  "phase": "selecting|analyzing|fact_checking|ranking|mapping|writing|reviewing|complete|failed",
  "selected_experiments": [
    {
      "path": "questions/q001/experiments/exp001",
      "question_readme": "questions/q001/README.md",
      "analysis_path": "questions/q001/experiments/exp001/.paperium/analysis.md",
      "status": "pending|running|approved|failed|needs_human_review|skipped",
      "repair_attempts": 0
    }
  ],
  "workers": [
    {
      "id": "worker-id",
      "backend": "codex|claude",
      "role": "analyze|fact_check|rank|write|review",
      "status": "pending|running|succeeded|failed|cancelled|timed_out",
      "experiment_path": "questions/q001/experiments/exp001",
      "started_at": "ISO-8601 timestamp or null",
      "ended_at": "ISO-8601 timestamp or null",
      "stdout_path": ".paperium/workers/worker-id/stdout.txt",
      "stderr_path": ".paperium/workers/worker-id/stderr.txt",
      "output_path": ".paperium/workers/worker-id/output.md",
      "allowed_paths": [
        "questions/q001/experiments/exp001",
        "questions/q001/README.md"
      ],
      "approved_expansions": [],
      "failure_reason": null
    }
  ],
  "ranking": {
    "path": ".paperium/ranking.md",
    "approved": false
  },
  "question_focus": {
    "path": ".paperium/question-focus.md",
    "approved": false
  },
  "sections": [],
  "final_write": {
    "paper_path": "PAPER.md",
    "status": "not_started|ready|written|failed",
    "written_at": null
  }
}
```

Section records use this minimum shape:

```json
{
  "id": "q001-answer",
  "title": "Q001 Answer",
  "path": ".paperium/sections/q001-answer.md",
  "status": "not_started|drafted|review_failed|approved|skipped",
  "factual_review_status": "not_started|passed|failed"
}
```

`final_write.status` may become `ready` only after every non-skipped section is approved and every
required factual review has passed. `PAPER.md` may be written only from the `ready` state.

On resume, `paperium` shows what is complete, what failed, and what needs user action.

Normal runs overwrite or update selected generated artifacts. They never delete stale generated
files automatically.

## Worker Contract

Workers are bounded subprocesses launched by `paperium`.

Each worker has:

- backend: `codex` or `claude`;
- role: `analyze`, `fact_check`, `rank`, `write`, or `review`;
- prompt stdin supplied by `paperium`;
- working directory set to the target repo root;
- explicit allowed context listed in the prompt;
- captured stdout and stderr under `.paperium/workers/<worker-id>/`;
- timeout;
- status recorded in `.paperium/state.json`.

V1 records context boundaries for each worker. Boundary enforcement is prompt-and-audit based:
the worker runs from the target repo root for practical CLI compatibility, but the prompt lists
allowed paths and requires the worker to request expansion before relying on anything else.
Approved expansions are recorded in worker state. Outputs that rely on unapproved paths fail
review.

Default concurrency is two workers. The user may override it, but V1 must keep concurrency bounded
and visible in the Rich progress UI.

Timeout, cancellation, non-zero exit, missing expected output, or fact-check rejection records a
failed worker result. Failed workers do not silently disappear from state. On resume, `paperium`
does not automatically restart failed workers without an explicit user action or workflow step.

Fact-check and factual-review workers write a small structured result, not a large evidence dump:

```json
{
  "status": "passed|failed",
  "findings": [
    {
      "severity": "error|warning",
      "claim": "short claim text",
      "reason": "why it is unsupported, wrong, or risky",
      "artifact_path": "relative/path/or/null"
    }
  ]
}
```

Repair loops and approval gates use only this pass/fail status plus findings. Detailed evidence
stays in run artifacts and generated analysis notes.

## Error Handling

Hard failures are visible and recoverable:

- Codex CLI missing;
- Claude CLI missing;
- selected experiment path missing;
- selected experiment has no usable run artifacts for fact-checking;
- fact-check still fails after two repair attempts;
- user denies needed context expansion and the worker cannot proceed honestly;
- paper section cannot pass factual review.

Failures are recorded in `.paperium/state.json` and surfaced in Rich progress/status output.

## Testing Requirements

V1 tests should cover:

- CLI/backend detection for Codex and Claude;
- manual and interactive experiment selection;
- `.gitignore` update for generated `.paperium` files;
- root `.paperium/state.json` creation and resume behavior;
- per-experiment `.paperium/analysis.md` path handling;
- worker command construction for Codex and Claude;
- context-boundary prompts and user-approved expansion requests;
- README-is-not-ground-truth prompt rule;
- fact-check repair limit;
- no ranking use before fact-check approval;
- no `PAPER.md` write before section approvals;
- no automatic deletion of generated files.

## Non-Goals

V1 does not:

- extend the old `paperctl` evidence-packet paper-generation model;
- edit experiment READMEs;
- require structured JSON experiment analysis;
- automatically analyze every experiment;
- silently include, exclude, or delete experiments;
- publish detailed evidence inventories into the paper;
- solve long-term packaging or MCP integration;
- implement a fully autonomous end-to-end writer without user approval gates.
