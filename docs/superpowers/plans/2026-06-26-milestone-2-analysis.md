# Milestone 2 Single-Experiment Analysis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `paperctl analyze --experiment ...` for one validated semantic experiment analysis using a fake backend for tests and an explicit `codex-exec` backend for real runs.

**Architecture:** Keep Milestone 1 unchanged. Add a separate analysis stage with schemas, preflight loading, response parsing, claim validation, state writing, backend adapters, and CLI wiring. The analysis artifact is latest-attempt state at `paper/work/analyses/<experiment-path>.json`.

**Tech Stack:** Python 3.11, argparse, jsonschema, existing `paperctl` JSON/fingerprint/path helpers, subprocess-based `codex exec`, pytest, Ruff.

---

## File Structure

- Create `src/paperctl/schemas/experiment-analysis.schema.json`: schema for model backend responses.
- Create `src/paperctl/schemas/analysis-state.schema.json`: schema for generated analysis-state artifacts.
- Create `src/paperctl/formula.py`: safe Decimal arithmetic parser/evaluator for derived claims.
- Create `src/paperctl/analysis_validation.py`: schema-adjacent validation for execution status, numeric prose, measured claims, and derived claims.
- Create `src/paperctl/analysis_backends.py`: backend protocol, fake backend, Codex exec backend, backend capability checks, and shared raw-response result shape.
- Create `src/paperctl/analysis_prompt.py`: deterministic prompt builder, prompt template version, and prompt-injection boundary text for backend workers.
- Create `src/paperctl/analysis.py`: single-experiment orchestration, preflight loading/freshness, parser, fingerprinting, state writing, and result dataclasses.
- Modify `src/paperctl/cli.py`: add `analyze` subcommand and exit-code mapping.
- Modify `src/paperctl/_support/redaction.py` only if existing redaction helpers cannot redact free-form diagnostics without duplication.
- Add `tests/test_analysis.py`: end-to-end analysis command/API tests.
- Add `tests/test_analysis_validation.py`: focused claim, formula, and numeric-prose validation tests.
- Add `tests/test_analysis_backends.py`: fake backend and Codex command construction/capability tests.
- Add `tests/fixtures/analysis/*.json`: fake backend response fixtures.

---

## Chunk 1: Schemas And Fixtures

### Task 1: Add Experiment Analysis Schema

**Files:**
- Create: `src/paperctl/schemas/experiment-analysis.schema.json`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Write schema tests first**

Add tests that validate a minimal accepted `experiment_analysis`, reject unknown properties, reject bad `claim_id`, reject unsupported `execution_status`, reject unbounded string fields, and reject a derived claim with empty `input_claim_ids`.

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_schemas.py -q
```

Expected: fail because `experiment-analysis.schema.json` does not exist.

- [ ] **Step 2: Implement schema**

Create `experiment-analysis.schema.json` with:

- `schema_version: 1`
- `artifact_type: "experiment_analysis"`
- M1 execution status enum: `completed`, `failed`, `incomplete`, `unknown`
- verdict and confidence enums from the spec
- field bounds from the spec
- `measured_value` and `derived_value` claim variants
- `additionalProperties: false`
- `claim_id` pattern `^[A-Za-z_][A-Za-z0-9_]*$`
- source path/hash/selector bounds

- [ ] **Step 3: Verify schema tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_schemas.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/paperctl/schemas/experiment-analysis.schema.json tests/test_schemas.py
git commit -m "Add experiment analysis schema"
```

### Task 2: Add Analysis State Schema

**Files:**
- Create: `src/paperctl/schemas/analysis-state.schema.json`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Write schema tests first**

Add tests for:

- accepted state with `analysis` and empty `diagnostics`
- failed state with `analysis: null`, non-empty diagnostics, and nullable `raw_output_sha256`
- backend metadata bounds
- diagnostic message/detail bounds
- rejection of unknown properties

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_schemas.py -q
```

Expected: fail because `analysis-state.schema.json` does not exist.

- [ ] **Step 2: Implement schema**

Create `analysis-state.schema.json` with accepted/failed conditional requirements. Reuse compatible local `$defs` for hashes and repo-relative paths. Reference the embedded `experiment_analysis` shape by duplicating or locally defining the object; do not rely on cross-schema `$ref` unless existing schema loader supports it.

- [ ] **Step 3: Verify schema tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_schemas.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/paperctl/schemas/analysis-state.schema.json tests/test_schemas.py
git commit -m "Add analysis state schema"
```

