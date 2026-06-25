# Milestone 1 Deterministic Design

Date: 2026-06-25

## Purpose

Build Milestone 1 of the `codex-paper` framework: a deterministic, LLM-free substrate that discovers research questions and experiments, inventories artifacts, extracts bounded observable evidence, renders a pre-analysis evidence draft, and records audit results.

Milestone 1 does not produce a publishable paper. It always keeps output at `PAPER.draft.md` and blocks publication because validated semantic analyses are absent.

## Source Context

This design is based on the repository handoff in `handoffs.md` and the local project rules in `AGENTS.md`.

The framework repository and target research repository are separate concepts. Every CLI command accepts `--repo`; when `--repo` is omitted, the command resolves the current Git root and fails clearly if no Git root exists.

## Approach

Use stage modules with explicit artifact contracts.

Core modules:

- `config`
- `discovery`
- `inventory`
- `normalize`
- `rendering`
- `audit`
- `build`

Small shared helpers may handle only mechanical concerns:

- repository-relative path validation
- content hashing
- atomic writes
- deterministic JSON serialization
- JSON Schema validation
- fingerprint comparison

Avoid a generic pipeline engine, plugin system, dependency graph framework, or dynamic adapter registry. Stage modules own domain behavior.

## Artifact Flow

The key invariant is:

```text
source repository
→ discovery artifact
→ inventory artifacts
→ evidence packets
→ deterministic draft
→ audit report
```

Every transition must be explicit, reproducible, and independently testable.

Recommended target-repository outputs:

```text
paper/work/manifest.json
paper/work/inventories/questions/<question-dir>/experiments/<experiment-dir>.json
paper/work/evidence/questions/<question-dir>/experiments/<experiment-dir>.json
paper/work/render-state.json
PAPER.draft.md
paper/PAPER.audit.json
```

Inventory and evidence paths intentionally mirror the source experiment path beneath their stage directory. Manifest entries record those generated artifact paths so later stages do not need to recompute them.

Generated JSON artifacts include `schema_version`, `artifact_type`, stage metadata, fingerprints, deterministic content, and schema validation. They are written atomically.

## CLI

Milestone 1 commands:

```text
paperctl --repo <path> init [--force]
paperctl --repo <path> discover [--force]
paperctl --repo <path> inventory [--force]
paperctl --repo <path> normalize [--force]
paperctl --repo <path> render [--force]
paperctl --repo <path> audit [--stage deterministic|publication] [--force]
paperctl --repo <path> build [--force]
```

Each command exposes a normal Python API. `build` calls those APIs directly, not CLI subprocesses.

Standalone stage commands perform only their own stage and fail clearly when prerequisites are missing or stale. Only `build` runs prerequisite stages.

`--force` bypasses caching only for the invoked stage. For `build`, it applies to all stages.

Exit behavior:

- `audit --stage deterministic` exits 0 when deterministic health passes.
- `audit --stage publication` exits nonzero in Milestone 1 while semantic analysis is missing or pre-analysis blockers remain.
- `build` exits 0 when the deterministic pipeline and deterministic-health audit pass, while reporting publication as blocked.

Stable exit-code categories:

```text
0  success for the requested scope
2  deterministic validation, configuration, safety, or freshness failure
3  publication gate blocked
4  invalid invocation or unresolved target repository
5  missing external dependency
```

The implementation should respect the conventions of the selected CLI library, but these categories must remain documented and stable.

`build` is deterministic orchestration only:

```text
discover
→ inventory
→ normalize/evidence extraction
→ render PAPER.draft.md
→ deterministic audit
→ record publication blockers
```

It must not trigger future LLM analysis without an explicit future option such as `--with-analysis`.

## Initialization

`paperctl init` safely initializes only framework configuration and runtime directories.

It creates:

```text
paper.yaml
paper/
└── work/
    ├── inventories/
    ├── evidence/
    └── cache/
```

It must:

