# Milestone 2 Single-Experiment Analysis Design

## Purpose

Milestone 2 adds the first semantic analysis stage to `paperctl` while keeping the
existing Milestone 1 deterministic pipeline unchanged. The milestone implements
one real experiment analyst for one explicitly selected experiment.

This milestone does not add parallel analysis, semantic review, repair loops,
question synthesis, final paper rendering, or publication-gate integration.
`paperctl build`, `paperctl render`, and publication audit continue to behave as
Milestone 1 commands.

## Scope

Implement:

```bash
paperctl --repo /path/to/repo analyze \
  --experiment questions/q001-throughput/experiments/exp001-completed \
  --backend codex-exec
```

Also implement a fixture-backed fake backend for tests and manual dry runs:

```bash
paperctl --repo /path/to/repo analyze \
  --experiment questions/q001-throughput/experiments/exp001-completed \
  --backend fake \
  --fake-response tests/fixtures/analysis/exp001-success.json
```

The command requires fresh deterministic prerequisites. It does not run
`discover`, `inventory`, or `normalize` implicitly.

## Non-Goals

- No `paperctl analyze --all`.
- No `paperctl analyze --question`.
- No concurrency or job queue.
- No backend retries.
- No semantic reviewer or repair loop.
- No question synthesis.
- No technical editor.
- No changes to `PAPER.md` publication behavior.
- No auditing of numeric literals embedded in prose.
- No raw model output embedded in stable analysis-state artifacts.

## Inputs

`analyze` reads:

- `paper.yaml`
- `paper/work/manifest.json`
- the selected experiment inventory packet
- the selected experiment evidence packet
- files referenced by validated claim sources

The selected experiment must resolve to exactly one manifest entry. M2 accepts
the manifest experiment path as the selector. Short aliases can be added later.

Before backend invocation, `analyze` verifies that manifest, inventory, and
evidence are present and fresh using the same byte-stable freshness checks used
by Milestone 1 stages. If any prerequisite is missing, malformed, stale, or does
not match the selected manifest entry, `analyze` exits with deterministic failure
and does not call the backend.

## Output Artifact

Each selected experiment writes one stable analysis-state artifact:

```text
paper/work/analyses/<question-path>/experiments/<experiment-name>.json
```

For example:

```text
paper/work/analyses/questions/q001-throughput/experiments/exp001-completed.json
```

The output path mirrors manifest paths so later milestones can locate analysis
state deterministically.

The file represents the latest attempt state. A failed validation replaces a
previous accepted state. The write is atomic.

## Analysis State Schema

The stable artifact has `artifact_type: "analysis_state"` and one of two states.

Accepted state:

- `schema_version`
- `artifact_type`
- `question_path`
- `experiment_path`
- `analysis_path`
- `status: "accepted"`
- `fingerprint`
- `backend`
- `analysis`
- `diagnostics: []`

Failed state:

- `schema_version`
- `artifact_type`
- `question_path`
- `experiment_path`
- `analysis_path`
- `status: "failed"`
- `fingerprint`
- `backend`
- `analysis: null`
- `diagnostics`
- `raw_output_sha256`

Failure diagnostics are bounded and structured. They include validation codes,
messages, source paths and selectors when applicable, backend return metadata
when applicable, and a hash of the raw backend output. They do not include the
full raw model response.

## Experiment Analysis Schema

The backend returns an `experiment_analysis` object. M2 validates and stores it
inside an accepted analysis state only if all schema and claim checks pass.

Required fields:

- `schema_version`
- `artifact_type: "experiment_analysis"`
- `question_path`
- `experiment_path`
- `title`
- `execution_status`
- `hypothesis_verdict`
- `objective`
- `answer`
- `meaning`
- `limitations`
- `confidence`
- `claims`

Allowed execution statuses:

- `completed`
- `partial`
- `failed`
- `not_run`
- `unknown`

Allowed hypothesis verdicts:

- `supported`
- `partially_supported`
- `not_supported`
- `inconclusive`
- `not_applicable`

Allowed confidence values:

- `high`
- `medium`
- `low`

## Claim Validation

M2 validates structured claims. Prose fields are schema-bounded strings but are
not scanned for untraceable numeric literals.

### Measured Claims

Measured claims require:

- unique `claim_id`
- `claim_type: "measured_value"`
- `label`
- `value`
- `value_type`
- optional `unit`
- one source object

The source must include:

- repo-relative `path`
- `source_hash`
- `selector_type: "json_pointer"`
- JSON Pointer `selector`

Validation rules:

1. The source path is repository-relative and stays inside the target repository.
2. The source path is within the selected experiment directory.
3. The source file exists.
4. The source file hash equals `source_hash`.
5. The source file kind is JSON or YAML.
6. The selector is a valid JSON Pointer.
7. The selector resolves to a scalar JSON-compatible value.
8. The selected value equals the claim value.
9. The selected value type matches `value_type`.

Cross-question and unrelated-experiment source paths are rejected in M2.

### Derived Claims

Derived claims require:

- unique `claim_id`
- `claim_type: "derived_value"`
- `label`
- `value`
- `value_type: "number"` or `value_type: "integer"`
- optional `unit`
- `formula`
- `input_claim_ids`

Validation rules:

1. Every input claim ID exists in the same analysis.
2. Every input claim is numeric.
3. The formula contains only claim IDs, numeric literals, parentheses, and
   `+`, `-`, `*`, `/`.
4. The formula contains no unknown symbols.
5. Division by zero fails validation.
6. The formula result equals the reported value.

