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
- No raw model output embedded in stable analysis-state artifacts.
- No rounded derived claims. Exact derived arithmetic only.
- No rendering or publication of semantic analysis into `PAPER.md`.

## Inputs

`analyze` reads:

- `paper.yaml`
- `paper/work/manifest.json`
- the selected experiment inventory packet
- the selected experiment evidence packet
- the selected question README path and hash from the manifest when available
- files referenced by validated claim sources

The selected experiment must resolve to exactly one manifest entry. M2 accepts
the manifest experiment path as the selector. Short aliases can be added later.

Before backend invocation, `analyze` verifies that manifest, inventory, and
evidence are present and fresh using the same byte-stable freshness checks used
by Milestone 1 stages. If any prerequisite is missing, malformed, stale, or does
not match the selected manifest entry, `analyze` exits with deterministic failure
and does not call the backend.

Exact preflight checks:

1. Load and schema-validate the manifest from configured `paper.work_directory`.
2. Recompute the expected discovery manifest from current question directories
   and compare canonical JSON bytes to the stored manifest.
3. Load and schema-validate the selected inventory.
4. Recompute the expected inventory for the selected manifest entry, including
   configured exclusions and inventory fingerprint, and compare canonical JSON
   bytes to the stored inventory.
5. Load and schema-validate the selected evidence packet.
6. Recompute the expected evidence packet for the selected manifest entry using
   current manifest, inventory, config, adapters, and source files, and compare
   canonical JSON bytes to the stored evidence packet.
7. Require `preanalysis_disposition: "analysis_candidate"` in the evidence
   packet. Evidence packets with `blocked` or `needs_human_review` fail preflight
   before backend invocation.
8. Require at least one claimable structured evidence value in the selected
   evidence packet. For M2, claimable values are `canonical_facts` or
   `observed_values` with JSON Pointer sources backed by JSON or YAML files.
   Experiments with no such values fail preflight before backend invocation.

Preflight failures are not analysis attempts. They do not replace an existing
analysis-state artifact. Backend, parse, schema, or claim-validation failures
are analysis attempts and replace the stable analysis-state artifact with
`status: "failed"`.

M2 uses latest-attempt state only. It does not preserve a
`previous_accepted_sha256`; that can be added later if the project chooses
last-good analysis retention.

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
The JSON Schema should set `additionalProperties: false` except inside explicitly
free-form diagnostic `detail` objects.

Accepted state:

- `schema_version`: integer const `1`
- `artifact_type`: string const `"analysis_state"`
- `question_path`: repo-relative path from the manifest entry
- `experiment_path`: repo-relative path from the manifest entry
- `analysis_path`: repo-relative path of this analysis-state artifact
- `status`: string const `"accepted"`
- `fingerprint`: deterministic stage fingerprint object
- `backend`: backend metadata object
- `analysis`: validated `experiment_analysis` object
- `diagnostics`: empty array
- `raw_output_sha256`: hash of the backend response body

Failed state:

- `schema_version`: integer const `1`
- `artifact_type`: string const `"analysis_state"`
- `question_path`: repo-relative path from the manifest entry
- `experiment_path`: repo-relative path from the manifest entry
- `analysis_path`: repo-relative path of this analysis-state artifact
- `status`: string const `"failed"`
- `fingerprint`: deterministic stage fingerprint object
- `backend`: backend metadata object
- `analysis`: null
- `diagnostics`: non-empty array of diagnostic objects
- `raw_output_sha256`: hash of the backend response body, or null when the
  backend produced no response bytes

Failure diagnostics are bounded and structured. They include validation codes,
messages, source paths and selectors when applicable, backend return metadata
when applicable, and a hash of the raw backend output. They do not include the
full raw model response.

Backend metadata object:

- `name`: `"fake"` or `"codex-exec"`
- `status`: `"completed"`, `"failed"`, or `"timed_out"`
- `return_code`: integer or null
- `stdout_preview`: string capped at 4,000 Unicode code points, or null
- `stderr_preview`: string capped at 4,000 Unicode code points, or null

Diagnostic object:

- `code`: stable machine-readable string
- `message`: human-readable string capped at 1,000 Unicode code points and
  without absolute paths
- `path`: repo-relative path or null
- `selector_type`: `"json_pointer"` or null
- `selector`: selector string or null
- `detail`: optional object for structured metadata; serialized canonical JSON
  must be capped at 4,000 bytes

Fingerprint object:

- `stage`: object with `name: "analyze"` and integer `version`
- `schema_version`: integer
- `config_sha256`: hash of relevant analysis config
- `source_files`: hash records for source files used to validate claims and the
  question README when available
