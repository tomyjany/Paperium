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
paper/work/inventories/<experiment-ref>.json
paper/work/evidence/<experiment-ref>.json
paper/work/render-state.json
PAPER.draft.md
paper/PAPER.audit.json
```

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

`build` is deterministic orchestration only:

```text
discover
→ inventory/extract
→ normalize
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

`paper.yaml` is the only user-authored YAML file. It is parsed with safe YAML loading, custom tags are prohibited, and the parsed object is validated by `paper-config.schema.json`.

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
    maximum_scalar_candidates_per_file: 200
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
- `fact_id` values are unique within an experiment;
- units are explicitly configured or present in the source;
- units are never inferred from field names;
- missing files, invalid selectors, type mismatches, path escapes, or duplicate fact IDs are deterministic-health errors.

`default_canonical_artifacts` does not make every scalar canonical. `outputs/experiment_report.json` is authoritative only for fields defined by its versioned contract. Other canonical facts require explicit selector mappings.

Canonical mappings establish authoritative facts, not conclusions, inclusion, or headline importance.

## Discovery

Discovery reads the configured question root and pattern, then finds experiment directories under each question's configured experiments directory. Experiment names do not need an `expNNN-` prefix.

Identity is path-based, not inferred from directory names. Duplicate or ambiguous references are deterministic errors.

Every discovered experiment appears in the manifest with separate deterministic fields:

```text
preanalysis_disposition: analysis_candidate | blocked | needs_human_review
execution_status: completed | failed | incomplete | unknown
evidence_status: available | missing | unsupported | conflicting
reason_codes: [...]
```

Milestone 1 does not assign final labels such as `included`, `excluded_smoke_only`, or `excluded_superseded`.

`execution_status` is set only from explicit structured contracts or metadata. Otherwise it is `unknown`. Do not infer completion from README prose, filenames, or warning/error matches.

A failed execution is not automatically excluded. Failed experiments may still be `analysis_candidate` if sufficient artifacts exist.

## Inventory

Inventory records all regular files under each experiment directory, excluding only fixed infrastructure directories such as `.git`. Do not silently omit `work/` or unknown artifacts.

Each file record includes repository-relative POSIX path, file type, byte size, lowercase `sha256:<hex>` over exact file bytes, detected kind, and support status.

Symlinks are recorded without following them. Any symlink resolving outside the repository is rejected.

Inventory does not execute experiment scripts and does not mutate experiment content.

Unknown or binary files are inventoried but unsupported unless an explicit adapter exists.

## Normalize And Evidence Extraction

`normalize` reads inventories, runs bounded adapters, and writes evidence packets.

Initial adapters:

- JSON/YAML: scalar values with exact JSON Pointer paths, bounded by depth and candidate limits.
- CSV: schema, row count, selected rows, and basic numeric summaries.
- JSONL: streamed line count, schema/sample, head/tail, and bounded summaries.
- Markdown: headings and short escaped excerpts with line ranges.
- Logs: streamed head/tail plus fixed warning/error pattern matches with line numbers.
- Unknown/binary: inventory-only unsupported records.

`maximum_file_bytes` means maximum full-parse size. Streaming adapters may inspect larger logs and JSONL files for bounded previews, columns, matches, and summaries.

Markdown and log adapters produce previews and diagnostics, not candidate facts. Unstructured numbers must not become facts automatically.

Error and warning matches use a documented fixed pattern set. They are diagnostics, not proof of failed execution.

Evidence packets distinguish:

- canonical facts;
- candidate facts;
- previews;
- conflicts;
- unsupported artifacts;
- extraction warnings.

Each candidate fact retains:

- source path;
- selector or line range;
- raw value;
- parsed type;
- unit only when explicitly present or configured;
- source hash;
- extraction adapter;
- adapter version.

Conflict detection occurs only between sources explicitly claiming the same `fact_id` or contract field. Do not infer conflicts from similar field names.

Aggregate `evidence_status` deterministically:

- `missing`: no usable evidence artifacts;
- `unsupported`: artifacts exist, but none have supported extraction;
- `conflicting`: explicit canonical claims conflict;
- `available`: at least one usable evidence source and no canonical conflict.

Non-finite numbers such as NaN and Infinity are rejected.

## Selectors

Supported selectors in Milestone 1:

- JSON Pointer for JSON and YAML.
- Named row/column selectors for tabular data when explicit canonical mappings require them.

Selector failures are deterministic-health errors for canonical facts.

## Rendering

Rendering produces `PAPER.draft.md` only. It also writes `paper/work/render-state.json` to track render inputs and the draft hash.

The draft contains a prominent notice that it is a pre-analysis evidence draft and not a publishable paper.

For each question, render:

- question identity and source path;
- discovered experiments;
- pre-analysis disposition fields;
- candidate and canonical fact summaries;
- evidence conflicts;
- missing or unsupported evidence;
- known publication blockers.

For each experiment, render:

- experiment title/path identity;
- deterministic execution status when known;
- pre-analysis disposition;
- candidate/canonical fact table;
- source artifact paths/selectors;
- conflicts and warnings.

Do not render interpretation, meaning, conclusions, recommendations, semantic verdicts, deterministic comparison tables that imply meaning, or placeholder sections such as "interpretation unavailable."

Keep the draft bounded. Render canonical facts and a configured subset of candidate facts/previews, then report omitted counts and point to the complete evidence packet.

Escape untrusted artifact text before inserting excerpts into Markdown.

Avoid a render/audit dependency cycle. `render` derives a "Known publication blockers" section directly from the manifest and evidence packets. Audit later validates that section.

Stable ordering is mandatory for questions, experiments, facts, warnings, and blockers. Do not emit timestamps.

## Audit

Audit writes `paper/PAPER.audit.json`.

It reports two independent result groups:

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

`publishable` is derived from gate results and must not be treated as an independent manually written truth.

Deterministic health checks:

- schema validity;
- prerequisite freshness;
- path safety;
- resolved provenance;
- source hashes;
- canonical selector validity;
- explicit conflict records;
- truncation warnings;
- every experiment represented in the manifest;
- draft determinism by rendering again to a temporary buffer and comparing bytes or hashes.

Distinguish:

- deterministic implementation/configuration errors;
- unresolved evidence blockers;
- informational warnings.

A correctly recorded evidence conflict or truncation warning is not itself a deterministic pipeline failure.

Publication blockers include:

```text
analysis_candidate  → missing_semantic_analysis
blocked             → unresolved_preanalysis_blocker
needs_human_review  → needs_human_review
conflicting evidence → unresolved_evidence_conflict
missing/unsupported evidence without final disposition → unresolved_evidence_blocker
```

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

Hashes are lowercase `sha256:<hex>` over exact bytes. Normalized configuration hashes use canonical JSON serialization, not original YAML formatting.

Avoid self-referential hashes. An artifact must not include a hash of its own complete bytes. Its fingerprint records inputs; downstream artifacts hash the completed artifact file.

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
- run or guide `paperctl build --repo <repository-root>`;
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

- completed experiment with explicit metadata or validated contract for `execution_status=completed`;
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
- evidence: JSON/YAML/CSV/JSONL adapters, markdown/log previews, canonical selectors, explicit conflicts;
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

Cache behavior tests:

- second unchanged build reuses outputs;
- changing one experiment regenerates only its inventory/evidence and downstream render/audit;
- adding an experiment invalidates discovery;
- changing renderer configuration leaves evidence reusable;
- `--force` regenerates the requested scope.

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
- every experiment appears in the manifest with deterministic pre-analysis fields;
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
- all verification commands pass.