### Task 3: Add Fake Analysis Response Fixtures

**Files:**
- Create: `tests/fixtures/analysis/exp001-success.json`
- Create: `tests/fixtures/analysis/invalid-schema.json`
- Create: `tests/fixtures/analysis/no-measured-claim.json`
- Create: `tests/fixtures/analysis/bad-selector.json`
- Create: `tests/fixtures/analysis/claim-not-in-evidence.json`
- Create: `tests/fixtures/analysis/bad-derived-literal.json`
- Create: `tests/fixtures/analysis/rounded-division.json`
- Create: `tests/fixtures/analysis/numeric-prose.json`

- [ ] **Step 1: Create fixtures matching existing minimal repo evidence**

Use `questions/q001-throughput/experiments/exp001-completed/outputs/experiment_report.json` as the success measured source. The success fixture should include at least one measured claim matching an evidence packet canonical fact, and optionally one exact derived claim using only `0`, `1`, or `100`.

- [ ] **Step 2: Run schema validation**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_schemas.py -q
```

Expected: success fixtures validate where intended; intentionally invalid fixtures are tested later by validation tests.

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/analysis
git commit -m "Add analysis response fixtures"
```

---

## Chunk 2: Formula And Claim Validation

### Task 4: Implement Safe Formula Evaluator

**Files:**
- Create: `src/paperctl/formula.py`
- Create: `tests/test_analysis_validation.py`

- [ ] **Step 1: Write formula tests first**

Cover:

- `throughput / baseline` exact division when terminating
- `(a * 100) / b`
- allowed literals `0`, `1`, `100`
- reject literal `2`
- reject unknown symbol
- reject unused `input_claim_ids`
- reject unlisted claim reference
- reject division by zero
- reject rounded `1 / 3` reported as `0.333`

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_validation.py -q
```

Expected: fail because `paperctl.formula` does not exist.

- [ ] **Step 2: Implement evaluator**

Use Python `ast.parse(..., mode="eval")` and allow only:

- `ast.Expression`
- `ast.BinOp`
- `ast.Add`, `ast.Sub`, `ast.Mult`, `ast.Div`
- `ast.Name`
- `ast.Constant` for numeric literals `0`, `1`, `100`

Convert numeric values to `Decimal(str(value))`. Return a `Decimal` result or raise a local `FormulaError` with stable diagnostic codes.

- [ ] **Step 3: Verify formula tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_validation.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add src/paperctl/formula.py tests/test_analysis_validation.py
git commit -m "Add safe analysis formula evaluator"
```

### Task 5: Implement Analysis Claim Validator

**Files:**
- Create: `src/paperctl/analysis_validation.py`
- Modify: `tests/test_analysis_validation.py`

- [ ] **Step 1: Write validation tests first**

Cover:

- accepted measured claim corresponds to evidence `canonical_facts`
- accepted measured claim corresponds to evidence `observed_values`
- reject no measured claims
- reject measured claim not in evidence packet
- reject source outside selected experiment
- reject stale hash
- reject bad selector
- reject type mismatch
- reject deterministic `execution_status` mismatch
- accept `unknown` evidence execution status with any schema-valid analysis status
- reject standalone numeric prose in `title`, `objective`, `answer`, `meaning`, and `limitations`
- allow identifier digits such as `exp014`

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_validation.py -q
```

Expected: fail because validator functions do not exist.

- [ ] **Step 2: Implement validator API**

Add:

```python
ANALYSIS_VALIDATION_VERSION = 1

class AnalysisValidationError(ValueError): ...