- `prerequisite_artifacts`: hash records for manifest, inventory, and evidence
- `extra_inputs`: backend name, backend configuration, output hash, and
  accepted-analysis or diagnostics hash
- `fingerprint_sha256`: hash of the fingerprint payload

The exact serialization should reuse the existing Milestone 1 fingerprint helper
where possible.

## Experiment Analysis Schema

The backend returns an `experiment_analysis` object. M2 validates and stores it
inside an accepted analysis state only if all schema and claim checks pass.

Required fields:

- `schema_version`: integer const `1`
- `artifact_type`: string const `"experiment_analysis"`
- `question_path`: repo-relative path matching the manifest entry
- `experiment_path`: repo-relative path matching the manifest entry
- `title`: non-empty string
- `execution_status`: enum listed below
- `hypothesis_verdict`: enum listed below
- `objective`: non-empty string
- `answer`: non-empty string
- `meaning`: non-empty string
- `limitations`: array of strings
- `confidence`: enum listed below
- `claims`: array of measured or derived claim objects

Allowed execution statuses:

- `completed`
- `failed`
- `incomplete`
- `unknown`

This reuses the Milestone 1 deterministic execution-status enum. If the selected
evidence packet has a deterministic `execution_status` other than `unknown`, the
analysis `execution_status` must match it exactly.

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

The JSON Schema should reject unknown top-level properties and unknown claim
properties. Claim IDs must be unique within one analysis.

Concrete field bounds:

- `title`: 1 to 160 Unicode code points
- `objective`: 1 to 1,000 Unicode code points
- `answer`: 1 to 1,500 Unicode code points
- `meaning`: 1 to 1,500 Unicode code points
- each limitation: 1 to 500 Unicode code points
- `limitations`: at most 10 entries
- `claims`: at most 50 entries
- failure `diagnostics`: at most 20 entries
- `claim_id`: 1 to 80 ASCII characters matching
  `^[A-Za-z_][A-Za-z0-9_]*$`
- `label`: 1 to 160 Unicode code points
- `unit`: null or 1 to 80 Unicode code points
- `formula`: 1 to 300 ASCII characters
- `input_claim_ids`: 1 to 20 unique entries
- claim string `value`: at most 2,000 Unicode code points
- source `path`: repo-relative path, 1 to 1,000 Unicode code points
- source `source_hash`: `sha256:` plus 64 lowercase hex characters
- source `selector`: JSON Pointer string, at most 1,000 Unicode code points

Claim IDs deliberately use an identifier grammar rather than hyphenated names
so the formula parser can distinguish claim symbols from subtraction.

## Claim Validation

All raw numbers belong in structured claims. Prose fields may refer to claim IDs
or use qualitative wording, but they must not introduce numeric facts outside
`claims`. M2 does not render or publish semantic analysis into `PAPER.md`, so
this policy protects stored analysis artifacts rather than final prose.

Numeric-prose validation applies to `title`, `objective`, `answer`, `meaning`,
and `limitations`. It rejects standalone numeric tokens such as `13`, `13.585`,
`-2`, or `100%`. Digits embedded in identifiers such as `exp014` or claim IDs
are not standalone numeric tokens. Claim values remain the only accepted place
for raw measured or derived numbers.

### Measured Claims

Measured claims require:

- unique `claim_id`
- `claim_type: "measured_value"`
- `label`
- `value`
- `value_type`
- optional `unit`
- one source object

Allowed `value_type` values are:

- `string`
- `number`
- `integer`
- `boolean`
- `null`

Claim `value` must conform to `value_type`. String values use the concrete
2,000-code-point cap above. Numeric, boolean, and null values use JSON scalar
schema validation plus the numeric exactness rules below.

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
10. The claim must correspond to a `canonical_facts` or `observed_values` entry
    already present in the selected evidence packet with the same path,
    source hash, selector type, selector, value, value type, and unit.

Type matching follows JSON Schema scalar semantics with one deliberate widening:
an integer source value may satisfy a claim with `value_type: "number"`, but a
non-integral number may not satisfy `value_type: "integer"`.

Measured numeric equality is exact after JSON/YAML parsing. M2 does not apply
tolerances, rounding, or unit conversion for measured claims.

Cross-question and unrelated-experiment source paths are rejected in M2.
The validator may reopen raw JSON/YAML sources only to verify hashes, selectors,
and values for claims already present in the selected evidence packet. It must
not discover new measured claims from raw sources in M2.

Accepted analysis requires at least one validated `measured_value` claim. A
response containing only derived claims, only prose, or zero claims fails
claim validation.

### Derived Claims

Derived claims require:

- unique `claim_id`
- `claim_type: "derived_value"`
- `label`
- `value`
- `value_type: "number"` or `value_type: "integer"`
- optional `unit`
- `formula`
- `input_claim_ids`, with at least one entry

