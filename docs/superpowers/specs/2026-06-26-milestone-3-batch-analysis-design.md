# Milestone 3 Batch Analysis Design

## Status

Approved for design by user. Implementation planning must happen separately after this spec passes review.

## Goal

Milestone 3 adds bounded batch analysis on top of the Milestone 2 single-experiment analyzer. A user can analyze selected experiments explicitly or choose them interactively from the CLI. The milestone does not synthesize questions, render semantic analysis into `PAPER.md`, add `analyze-all`, or write a batch-level state artifact.

## Non-Goals

- Do not redesign Milestone 2 analysis validation, fingerprints, schemas, or Codex backend rules.
- Do not add question synthesis, semantic review, technical editing, or publishable rendering.
- Do not add `analyze-all` in M3, though the batch runner should leave a clear path for it later.
- Do not add `--keep-going` in M3.
- Do not write a separate batch summary artifact.
- Do not introduce a new menu dependency unless a later review explicitly approves it.

## Approach

Extend the existing `paperctl analyze` command into a one-or-many experiment command.

Supported forms:

```bash
paperctl --repo /path/to/target analyze EXPERIMENT_PATH [EXPERIMENT_PATH ...]
paperctl --repo /path/to/target analyze --experiments-menu
```

Options:

```bash
--jobs N              default 2; bounded parallel experiment analysis
--force               re-run even if accepted analysis is up to date
--timeout-seconds N   existing per-experiment timeout behavior
--backend NAME        existing backend selection behavior
```

Rules:

- Explicit experiment paths and `--experiments-menu` are mutually exclusive.
- At least one explicit experiment path is required unless `--experiments-menu` is used.
- A single explicit experiment path remains the compatible Milestone 2 case.
- `--experiments-menu` requires an interactive TTY and fails clearly in non-TTY contexts.
- `--repo` scopes manifest discovery, evidence lookup, cache checks, and analysis output paths to the target research repository. If `--repo` is omitted, `paperctl` resolves the current Git root using the existing command behavior.

## Selection

Explicit experiment paths are repository-relative paths resolved against the discovered manifest for the selected target repo. A path that exists in the target repository but is not a manifest experiment is rejected before backend invocation. Invalid paths fail preflight rather than being guessed or normalized implicitly.

The interactive menu loads the current manifest and displays experiments grouped by question. It shows every discovered experiment, including blocked or non-candidate entries, but only runnable experiments may be selected.

Runnable means the normalized evidence packet has:

```json
{"preanalysis_disposition": "analysis_candidate"}
```

Disabled rows include the refusal reason, such as blocked, needs human review, missing evidence, missing normalized packet, or stale packet.

The first implementation target is a Rich plus standard-library checkbox-style terminal picker. If Rich cannot support a clean checkbox interaction without a new dependency, M3 should provide a small internal TTY picker rather than adding a dependency.

Before scheduling begins, M3 validates the entire selected set. If any explicit path is invalid, non-manifest, or non-runnable, the command fails before launching backend work for any experiment. The menu prevents disabled rows from being selected, so menu-based selections should already contain runnable experiments only.

## Scheduling

Selected experiments flow through one batch runner regardless of whether they came from explicit paths or the menu.

The batch runner:

- Starts only after selection validation succeeds for the full selected set.
- Runs up to `--jobs` experiments concurrently.
- Defaults to `--jobs 2`.
- Supports `--jobs 1` for sequential behavior.
- Applies skip decisions before launching backend work.
- Uses fail-fast behavior only.

Fail-fast means that when any non-skipped experiment fails, the runner stops launching new experiments. Already-running experiments may finish. They should only be cancelled if the existing backend wrapper can do so cleanly without losing per-experiment diagnostics.

Experiments not launched because of fail-fast are reported as `not_started`.

## Per-Experiment State

Each launched experiment uses the existing Milestone 2 pipeline:

1. Load normalized evidence.
2. Run preflight.
3. Invoke the configured backend if preflight passes.
4. Validate the returned analysis.
5. Write latest attempt state to:

```text
paper/work/analyses/<experiment-path>.json
```

Per-experiment analysis files remain the source of truth. M3 does not create a batch artifact.

## Cache And Force Behavior

By default, an accepted analysis artifact is skipped when its fingerprint still matches current inputs, including evidence, question context, prompt/schema hashes, and validator versions defined by Milestone 2.

`--force` ignores accepted up-to-date state and re-runs selected experiments.

Failed, incomplete, missing, or stale analysis artifacts are re-run by default.

Skipped experiments are still reported in CLI output with reason and analysis path.

## Output

For an interactive TTY, M3 shows a live Rich progress view with one row per selected experiment. Each row includes:

- experiment path
- status: `queued`, `skipped`, `running`, `accepted`, `failed`, `blocked`, or `not_started`
- analysis path when known
- compact diagnostic or skip reason
- token usage after backend completion when available

For non-TTY output, M3 falls back to deterministic line-oriented logs.

Final command output includes aggregate counts for selected, skipped, accepted, failed, blocked, and not started experiments. These counts are terminal output only and are not persisted as a batch artifact.

Exit status:

- Exit `0` when every selected experiment is accepted or skipped as accepted/up-to-date.
- Exit nonzero when any selected experiment fails, is blocked by preflight, is invalid, cannot be selected, or is not started because fail-fast triggered.

## Error Handling

All Milestone 2 preflight and validation failures remain per-experiment diagnostics. M3 adds orchestration-level diagnostics only for selection, menu, concurrency, and fail-fast behavior.

Backend invocation must never occur for:

- invalid explicit paths
- non-manifest paths
- disabled menu rows
- normalized evidence whose preanalysis disposition is not `analysis_candidate`
- accepted up-to-date artifacts unless `--force` is passed

For explicit path selection, any invalid, non-manifest, or non-runnable experiment aborts the whole batch before backend invocation. Cache skips do not abort the batch.

## Test Plan

Add tests for:

- `analyze exp1 exp2` accepts multiple explicit manifest experiment paths.
- Single-path `analyze` remains compatible with Milestone 2 behavior.
- Explicit paths and `--experiments-menu` are mutually exclusive.
- Missing explicit paths without `--experiments-menu` fail clearly.
- Invalid or non-manifest experiment paths fail before backend invocation.
- Invalid, non-manifest, blocked, and non-candidate explicit selections abort the full batch before backend invocation.
- `--repo` scopes manifest discovery, evidence lookup, cache checks, and analysis output paths.
- The menu requires a TTY.
- The menu shows disabled non-runnable experiments with reasons.
- Accepted up-to-date analyses are skipped by default.
- `--force` re-runs accepted up-to-date analyses.
- Failed, incomplete, missing, and stale analyses are re-run by default.
- `--jobs` bounds concurrency, including `--jobs 1`.
- Fail-fast stops launching new work after the first failure.
- Not-launched experiments are reported as `not_started`.
- Rich TTY output includes status, analysis path, and token usage when present.
- Non-TTY output is deterministic and includes status, analysis path, and token usage when present.
- No batch artifact is written.

Live Codex invocation is not required for M3 orchestration tests. Use fakes around the existing Milestone 2 single-experiment analyzer boundary.

## Future Work

Later milestones may add:

- `paperctl analyze-all`
- `--keep-going`
- selector expressions by question, tag, status, or disposition
- persisted batch summaries
- question synthesis from accepted analysis states
- semantic rendering into `PAPER.md`