- create `paper.yaml` with documented defaults;
- create runtime directories idempotently;
- validate the generated configuration before returning success;
- print created files and directories;
- refuse to overwrite `paper.yaml` unless `--force` is supplied;
- replace only `paper.yaml` when `--force` is supplied;
- write replacements atomically.

It must not create or modify questions, experiments, metadata, README files, output artifacts, `PAPER.md`, or `PAPER.draft.md`.

## Configuration

`paper.yaml` is the only user-authored framework configuration YAML file. It is parsed with safe YAML loading, custom tags are prohibited, and the parsed object is validated by `paper-config.schema.json`.

Unknown keys fail validation. All paths are repository-relative. Absolute paths, `..` escapes, and resolved paths outside the repository are rejected.

Initial shape:

```yaml
schema_version: 1

questions:
  root: questions
  pattern: "q*"
  experiments_directory: experiments

paper:
  work_directory: paper/work
  draft_output: PAPER.draft.md
  final_output: PAPER.md
  audit_report: paper/PAPER.audit.json

evidence:
  default_canonical_artifacts:
    - outputs/experiment_report.json
  canonical_facts: {}
  extraction_limits:
    maximum_file_bytes: 10000000
    maximum_scalar_observations_per_file: 200
    maximum_nesting_depth: 12
    preview_rows: 20
    log_head_lines: 100
    log_tail_lines: 100

audit:
  default_stage: publication
```

`paper.final_output` is retained only as the protected future publication target. Milestone 1 never writes or replaces it.

Do not add future agent, concurrency, review, repair, model, or publication-policy settings until those features exist.

## Canonical Facts

Canonical fact mappings are per experiment only, keyed by repository-relative POSIX experiment paths, for example:

```yaml
evidence:
  canonical_facts:
    "questions/q001-throughput/experiments/exp014-two-workers":
      - fact_id: measured_throughput
        source: outputs/hpi_2wpg_summary.json
        selector_type: json_pointer
        selector: /primary_slice/pages_per_second
        expected_type: number
        unit: pages_per_second
```

Requirements:

- experiment references must resolve uniquely;
- source paths are relative to the experiment directory;
- selectors must resolve exactly once;
- `fact_id` values are unique within each single canonical declaration source;
- units are explicitly configured or present in the source;
- units are never inferred from field names;
- for user-authored `paper.yaml` `canonical_facts` mappings, missing files, invalid selectors, type mismatches, path escapes, or duplicate fact IDs within that configured declaration source are deterministic-health errors.

`default_canonical_artifacts` does not make every scalar canonical. `outputs/experiment_report.json` is authoritative only for fields defined by its versioned contract. Other canonical facts require explicit selector mappings.

Canonical mappings establish authoritative facts, not conclusions, inclusion, or headline importance.

Milestone 1 `experiment_report.json` contract:

```json
{
  "schema_version": 1,
  "execution_status": "completed",
  "canonical_facts": [
    {
      "fact_id": "measured_throughput",
      "value": 13.585,
      "value_type": "number",
      "unit": "pages_per_second",
      "source": {
        "path": "outputs/hpi_2wpg_summary.json",
        "selector_type": "json_pointer",
        "selector": "/primary_slice/pages_per_second"
      }
    }
  ]
}
```

Only `execution_status` and entries in `canonical_facts` have contract meaning in Milestone 1. Each `canonical_facts` entry must include `fact_id`, `value`, `value_type`, `unit` or `null`, and a source path/selector. The selector is resolved independently of scalar enumeration limits and the source value is compared with `value`. Internal report value/selector mismatch is not a cross-source conflict; it blocks that experiment with `source_contract_value_mismatch`. `execution_status` affects only deterministic status, not research meaning.