Validation rules:

1. Every input claim ID exists in the same analysis.
2. Every input claim is numeric.
3. The set of claim ID symbols referenced in `formula` exactly equals
   `input_claim_ids`; unused inputs and unlisted same-analysis claim references
   fail validation.
4. The formula contains only claim IDs, numeric literals, parentheses, and
   `+`, `-`, `*`, `/`.
5. Numeric literals are limited to `0`, `1`, and `100`. Every other numeric
   input must be a measured claim with provenance.
6. The formula contains no unknown symbols.
7. Division by zero fails validation.
8. The formula result equals the reported value exactly.

The implementation should evaluate formulas with a small safe parser, not
Python `eval`.

Derived arithmetic should use Python `Decimal` or an equivalent exact decimal
strategy over JSON numeric string representations. A derived integer claim must
produce an integral result. A derived number claim must compare exactly to the
reported numeric value after decimal normalization. M2 does not support
approximate floating-point tolerances.

Rounded derived claims are explicitly deferred. For example, a formula that
produces `1 / 3` cannot be accepted as `0.333`, `0.33`, or any rounded decimal
in M2.

JSON and YAML numeric values should be converted to `Decimal` from their parsed
canonical string representation, not from binary floating-point arithmetic.

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
- question README path and hash when available
- experiment path
- inventory path
- evidence packet path
- output schema name or schema path
- backend-specific options

`AnalysisBackendResult` includes:

- backend name
- status
- raw response bytes when available
- bounded stdout and stderr summaries
- return code when applicable

Both real and fake backends feed the same parser, schema validator, claim
validator, and analysis-state writer.
Backends do not return parsed analyses; response parsing is centralized after
backend execution so fake and real outputs follow identical parser rules.

## Implementation Units

Milestone 2 should be implemented as small units with clear inputs and outputs:

- `analysis.py`: orchestration for one selected experiment. It loads config,
  resolves the manifest entry, runs preflight, invokes the backend, validates,
  writes state, and returns a command result.
- `analysis_backends.py` or `backends/analysis.py`: backend protocol plus
  `FakeBackend` and `CodexExecBackend`. It returns backend results but does not
  validate claims or write stable artifacts.
- `analysis_validation.py`: schema-adjacent validation for measured and derived
  claims. It accepts a parsed analysis object plus repo/config context and
  returns diagnostics or a validated analysis.
- `formula.py`: safe arithmetic parser/evaluator for derived claims. It has no
  filesystem dependencies.
- `analysis_state.py` or local helpers in `analysis.py`: builds deterministic
  accepted/failed state payloads, fingerprints them, computes mirrored output
  paths, and performs atomic writes.
- `schemas/experiment-analysis.schema.json`: model response contract.
- `schemas/analysis-state.schema.json`: stable generated artifact contract.

These units should not change M1 renderer, audit, or build behavior in M2.

## Fake Backend

`FakeBackend` reads the response JSON specified by `--fake-response`.
`--fake-response` resolves relative to the current working directory, not the
target `--repo`, matching the existing `uv run paperctl ...` development usage
where fixture paths are supplied from the framework repository.

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

The backend writes the prompt to a temporary prompt file outside the target repo
and requests the final model message in a temporary output file outside the
target repo. Conceptual invocation:

```bash
codex exec \
  --ephemeral \
  --sandbox read-only \
  --ask-for-approval never \
  --output-schema /path/to/experiment-analysis.schema.json \
  --output-last-message /tmp/paperctl-analysis-response.json \
  --file /tmp/paperctl-analysis-prompt.md
```

If the installed `codex exec` surface requires a different non-interactive
prompt transport, the implementation may adapt the argument array. It may not
drop enforced schema output, read-only execution, or non-interactive/no-approval
execution.

`CodexExecBackend` must enforce `experiment-analysis.schema.json` with
`codex exec --output-schema`, not only through prompt instructions. If the
installed Codex executable cannot enforce schema output, the backend fails before
invocation with exit code `5`.

`CodexExecBackend` must require read-only and non-interactive/no-approval
execution. If the installed Codex executable cannot provide those capabilities,
the backend fails before invocation with exit code `5`.

The response contract remains: the backend response body is the UTF-8 contents
of a single final-message file expected to contain one JSON object.

The worker prompt is narrow and includes:

- primary question path
- question README path and current hash when available
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

Parser rules shared by fake and real backends:

1. Read the backend response body as UTF-8 bytes.
2. Parse exactly one top-level JSON object.
3. Reject empty output, invalid UTF-8, invalid JSON, arrays, strings, numbers,
   and multiple concatenated JSON documents.