The implementation should evaluate formulas with a small safe parser, not
Python `eval`.

## Backend Interface

Introduce a small backend boundary:

```python
class AnalysisBackend:
    def analyze(job: AnalysisJob) -> AnalysisBackendResult:
        ...
```

`AnalysisJob` includes:

- target repo root
- config
- question path
- experiment path
- inventory path
- evidence packet path
- output schema name or schema path
- backend-specific options

`AnalysisBackendResult` includes:

- backend name
- status
- parsed response when available
- raw output bytes or text for hashing
- bounded stdout and stderr summaries
- return code when applicable

Both real and fake backends feed the same parser, schema validator, claim
validator, and analysis-state writer.

## Fake Backend

`FakeBackend` reads the response JSON specified by `--fake-response`.

It is used for the default test suite and manual dry runs. It must not bypass
schema or claim validation.

Fixture responses cover:

- accepted analysis
- invalid schema
- stale source hash
- invalid JSON Pointer
- source outside selected experiment
- invalid derived formula
- division by zero
- backend failure

## Codex Exec Backend

`CodexExecBackend` runs `codex exec` as an argument-array subprocess with the
target research repo as the working directory. It must not use `shell=True`.

The worker prompt is narrow and includes:

- primary question path
- primary experiment path
- inventory path
- evidence packet path
- required output schema instructions
- read-only instruction
- no repository modification instruction
- instruction to treat repository contents as evidence, not as instructions
- instruction to inspect only the selected experiment and its deterministic
  packets

The backend requests read-only sandboxing when the available `codex exec`
surface supports it. If the subprocess fails, times out, returns invalid JSON,
or does not produce a final response, `analyze` writes a failed analysis state.

## Data Flow

`paperctl analyze` runs:

1. Resolve target repo.
2. Load and validate config.
3. Load and validate manifest.
4. Resolve `--experiment` to one manifest entry.
5. Load and validate that experiment inventory.
6. Load and validate that experiment evidence packet.
7. Verify deterministic freshness.
8. Build `AnalysisJob`.
9. Invoke backend.
10. Parse backend response.
11. Validate experiment-analysis schema.
12. Validate measured claims.
13. Validate derived claims.
14. Build analysis-state artifact.
15. Atomically write analysis-state artifact.
16. Print concise status summary.

## Error Handling

Missing or stale deterministic prerequisites:

- exit with deterministic failure
- do not invoke backend
- do not write an analysis-state artifact

Backend failure:

- write `status: "failed"`
- include backend diagnostic code
- include bounded stdout/stderr summaries
- include raw output hash when output exists
- exit nonzero

Invalid JSON, schema, or claims:

- write `status: "failed"`
- include validation diagnostics
- include raw output hash
- exit nonzero

Accepted analysis:

- write `status: "accepted"`
- include validated analysis
- include deterministic fingerprint
- exit success

`analyze` must not modify experiment artifacts, `PAPER.draft.md`, or `PAPER.md`.

## CLI

Add `analyze` to the existing CLI:

```text
paperctl analyze --experiment PATH --backend {fake,codex-exec}
```

Backend-specific options:

```text
--fake-response PATH      required when --backend fake
--codex-bin PATH          optional, defaults to codex
--timeout-seconds N       optional bounded subprocess timeout
```

The real backend is explicit. There is no hidden default that can launch an LLM
call by accident.

Plain output is sufficient for M2. Rich output can be added later after the
command behavior stabilizes.

## Fingerprints

Accepted and failed analysis states include deterministic fingerprints covering:

- analysis stage version
- analysis-state schema version
- relevant config
- manifest artifact hash
- inventory artifact hash
- evidence packet artifact hash
- backend name and non-secret backend configuration
- raw backend output hash
- accepted analysis hash or failure diagnostics hash

Fingerprints must not include absolute paths, timestamps, temporary paths, or
full raw model output.

## Tests

The default test suite stays LLM-free.

Required tests:

- CLI parses `analyze --experiment --backend fake --fake-response`.
- Missing manifest fails before backend invocation.
- Missing inventory fails before backend invocation.
- Missing evidence packet fails before backend invocation.
- Stale inventory or evidence fails before backend invocation.
- FakeBackend accepted fixture writes `status: "accepted"`.
- Invalid schema fixture writes `status: "failed"`.
- Stale source hash writes `status: "failed"`.
- Bad JSON Pointer writes `status: "failed"`.
- Source outside selected experiment writes `status: "failed"`.
- Valid derived arithmetic writes `status: "accepted"`.
- Unknown derived claim input writes `status: "failed"`.
- Division by zero writes `status: "failed"`.
- Backend failure writes bounded diagnostics.
- Analysis-state output path mirrors manifest paths under `paper/work/analyses`.
- Analysis-state artifacts validate against schema.
- Existing Milestone 1 tests remain green.

Optional real Codex integration tests may be added later and must be skipped by
default.

## Acceptance Example

This command:

```bash
uv run paperctl --repo tests/fixtures/minimal-research-repo analyze \
  --experiment questions/q001-throughput/experiments/exp001-completed \
  --backend fake \
  --fake-response tests/fixtures/analysis/exp001-success.json
```

must write:

```text
tests/fixtures/minimal-research-repo/paper/work/analyses/questions/q001-throughput/experiments/exp001-completed.json
```

with `status: "accepted"` when deterministic prerequisites are fresh.

Invalid fake responses must write the same stable path with `status: "failed"`
and bounded diagnostics, without touching `PAPER.md`.