A single canonical declaration source is malformed if it repeats a `fact_id` for the same experiment. Distinct valid canonical declaration sources may intentionally claim the same `fact_id`; if their normalized values, value types, or units disagree, the evidence packet records a `canonical_conflict`, `evidence_status` becomes `conflicting`, and `preanalysis_disposition` becomes `needs_human_review`. Different provenance paths or selectors alone are not a conflict when the normalized value, type, and unit agree.

An `experiment_report.json` at a default canonical artifact path creates canonical facts only if it declares a recognized `schema_version` and validates against `experiment-report.schema.json`. A missing default report is not an error by itself. A report with an unknown `schema_version` blocks that experiment with `unknown_experiment_report_version`. A recognized but malformed report blocks that experiment with `malformed_experiment_report`. Unrecognized structured files at the same path may still be inventoried and extracted as ordinary observed values, but they do not create canonical facts.

## Discovery

Discovery reads the configured question root and pattern, then finds experiment directories under each question's configured experiments directory. Experiment names do not need an `expNNN-` prefix.

Identity is path-based, not inferred from directory names. Duplicate or ambiguous references are deterministic errors.

`manifest.json` is discovery-owned and immutable after discovery. Inventory writes only per-experiment inventory artifacts. Normalize writes only per-experiment evidence packets. Status and disposition fields belong in evidence packets, not in the manifest.

Each manifest entry records stable source identity and generated artifact locations:

```text
question_ref
question_path
question_readme_path
question_readme_sha256
experiment_ref
experiment_path
inventory_path
evidence_path
```

`question_readme_path` and `question_readme_sha256` are `null` when the README is absent. Missing README files do not prevent discovery.

Empty repository behavior:

- Missing configured questions root is a deterministic failure.
- Existing configured questions root with zero experiments is a successful deterministic discovery. Publication is blocked with `no_experiments_discovered`.

Milestone 1 does not assign final labels such as `included`, `excluded_smoke_only`, or `excluded_superseded`.

`execution_status` is assigned in evidence packets only, and only from a validated Milestone 1 `experiment_report.json` contract. Otherwise it is `unknown`. Legacy metadata files may be inventoried and extracted as observed values, but they do not set `execution_status` unless a future milestone defines and validates their schema. Do not infer completion from README prose, filenames, or warning/error matches.

A failed execution is not automatically excluded. Failed experiments may still be `analysis_candidate` if sufficient artifacts exist.

## Inventory

Inventory records all regular files and symlinks under each experiment directory. The exact exclusion list is `.git`, `.hg`, `.svn`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, and `.DS_Store`. Do not silently omit `work/` or unknown artifacts.

Each file record includes repository-relative POSIX path, file type, byte size, lowercase `sha256:<hex>` over exact file bytes, detected kind, and support status.

Symlinks are recorded without following them. Inert external symlinks are unsupported evidence, not automatic deterministic-health failures. Canonical/configured paths may not traverse symlinks that resolve outside the repository.

Kind detection uses a fixed extension map, plus explicit binary detection for files that cannot be safely decoded. Do not infer kind from filename prose beyond that map.

Inventory does not execute experiment scripts and does not mutate experiment content.

Unknown or binary files are inventoried but unsupported unless an explicit adapter exists.

## Normalize And Evidence Extraction

`normalize` reads inventories, runs bounded adapters, and writes evidence packets.

Initial adapters:

- JSON/YAML: scalar values with exact JSON Pointer paths, bounded by depth and observation limits.
- CSV: schema, row count, selected rows, and bounded numeric summary previews.
- JSONL: streamed line count, schema/sample, head/tail, and bounded numeric summary previews.
- Markdown: headings and short escaped excerpts with line ranges.
- Logs: streamed head/tail plus fixed warning/error pattern matches with line numbers.
- Unknown/binary: inventory-only unsupported records.

`maximum_file_bytes` means maximum full-parse size. Streaming adapters may inspect larger logs and JSONL files for bounded previews, columns, matches, and summaries.

Markdown and log adapters produce previews and diagnostics, not observed values. Unstructured numbers must not become facts automatically.