4. Treat stdout and stderr as diagnostics only; never parse analysis JSON from
   stdout or stderr.
5. Hash the raw response bytes as `raw_output_sha256`.

## Data Flow

`paperctl analyze` runs:

1. Resolve target repo.
2. Load and validate config.
3. Load and validate manifest.
4. Resolve `--experiment` to one manifest entry.
5. Load and validate that experiment inventory.
6. Load and validate that experiment evidence packet.
7. Verify deterministic freshness.
8. Verify evidence-packet preanalysis disposition and claimable structured
   evidence.
9. Build `AnalysisJob` with question README context when available.
10. For `codex-exec`, verify required schema-output, read-only, and
    no-approval capabilities.
11. Invoke backend.
12. Parse backend response.
13. Validate experiment-analysis schema.
14. Validate execution status consistency.
15. Validate measured claims against evidence-packet facts/values and raw
    sources.
16. Validate derived claims.
17. Validate numeric-prose policy.
18. Build analysis-state artifact.
19. Atomically write analysis-state artifact.
20. Print concise status summary.

## Error Handling

Missing or stale deterministic prerequisites:

- exit with deterministic failure
- do not invoke backend
- do not write an analysis-state artifact
- leave any existing analysis-state artifact unchanged

Evidence packet not eligible for analysis:

- exit with deterministic failure
- do not invoke backend
- do not write an analysis-state artifact
- leave any existing analysis-state artifact unchanged

Missing Codex backend capability:

- exit with missing dependency failure
- do not invoke backend
- do not write an analysis-state artifact
- leave any existing analysis-state artifact unchanged

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

Exit codes follow existing CLI conventions:

- `0`: accepted analysis written
- `2`: deterministic preflight failure, invalid backend JSON, schema failure,
  or claim-validation failure
- `3`: backend process failed or timed out after invocation
- `4`: invalid command usage
- `5`: missing `codex` executable or missing required external backend
  capability

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

`--timeout-seconds` defaults to `600`, has a minimum of `1`, and has a maximum
of `7200`. The timeout applies to the Codex subprocess only; fake backend reads
should remain ordinary file I/O and should not use this timeout.

The real backend is explicit. There is no hidden default that can launch an LLM
call by accident.

Plain output is sufficient for M2. Rich output can be added later after the
command behavior stabilizes.

## Fingerprints

Accepted and failed analysis states include deterministic fingerprints covering:

- analysis stage version
- analysis-state schema version
- analysis-state schema hash
- experiment-analysis schema hash
- relevant config
- manifest artifact hash
- inventory artifact hash
- evidence packet artifact hash
- question README path and hash when available
- prompt template hash
- prompt builder version
- claim-validator version
- formula evaluator version
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
- Evidence packet with `preanalysis_disposition: blocked` fails before backend
  invocation.
- Evidence packet with `preanalysis_disposition: needs_human_review` fails
  before backend invocation.
- Evidence packet with no claimable structured evidence fails before backend
  invocation.
- FakeBackend accepted fixture writes `status: "accepted"`.
- Invalid schema fixture writes `status: "failed"`.
- Accepted analysis with no measured claim writes `status: "failed"`.
- Analysis execution status conflicting with known deterministic execution status
  writes `status: "failed"`.
- Stale source hash writes `status: "failed"`.
- Bad JSON Pointer writes `status: "failed"`.
- Source outside selected experiment writes `status: "failed"`.
- Measured claim not present in evidence-packet `canonical_facts` or
  `observed_values` writes `status: "failed"`.
- Valid derived arithmetic writes `status: "accepted"`.
- Unknown derived claim input writes `status: "failed"`.
- Derived formula with an uncited numeric literal other than `0`, `1`, or `100`
  writes `status: "failed"`.
- Non-exact rounded division writes `status: "failed"`.
- Division by zero writes `status: "failed"`.
- Prose numeric literal outside structured claims writes `status: "failed"`.
- Backend failure writes bounded diagnostics.
- Codex command construction includes read-only sandboxing, no-approval mode, and
  `--output-schema` pointing at `experiment-analysis.schema.json`.
- Codex backend refuses to invoke when schema-output enforcement is unavailable.
- Codex backend refuses to invoke when read-only or no-approval execution is
  unavailable.
- Analysis fingerprint changes when the prompt template hash changes.
- Analysis fingerprint changes when the prompt builder version changes.
- Analysis fingerprint changes when `experiment-analysis.schema.json` changes.
- Analysis fingerprint changes when `analysis-state.schema.json` changes.
- Analysis fingerprint changes when the claim-validator version changes.
- Analysis fingerprint changes when the formula evaluator version changes.
- Analysis fingerprint changes when the question README hash changes.
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