def validate_analysis_claims(
    *,
    repo: Path,
    manifest_entry: dict[str, Any],
    evidence_packet: dict[str, Any],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    ...
```

Return an empty diagnostics list on success; return stable diagnostic objects on failures. Keep this module free of writing side effects.

- [ ] **Step 3: Implement evidence-bound measured validation**

Build a set of claimable evidence signatures from `canonical_facts` and `observed_values` whose sources are JSON Pointer sources and whose adapter is `json` or `yaml`. A measured claim is valid only when path, hash, selector type, selector, value, value type, and unit match one of those signatures. Reopen the raw source only to verify current hash, selector resolution, and value.

- [ ] **Step 4: Implement numeric prose validation**

Reject standalone numeric tokens with a conservative regex that does not match digits embedded in identifiers:

```python
r"(?<![A-Za-z0-9_])-?\\d+(?:\\.\\d+)?%?(?![A-Za-z0-9_])"
```

Apply to `title`, `objective`, `answer`, `meaning`, and each limitation.

- [ ] **Step 5: Verify validation tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_validation.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/paperctl/analysis_validation.py tests/test_analysis_validation.py
git commit -m "Validate experiment analysis claims"
```

---

## Chunk 3: Backends And Response Parsing

### Task 6: Implement Backend Protocol And Fake Backend

**Files:**
- Create: `src/paperctl/analysis_backends.py`
- Create: `tests/test_analysis_backends.py`

- [ ] **Step 1: Write fake backend tests first**

Cover:

- fake response path resolves relative to current working directory
- fake backend returns raw response bytes and metadata, not parsed JSON
- missing fake response is a backend failure result

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_backends.py -q
```

Expected: fail because backend module does not exist.

- [ ] **Step 2: Implement backend result dataclasses**

Add:

```python
@dataclass(frozen=True)
class AnalysisBackendResult:
    backend_name: str
    status: str
    raw_response: bytes | None
    return_code: int | None
    stdout: str | None
    stderr: str | None
```

Use status values `completed`, `failed`, `timed_out`.

- [ ] **Step 3: Implement FakeBackend**

Read `--fake-response` bytes. On success return `completed`; on `OSError` return `failed` with bounded stderr.

- [ ] **Step 4: Verify fake backend tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_backends.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/paperctl/analysis_backends.py tests/test_analysis_backends.py
git commit -m "Add analysis fake backend"
```

### Task 7: Implement Codex Exec Command Construction And Capability Checks

**Files:**
- Modify: `src/paperctl/analysis_backends.py`
- Modify: `tests/test_analysis_backends.py`

- [ ] **Step 1: Write Codex command tests first**

Mock subprocess/help behavior and assert:

- command includes `--sandbox read-only`
- command includes `--ask-for-approval never`
- command includes `--output-schema <experiment-analysis.schema.json>`
- command includes `--output-last-message <tmp>`
- stdin prompt transport uses trailing `-` unless help explicitly supports `--file`
- missing `--output-schema` support fails before invocation
- missing read-only sandbox support fails before invocation
- missing no-approval support fails before invocation

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_backends.py -q
```

Expected: fail.

- [ ] **Step 2: Implement capability probing**

Add a helper that runs `<codex-bin> exec --help` and checks for:

- `--output-schema`
- `--sandbox`
- `read-only` or compatible read-only sandbox wording
- `--ask-for-approval`
- `never`

Return a failed backend result or raise a backend setup error before invocation if unavailable.

- [ ] **Step 3: Implement CodexExecBackend**

Use `subprocess.run` with argument arrays, `cwd=repo`, `input=prompt`, `text=True`, bounded timeout. Read the final-message file as bytes. Never parse stdout/stderr as analysis.

- [ ] **Step 4: Verify backend tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis_backends.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/paperctl/analysis_backends.py tests/test_analysis_backends.py
git commit -m "Add codex exec analysis backend"
```

---

## Chunk 4: Analysis Orchestration And State Writing

### Task 8: Implement Analysis Preflight And State Builder

**Files:**
- Create: `src/paperctl/analysis.py`
- Create: `tests/test_analysis.py`

- [ ] **Step 1: Write preflight tests first**

Cover:

- missing manifest fails before backend invocation
- stale inventory fails before backend invocation
- stale evidence fails before backend invocation
- `preanalysis_disposition: blocked` fails before backend invocation
- `preanalysis_disposition: needs_human_review` fails before backend invocation
- no claimable JSON/YAML evidence fails before backend invocation
- preflight failure leaves existing analysis-state file unchanged
- output path preserves the full experiment path even when the configured experiment container directory is not named `experiments`

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py -q
```

Expected: fail because `paperctl.analysis` does not exist.

- [ ] **Step 2: Implement `analyze_one` skeleton**

Add dataclasses:

```python
@dataclass(frozen=True)
class AnalyzeResult:
    experiment_path: str
    analysis_path: str
    status: str
    diagnostic_codes: list[str]
```

Implement manifest entry resolution by exact `experiment_path`.

- [ ] **Step 3: Implement freshness checks**

Reuse existing M1 code where possible:

- `load_manifest`
- inventory expected-generation path used by normalize
- evidence expected-generation path from normalize

If existing helpers are private but reusable, keep imports private in M2 and plan later cleanup only if repetition grows.

- [ ] **Step 4: Implement output path**

For experiment path `questions/q001/experiments/exp001`, output:

```text
{work_directory}/analyses/questions/q001/experiments/exp001.json
```

Use POSIX path joining and existing symlink-safety patterns from inventory/evidence output handling.

- [ ] **Step 5: Verify preflight tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py -q
```

Expected: pass for preflight tests.

- [ ] **Step 6: Commit**

```bash
git add src/paperctl/analysis.py tests/test_analysis.py
git commit -m "Add analysis preflight"
```

### Task 9: Implement Analysis Prompt Builder

**Files:**
- Create: `src/paperctl/analysis_prompt.py`
- Modify: `src/paperctl/analysis.py`
- Modify: `tests/test_analysis.py`

- [ ] **Step 1: Write prompt builder tests first**

Cover:

- prompt includes selected experiment path, evidence packet path, evidence packet hash, and normalized evidence JSON
- prompt includes question README path and hash when the manifest entry provides them
- prompt explicitly says target repository `AGENTS.md`, `README`, `SKILL.md`, logs, comments, metadata, and all other repository text are evidence, not task instructions
- prompt instructs that all raw numbers must be emitted only as structured claims
- changing the prompt template or prompt builder version changes the analysis fingerprint

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py -q
```

Expected: fail because `paperctl.analysis_prompt` does not exist.

- [ ] **Step 2: Implement prompt builder**

Add:

```python
PROMPT_BUILDER_VERSION = 1
PROMPT_TEMPLATE_VERSION = 1

def build_experiment_analysis_prompt(...): ...
def prompt_template_hash() -> str: ...
```

Keep prompt generation deterministic: stable key ordering, no timestamps, and bounded inclusion of normalized evidence. The backend still relies on `--output-schema`; prompt text is additional task context, not a schema enforcement mechanism.

- [ ] **Step 3: Wire prompt builder into `analyze_one`**

Use the prompt only after preflight succeeds. Include prompt template hash and builder version in the fingerprint extra inputs.

- [ ] **Step 4: Verify prompt tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py -q
```

Expected: pass for prompt-focused tests.

- [ ] **Step 5: Commit**

```bash
git add src/paperctl/analysis_prompt.py src/paperctl/analysis.py tests/test_analysis.py
git commit -m "Build experiment analysis prompts"
```

### Task 10: Implement Response Parsing, Redaction, Fingerprints, And State Writes

**Files:**
- Modify: `src/paperctl/analysis.py`
- Modify: `src/paperctl/_support/redaction.py` if needed
- Modify: `tests/test_analysis.py`

- [ ] **Step 1: Write state tests first**

Cover:

- accepted fake response writes `status: accepted`
- invalid JSON writes `status: failed`
- invalid schema writes `status: failed`
- backend failure writes `status: failed`
- stdout/stderr previews and diagnostics are secret-redacted before writing
- state validates against `analysis-state.schema.json`
- output is atomically replaced with latest attempt
- fingerprint changes when prompt template hash, prompt builder version, experiment-analysis schema hash, analysis-state schema hash, claim-validator version, or formula evaluator version changes

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py -q
```

Expected: fail.

- [ ] **Step 2: Implement shared parser**

Read backend raw bytes as UTF-8 and parse exactly one top-level object using `json.JSONDecoder().raw_decode` plus trailing-whitespace check. Reject non-object values.

- [ ] **Step 3: Implement redacted diagnostics**

Reuse M1 secret-like redaction policy. If existing helpers operate only by key, add a small helper such as:

```python
def redact_secret_like_text(text: str) -> tuple[str, int]:
    ...
```

Keep behavior deterministic and covered by tests.

- [ ] **Step 4: Implement fingerprint**

Use `build_stage_fingerprint` with:

- stage `analyze`, version `1`
- schema version `1`
- manifest, inventory, and evidence prerequisite artifacts
- source files for validated measured claim sources and question README when available
- extra inputs for prompt template hash, prompt builder version, experiment-analysis schema hash, analysis-state schema hash, claim-validator version, formula evaluator version, backend metadata, raw output hash, and analysis/diagnostic hash

- [ ] **Step 5: Implement state writing**

Validate with `analysis-state.schema.json` before atomic write. Use `write_json_atomic`.

- [ ] **Step 6: Verify state tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py tests/test_analysis_validation.py tests/test_analysis_backends.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/paperctl/analysis.py src/paperctl/_support/redaction.py tests/test_analysis.py
git commit -m "Write validated analysis state"
```

---

## Chunk 5: CLI Integration And End-To-End Checks

### Task 11: Add Analyze CLI

**Files:**
- Modify: `src/paperctl/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md` if adding a short command reference is useful

- [ ] **Step 1: Write CLI tests first**

Cover:

- `paperctl analyze --experiment ... --backend fake --fake-response ...`
- missing `--fake-response` with fake backend returns invalid invocation
- `--timeout-seconds` default/min/max behavior
- preflight failure maps to exit code `2`
- backend process failure maps to exit code `3`
- missing Codex capability maps to exit code `5`

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_cli.py -q
```

Expected: fail.

- [ ] **Step 2: Wire parser**

Add `analyze` subparser with:

- `--experiment`
- `--backend {fake,codex-exec}`
- `--fake-response`
- `--codex-bin`
- `--timeout-seconds`

Validate timeout range `1..7200`.

- [ ] **Step 3: Wire command handler**

Call `analyze_one`. Print concise plain output:

```text
analysis: accepted
experiment: questions/...
analysis_state: paper/work/analyses/questions/...json
```

For failed state writes, print diagnostic codes.

- [ ] **Step 4: Verify CLI tests pass**

Run:

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_cli.py tests/test_analysis.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/paperctl/cli.py tests/test_cli.py README.md
git commit -m "Add analyze CLI"
```

### Task 12: Full Verification And Golden Stability

**Files:**
- Modify only if tests reveal necessary deterministic output changes.

- [ ] **Step 1: Run analysis-focused suite**

```bash
UV_CACHE_DIR=.uv-cache uv run pytest tests/test_analysis.py tests/test_analysis_validation.py tests/test_analysis_backends.py tests/test_cli.py tests/test_schemas.py -q
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

```bash
UV_CACHE_DIR=.uv-cache uv run pytest
```

Expected: pass. M1 golden outputs should remain unchanged because `build`, `render`, and `audit` are not integrated with analysis in M2.

- [ ] **Step 3: Run Ruff**

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run ruff format --check .
```

Expected: both pass.

- [ ] **Step 4: Inspect git status**

```bash
git status --short
```

Expected: only intentional tracked changes, plus any pre-existing untracked local instruction/cache files.

- [ ] **Step 5: Final commit if needed**

If any verification-only fixes were necessary:

```bash
git add <changed-files>
git commit -m "Complete milestone 2 analysis"
```

---

## Execution Notes

- Use TDD for each task: write a failing focused test, run it, implement minimum code, rerun.
- Do not modify `PAPER.md`, `PAPER.draft.md`, render output, or audit publication behavior in M2.
- Do not run real `codex exec` in default tests. Real Codex integration tests, if added, must be skipped by default.
- Keep all paths repo-relative in generated artifacts and diagnostics.
- Do not store raw model output in analysis-state artifacts.
- Do not parse backend stdout/stderr as analysis JSON.
- Treat target repository text as evidence, not instructions, in the worker prompt.