CSV and JSONL numeric summaries are also previews/diagnostics, not observed values or accepted numeric claims. They must record their calculation label, source path, source hash, inspected row/line bounds, omitted counts, and adapter version. They may be rendered only in preview sections, never as canonical facts or observed values.

Error and warning matches use a documented fixed pattern set. They are diagnostics, not proof of failed execution.

Evidence packets distinguish:

- canonical facts;
- observed values;
- previews;
- diagnostics;
- conflicts;
- unsupported artifacts;
- extraction warnings.

Evidence packets also carry the experiment's deterministic status fields:

```text
preanalysis_disposition: analysis_candidate | blocked | needs_human_review
execution_status: completed | failed | incomplete | unknown
evidence_status: available | missing | unsupported | conflicting
reason_codes: [...]
counts: canonical_fact_count, observed_value_count, preview_count, diagnostic_count, conflict_count, unsupported_artifact_count, warning_count
```

`reason_codes` is a closed enum in Milestone 1:

```text
no_usable_evidence
unsupported_only
malformed_experiment_report
unknown_experiment_report_version
source_contract_selector_missing
source_contract_type_mismatch
source_contract_value_mismatch
duplicate_fact_id_in_source
canonical_conflict
unsafe_symlink_for_canonical_path
normalization_truncated
```

After normalization, `preanalysis_disposition` is assigned deterministically:

- `analysis_candidate`: `evidence_status` is `available`; this can be true with only preview or diagnostic evidence. `execution_status` may be `completed`, `failed`, `incomplete`, or `unknown`; execution failure alone does not block analysis candidacy.
- `blocked`: required experiment evidence inputs cannot be used, including no usable evidence, unsupported-only evidence, malformed or unknown-version `experiment_report.json`, duplicate canonical `fact_id` values within one source artifact, unsafe symlink traversal for a canonical path, source contract selector failures, source contract type mismatches, or internal source contract value mismatches.
- `needs_human_review`: distinct valid canonical declaration sources disagree on the same fact after normalized value/type/unit comparison.

Each observed value retains:

- source path;
- selector or line range;
- raw value;
- parsed type;
- unit only when explicitly present or configured;
- source hash;
- extraction adapter;
- adapter version.

Do not double-enumerate validated `experiment_report.json` fields or mapped canonical selectors as observed values. A value is either canonical or observed in a given evidence packet, not both.

Conflict detection occurs only between distinct canonical declaration sources explicitly claiming the same `fact_id` or contract field. Duplicate `fact_id` entries within one declaration source are malformed input, not an evidence conflict. Do not infer conflicts from similar field names.

Aggregate `evidence_status` deterministically:

- `missing`: the inventory contains no files that can produce canonical facts, observed values, previews, or diagnostics.
- `unsupported`: artifacts exist, but every artifact is unsupported and no preview or diagnostic can be produced.
- `conflicting`: two or more distinct valid canonical declaration sources claim the same `fact_id` with different normalized values, value types, or units.
- `available`: at least one canonical fact, observed value, preview, or diagnostic is available and no canonical conflict exists.

Non-finite numbers such as NaN and Infinity are rejected.

## Selectors

Supported selectors in Milestone 1:

- JSON Pointer for JSON and YAML.

Selector failures in user-authored `paper.yaml` canonical mappings are deterministic-health errors. Selector failures inside source `experiment_report.json` artifacts make that experiment `blocked` unless they participate in an explicit cross-source canonical conflict.

Tabular canonical selectors are deferred. CSV and JSONL adapters may produce bounded previews and diagnostic summaries, but Milestone 1 does not accept CSV/JSONL cells as canonical facts through selector mappings.

## Rendering

Rendering produces `PAPER.draft.md` only. It also writes `paper/work/render-state.json` to track render inputs and the draft hash.

The draft contains a prominent notice that it is a pre-analysis evidence draft and not a publishable paper.

For each question, render:

- question identity and source path;
- discovered experiments;
- pre-analysis disposition fields from evidence packets;
- observed value and canonical fact summaries;
- evidence conflicts;
- missing or unsupported evidence;
- known publication blockers.

For each experiment, render:

- experiment title/path identity;
- deterministic execution status when known;
- pre-analysis disposition from its evidence packet;
- observed-value/canonical-fact table;
- source artifact paths/selectors;
- conflicts and warnings.

Do not render interpretation, meaning, conclusions, recommendations, semantic verdicts, rankings, ratios, "best" claims, or placeholder sections such as "interpretation unavailable."

Milestone 1 may render mechanical evidence tables: per-experiment canonical facts, bounded observed values, source selectors, and status fields. It does not render cross-experiment comparison tables that imply research meaning. Broader deterministic comparison tables are deferred until later milestones have validated semantic analyses and explicit claim relationships.

Keep the draft bounded. Render all canonical facts, then at most 20 observed values, 10 previews, 20 diagnostics, 20 warnings, and 20 unsupported artifacts per experiment unless configuration later exposes stricter implemented limits. Report omitted counts and point to the complete evidence packet.

Escape untrusted artifact text before inserting excerpts into Markdown.

Avoid a render/audit dependency cycle. `render` derives a "Known publication blockers" section through the same shared blocker-derivation helper that audit uses, based on the manifest and evidence packets. Audit later validates that section.

Stable ordering is mandatory for questions, experiments, facts, warnings, and blockers. Do not emit timestamps.

## Audit

Audit writes `paper/PAPER.audit.json`.

Audit always computes both independent result groups, even when the requested `--stage` controls only exit behavior:

```json
{
  "schema_version": 1,
  "artifact_type": "paper_audit",
  "deterministic_health": {
    "status": "passed",
    "issues": []
  },
  "publication_gate": {
    "status": "blocked",
    "blockers": [
      {
        "severity": "blocker",
        "code": "missing_semantic_analysis",
        "experiment_ref": "questions/q001-throughput/experiments/exp001-completed"
      }
    ]
  }
}
```

`publishable` is a derived field: true only when deterministic health has status `passed` and publication gate has status `passed`. It must not be treated as an independent manually written truth.

Deterministic health checks:

- schema validity;
- prerequisite freshness;
- path safety;
- resolved provenance;
- source hashes;
- user-configured canonical selector validity and recorded source-contract selector failures;
- explicit conflict records;
- truncation warnings;
- every experiment represented in the manifest;
- every manifest experiment has one valid fresh inventory artifact and one valid fresh evidence packet at the manifest-recorded paths;
- draft determinism by rendering again to a temporary buffer and comparing bytes or hashes.

Distinguish:

- deterministic implementation/configuration errors;
- unresolved evidence blockers;
- informational warnings.

A correctly recorded evidence conflict or truncation warning is not itself a deterministic pipeline failure.

Deterministic-health failures are reserved for framework, configuration, safety, and artifact-integrity failures that prevent trustworthy deterministic output. Examples include invalid `paper.yaml`, unknown config keys, unsafe paths, path traversal, unsafe configured/canonical symlink traversal outside the repository, stale or schema-invalid prerequisite artifacts, invalid user-authored `canonical_facts` mappings, generated artifact schema failures, unresolved provenance for accepted canonical facts, and render nondeterminism.

Experiment evidence problems are represented in evidence-packet status and block publication without necessarily failing deterministic health. Examples include no usable evidence, unsupported-only artifacts, malformed recognized `experiment_report.json`, source report selectors that fail to resolve, source report type mismatches, explicit canonical conflicts between distinct sources, and bounded truncation. If such problems are fully recorded in valid generated artifacts, `audit --stage deterministic` may still pass and `build` may exit 0 while publication remains blocked.

Publication blockers include:

```text
analysis_candidate  → missing_semantic_analysis
blocked             → unresolved_preanalysis_blocker
needs_human_review  → needs_human_review
conflicting evidence → unresolved_evidence_conflict
missing/unsupported evidence in evidence-packet status fields → unresolved_evidence_blocker
zero manifest experiments → no_experiments_discovered
```

Publication blockers use deterministic precedence and deduplication per experiment. Emit at most one primary blocker from evidence-packet `preanalysis_disposition` in this order: `needs_human_review`, `blocked`, `analysis_candidate`. Then emit at most one additional evidence blocker if evidence-packet `evidence_status` is `conflicting`, `missing`, or `unsupported`, ordered as `conflicting`, `missing`, `unsupported`. Sort final blockers by question path, experiment path, blocker priority, then code. Do not emit duplicate blocker codes for the same experiment.

Audit must never modify or delete an existing `PAPER.md`.

## Generated JSON Rules

Generated JSON artifacts:

- include `schema_version`;
- include `artifact_type`;
- validate against JSON Schema;
- use stable key ordering and deterministic formatting;
- end with a newline;
- use repository-relative POSIX paths;
- avoid timestamps;
- represent missing values consistently as `null`;
- reject non-finite numbers;
- write atomically through temporary files.

Deterministic sort order is by repository-relative question path, experiment path, artifact path, selector, fact ID, reason code, then blocker code as applicable. Do not depend on filesystem traversal order.

Hashes are lowercase `sha256:<hex>` over exact bytes. Normalized configuration hashes use canonical JSON serialization, not original YAML formatting.

Avoid self-referential hashes. An artifact must not include a hash of its own complete bytes. Its fingerprint records inputs; downstream artifacts hash the completed artifact file.

## Sensitive Data

Treat target repositories as potentially containing secrets. Milestone 1 must not emit obvious secrets into evidence packets, previews, diagnostics, logs, or `PAPER.draft.md`.

Use a small fixed redaction pattern set for common secret shapes such as assignment-style keys containing `password`, `passwd`, `secret`, `token`, `api_key`, `apikey`, `access_key`, or `private_key`. Preserve enough context to diagnose redaction, such as path, selector or line number, and redaction count, but replace the sensitive value with `[REDACTED]`.

Redaction is deterministic and recorded as a warning/diagnostic. Do not attempt entropy-based secret detection in Milestone 1.

## Schemas

Package schemas inside the Python distribution:

```text
src/paperctl/schemas/
├── __init__.py
├── paper-config.schema.json
├── manifest.schema.json
├── artifact-inventory.schema.json
├── evidence-packet.schema.json
├── render-state.schema.json
├── paper-audit.schema.json
└── experiment-report.schema.json
```

Load schemas through `importlib.resources`.

`experiment-report.schema.json` validates a source contract. It is not necessarily a framework-generated artifact and does not need framework fingerprint metadata unless `paperctl` later generates it.

## Fingerprints And Staleness

Use one small shared fingerprint structure. Do not create a generic cache database.

Fingerprints record:

- stage name;
- stage implementation version;
- relevant normalized configuration hash;
- source file paths and content hashes;
- adapter names and versions where applicable;
- hashes of prerequisite generated artifacts;
- schema identifier/version.

Staleness checks validate prerequisite schemas before trusting fingerprints.

Discovery fingerprints include a deterministic snapshot of relevant directory entries, so adding or deleting a question or experiment invalidates the manifest.

Inventory fingerprints include the complete in-scope file listing, including path, file type, and content hash.

Evidence packets depend on the inventory artifact hash plus hashes of any source files actually inspected. Adapter invalidation is recorded per adapter, so changing the CSV adapter does not invalidate evidence produced only by JSON adapters.

Freshness checks recompute source-derived inputs transitively. They must not trust cached child artifacts merely because an immediate prerequisite hash is present; the prerequisite itself must be schema-valid and fresh for its recorded source inputs.

Per-stage configuration dependencies:

| Stage | Relevant configuration fields |
|---|---|
| `init` | default configuration template version |
| `discover` | `questions.root`, `questions.pattern`, `questions.experiments_directory`, `paper.work_directory` |
| `inventory` | `paper.work_directory`, inventory exclusion list, kind extension map |
| `normalize` | `evidence.default_canonical_artifacts`, `evidence.canonical_facts`, `evidence.extraction_limits`, adapter versions |
| `render` | `paper.draft_output`, render limits, manifest hash, ordered evidence packet hashes |
| `audit` | `paper.audit_report`, `audit.default_stage`, manifest/inventory/evidence/render-state hashes |
| `build` | the union of invoked stage dependencies |

Changing renderer configuration must not force evidence re-extraction. Changing extraction limits must not force discovery regeneration.

Render state contains:

- renderer version;
- relevant config hash;
- manifest hash;
- ordered evidence-packet hashes;
- draft SHA-256;
- draft path.

Cache reuse is an optimization only. Regenerated output from identical inputs must be byte-identical.

## Package Layout

Use a `uv`-managed Python package with `src/` layout.

Authoritative CLI entry point:

```toml
[project.scripts]
paperctl = "paperctl.cli:main"
```

Also keep `python -m paperctl` working through `__main__.py`. Omit a top-level `paperctl` script unless it adds real value.

Initial tree:

```text
.
├── AGENTS.md
├── handoffs.md
├── README.md
├── pyproject.toml
├── uv.lock
├── skills/
│   └── paper-build/
│       ├── SKILL.md
│       └── references/
│           └── milestone-1-workflow.md
├── src/
│   └── paperctl/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── discovery.py
│       ├── inventory.py
│       ├── normalize.py
│       ├── rendering.py
│       ├── audit.py
│       ├── build.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   └── *.schema.json
│       ├── adapters/
│       │   ├── __init__.py
│       │   ├── json_adapter.py
│       │   ├── yaml_adapter.py
│       │   ├── csv_adapter.py
│       │   ├── jsonl_adapter.py
│       │   ├── markdown_adapter.py
│       │   └── log_adapter.py
│       └── _support/
│           ├── __init__.py
│           ├── atomic.py
│           ├── hashing.py
│           ├── jsonio.py
│           ├── paths.py
│           ├── schema.py
│           └── fingerprints.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── minimal-research-repo/
│   ├── golden/
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_discovery.py
│   ├── test_inventory.py
│   ├── test_evidence.py
│   ├── test_rendering.py
│   ├── test_audit.py
│   ├── test_build.py
│   ├── test_schemas.py
│   └── test_fingerprints.py
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-06-25-milestone-1-deterministic-design.md
```

`uv.lock` is committed after dependency resolution, but it is generated rather than an authored design artifact.

Keep the existing `handoffs.md` casing unless it is deliberately renamed once. Do not refer to both `handoffs.md` and `HANDOFFS.md` on a case-sensitive filesystem.

## Skill

`skills/paper-build/SKILL.md` is a thin, explicitly invoked wrapper around the installed `paperctl` executable.

It should:

- explain that it builds a deterministic pre-analysis evidence draft;
- verify the intended repository;
- require existing `paper.yaml`;
- run or guide `paperctl --repo <repository-root> build`;
- fail clearly if `paperctl` is unavailable;
- report deterministic build status;
- report path to `PAPER.draft.md`;
- report path to the audit report;
- summarize publication blockers;
- state clearly that Milestone 1 never publishes `PAPER.md`;
- preserve research artifacts.

It should not:

- duplicate CLI implementation logic;
- locate and run source files directly;
- perform semantic interpretation;
- invoke LLM analysts or subagents;
- resolve evidence conflicts itself;
- silently run `paperctl init`;
- manually rewrite generated output.

## Fixture

Create one compact integration fixture with one question and approximately six experiments:

- completed experiment with validated `experiment_report.json` contract for `execution_status=completed`;
- explicitly mapped canonical facts;
- incomplete experiment with missing expected outputs;
- legacy experiment directory without modern metadata;
- stale README value beside a different structured value, proving Markdown numbers are excerpts rather than facts;
- separate structured conflict where two explicit sources claim different values for the same `fact_id`;
- smoke and full-run artifacts, with configuration explicitly selecting the full-run fact;
- unsupported binary artifact;
- JSONL and log artifacts that exceed deliberately low preview limits.

The fixture must be small and human-readable. Do not commit genuinely large generated artifacts.

Include a pre-existing sentinel `PAPER.md` and assert that every Milestone 1 command leaves its bytes unchanged.

## Tests

Copy the integration fixture into a temporary directory for each test. Tests must never modify committed fixtures or golden files.

Initialize the temporary fixture as a Git repository for Git-root resolution tests. Use explicit `--repo` in most stage tests.

Stage tests:

- config: defaults, strict unknown-key rejection, path safety;
- discovery: question/experiment detection, legacy names, path identity;
- inventory: full file listing, hashing, symlinks, unsupported files, bounds;
- evidence: JSON/YAML/CSV/JSONL adapters, markdown/log previews, canonical selectors, explicit conflicts, redaction;
- rendering: stable draft output, bounded tables/previews, escaped excerpts;
- audit: deterministic/publication behavior, blocker codes, no `PAPER.md` mutation;
- build: full fixture workflow and cache reuse/regeneration behavior.

Adapter unit tests stay separate from full-pipeline tests.

Edge-case tests use tiny temporary fixtures for:

- malformed JSON/YAML;
- prohibited YAML custom tags;
- invalid selectors;
- duplicate fact IDs;
- duplicate or ambiguous experiment references;
- path traversal;
- symlink escapes;
- non-finite numbers;
- stale prerequisites;
- extraction-limit boundaries.
- empty configured questions root;
- missing configured questions root;
- secret redaction in evidence packets and `PAPER.draft.md`.

Cache behavior tests:

- second unchanged build reuses outputs;
- changing one experiment regenerates only its inventory/evidence and downstream render/audit;
- adding an experiment invalidates discovery;
- changing renderer configuration leaves evidence reusable;
- `--force` regenerates the requested scope.
- forced regeneration from unchanged inputs produces the same bytes as reused cache output.

Golden artifacts:

- contain no absolute paths;
- contain no timestamps;
- contain no temporary-directory names;
- contain no platform-specific separators;
- use stable ordering;
- validate against schemas as part of tests.

Assert byte-identical output across two clean builds from identical fixture copies.

Verification commands:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Type checking is not an acceptance requirement unless a checker is adopted and configured.

## Non-Goals

Milestone 1 does not include:

- LLM calls;
- Codex workers;
- semantic interpretation;
- final paper publication;
- review or repair loops;
- technical editing;
- global canonical mappings;
- plugin marketplace packaging;
- experiment execution;
- network downloads;
- database or cache service;
- generic pipeline engine;
- automatic README correction;
- modification of source question, experiment, metadata, README, or output artifacts.

## Acceptance Summary

Milestone 1 succeeds when:

- every experiment directory is discovered;
- every experiment appears in the discovery-owned manifest with mirrored inventory/evidence artifact paths;
- status and disposition fields appear in evidence packets, not in the manifest;
- legacy names are included;
- structured evidence is inventoried and bounded without executing experiments;
- canonical facts require explicit contracts or selectors;
- smoke/full-run choice comes from explicit config, not heuristics;
- explicit conflicts are surfaced rather than resolved silently;
- generated JSON is schema-valid and deterministic;
- `PAPER.draft.md` is a bounded pre-analysis evidence draft;
- `PAPER.md` is never created, replaced, or modified;
- deterministic audit can pass;
- publication audit remains blocked with explicit blockers;
- cache reuse is correct but never hides source changes;
- generated evidence and drafts redact obvious secrets;
- all verification commands pass.
