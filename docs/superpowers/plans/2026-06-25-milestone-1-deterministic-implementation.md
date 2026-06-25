# Milestone 1 Deterministic Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, LLM-free Milestone 1 `paperctl` framework that discovers experiments, inventories artifacts, normalizes evidence, renders `PAPER.draft.md`, and audits publication blockers without ever modifying `PAPER.md`.

**Architecture:** Use a small `uv` Python package with explicit stage modules: config, discovery, inventory, normalize, rendering, audit, and build orchestration. Generated machine artifacts are deterministic JSON validated by packaged schemas; `paper.yaml` is the only framework config YAML. `manifest.json` is discovery-owned and immutable after discovery; per-experiment inventory/evidence artifacts own later stage state.

**Tech Stack:** Python 3.11+, `uv`, `pytest`, `ruff`, `jsonschema`, `PyYAML`, standard-library `argparse`, `csv`, `json`, `hashlib`, `pathlib`, `tempfile`, and `importlib.resources`.

---

The header's subagent reference is implementation-process guidance from the planning skill. The Milestone 1 product must not implement or invoke LLM workers, subagents, semantic analysis, review agents, or recursive delegation.

Spec: `docs/superpowers/specs/2026-06-25-milestone-1-deterministic-design.md`

Implementation skills: @superpowers:test-driven-development, @superpowers:verification-before-completion.

## File Structure

Create:

- `README.md`: CLI usage, Milestone 1 scope, verification commands.
- `pyproject.toml`: package metadata, `paperctl` console script, dependencies, ruff/pytest config.
- `src/paperctl/__init__.py`: package version.
- `src/paperctl/__main__.py`: `python -m paperctl` entry point.
- `src/paperctl/cli.py`: argparse CLI, exit-code mapping, command dispatch.
- `src/paperctl/config.py`: safe YAML loading, defaults, strict validation, repo resolution.
- `src/paperctl/discovery.py`: discovery-owned manifest creation and freshness.
- `src/paperctl/inventory.py`: per-experiment inventory artifacts, symlink and kind detection.
- `src/paperctl/normalize.py`: evidence packet creation, adapters, statuses, blocker inputs.
- `src/paperctl/rendering.py`: bounded `PAPER.draft.md` plus `render-state.json`.
- `src/paperctl/audit.py`: deterministic health and publication gate audit.
- `src/paperctl/build.py`: deterministic stage orchestration.
- `src/paperctl/adapters/__init__.py`: explicit adapter list.
- `src/paperctl/adapters/json_adapter.py`: JSON scalar observations and canonical selectors.
- `src/paperctl/adapters/yaml_adapter.py`: safe YAML scalar observations and canonical selectors.
- `src/paperctl/adapters/csv_adapter.py`: bounded CSV previews and numeric diagnostics.
- `src/paperctl/adapters/jsonl_adapter.py`: streamed JSONL previews and diagnostics.
- `src/paperctl/adapters/markdown_adapter.py`: heading/excerpt previews.
- `src/paperctl/adapters/log_adapter.py`: head/tail and fixed warning/error diagnostics.
- `src/paperctl/_support/__init__.py`: helper package marker.
- `src/paperctl/_support/atomic.py`: atomic text/JSON writes.
- `src/paperctl/_support/fingerprints.py`: stage fingerprints and freshness comparison.
- `src/paperctl/_support/hashing.py`: byte and canonical JSON hashes.
- `src/paperctl/_support/jsonio.py`: deterministic JSON encode/decode.
- `src/paperctl/_support/paths.py`: repo-relative POSIX path safety.
- `src/paperctl/_support/redaction.py`: fixed secret redaction.
- `src/paperctl/_support/schema.py`: schema loading and validation.
- `src/paperctl/_support/sorting.py`: canonical sort keys.
- `src/paperctl/schemas/__init__.py`: schema package marker.
- `src/paperctl/schemas/paper-config.schema.json`
- `src/paperctl/schemas/manifest.schema.json`
- `src/paperctl/schemas/artifact-inventory.schema.json`
- `src/paperctl/schemas/evidence-packet.schema.json`
- `src/paperctl/schemas/render-state.schema.json`
- `src/paperctl/schemas/paper-audit.schema.json`
- `src/paperctl/schemas/experiment-report.schema.json`
- `skills/paper-build/SKILL.md`: thin explicit wrapper around installed `paperctl`.
- `skills/paper-build/references/milestone-1-workflow.md`: concise workflow reference.
- `tests/conftest.py`: copied fixture repos and CLI helpers.
- `tests/fixtures/minimal-research-repo/...`: compact fixture with one question and six experiments.
- `tests/golden/...`: stable golden JSON/Markdown outputs.
- `tests/test_cli.py`
- `tests/test_config.py`
- `tests/test_discovery.py`
- `tests/test_inventory.py`
- `tests/test_evidence.py`
- `tests/test_rendering.py`
- `tests/test_audit.py`
- `tests/test_build.py`
- `tests/test_schemas.py`
- `tests/test_fingerprints.py`

Existing files:

- Keep `handoffs.md` casing unchanged.
- Do not modify source experiment artifacts except when creating committed test fixtures.
- Do not create, replace, or edit any target `PAPER.md` during framework commands.

## Chunk 1: Deterministic Milestone 1 Vertical Slice

### Task 1: Project Scaffold And Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `README.md`
- Create: `src/paperctl/__init__.py`
- Create: `src/paperctl/__main__.py`
- Create: `src/paperctl/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI smoke tests**

Add tests in `tests/test_cli.py`:

```python
import subprocess
import sys


def test_module_entrypoint_shows_help():
    result = subprocess.run(
        [sys.executable, "-m", "paperctl", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout


def test_console_script_shows_help():
    result = subprocess.run(
        ["paperctl", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert "paperctl" in result.stdout
```

- [ ] **Step 2: Run tests and verify failure**

Run: `uv run pytest tests/test_cli.py -q`

Expected: fails because the package and `paperctl` entry point do not exist.

- [ ] **Step 3: Add minimal package scaffold**

Add `pyproject.toml` with:

```toml
[project]
name = "codex-paper"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "jsonschema>=4.0",
  "PyYAML>=6.0",
]

[project.scripts]
paperctl = "paperctl.cli:main"

[dependency-groups]
dev = [
  "pytest>=8.0",
  "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100

[tool.ruff.format]
quote-style = "double"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Implement `src/paperctl/cli.py` with `argparse`, command placeholders, and exit constants:

```python
SUCCESS = 0
DETERMINISTIC_FAILURE = 2
PUBLICATION_BLOCKED = 3
INVALID_INVOCATION = 4
MISSING_DEPENDENCY = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paperctl")
    parser.add_argument("--repo", default=None)
    subparsers = parser.add_subparsers(dest="command", required=False)
    for name in ["init", "discover", "inventory", "normalize", "render", "build"]:
        command = subparsers.add_parser(name)
        command.add_argument("--force", action="store_true")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--stage", choices=["deterministic", "publication"], default=None)
    audit.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return SUCCESS
    parser.error(f"command not implemented yet: {args.command}")
    return INVALID_INVOCATION
```

Add `src/paperctl/__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

- [ ] **Step 4: Run smoke tests**

Run: `uv run pytest tests/test_cli.py -q`

Expected: PASS for help tests.

- [ ] **Step 5: Run formatting checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
```

Expected: PASS.

- [ ] **Step 6: Commit scaffold**

```bash
git add pyproject.toml README.md src/paperctl tests/test_cli.py
git commit -m "Add paperctl package scaffold"
```

### Task 2: Schemas And Deterministic JSON Helpers

**Files:**
- Create: `src/paperctl/schemas/*.schema.json`
- Create: `src/paperctl/schemas/__init__.py`
- Create: `src/paperctl/_support/__init__.py`
- Create: `src/paperctl/_support/jsonio.py`
- Create: `src/paperctl/_support/schema.py`
- Create: `src/paperctl/_support/hashing.py`
- Create: `tests/test_schemas.py`

- [ ] **Step 1: Write failing schema/helper tests**

Cover:

- packaged schemas load through `importlib.resources`;
- deterministic JSON output has sorted keys and trailing newline;
- non-finite numbers are rejected;
- byte hashes use `sha256:<hex>`;
- canonical JSON config hash ignores YAML formatting differences.

Run: `uv run pytest tests/test_schemas.py -q`

Expected: FAIL because helpers/schemas do not exist.

- [ ] **Step 2: Add minimal schemas**

Create schemas named in the spec with required top-level `schema_version` and `artifact_type` for generated artifacts. Keep schemas strict with `additionalProperties: false` where the artifact shape is known.

Important schema requirements:

- `manifest.schema.json`: no status/disposition fields; entries include question path/hash and mirrored artifact paths.
- `evidence-packet.schema.json`: status/disposition fields, closed `reason_codes`, counts, canonical facts, observed values, previews, diagnostics, conflicts, unsupported artifacts, warnings.
- `experiment-report.schema.json`: recognized source contract with `schema_version`, optional `execution_status`, and `canonical_facts`.

- [ ] **Step 3: Implement helpers**

Implement:

- `dump_json_bytes(obj) -> bytes`
- `write_json_atomic(path, obj)` later delegated to atomic helper but deterministic encoding lives here.
- `sha256_file(path) -> str`
- `sha256_bytes(data) -> str`
- `canonical_json_hash(obj) -> str`
- `load_schema(name) -> dict`
- `validate_artifact(name, obj) -> None`

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_schemas.py -q`

Expected: PASS.

- [ ] **Step 5: Commit schemas/helpers**

```bash
git add src/paperctl/schemas src/paperctl/_support tests/test_schemas.py
git commit -m "Add deterministic JSON schemas and helpers"
```

### Task 3: Config Loading, Repo Resolution, And Init

**Files:**
- Create: `src/paperctl/config.py`
- Create: `src/paperctl/_support/paths.py`
- Create: `src/paperctl/_support/atomic.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing config tests**

Test:

- safe YAML parsing rejects custom tags;
- unknown keys fail validation;
- defaults match the spec;
- all configured paths are repo-relative;
- absolute paths and `..` escapes fail;
- omitted `--repo` resolves Git root;
- omitted `--repo` outside Git exits category 4;
- `paperctl init` creates only `paper.yaml` and `paper/work/{inventories,evidence,cache}`;
- `init --force` replaces only `paper.yaml`.

Run: `uv run pytest tests/test_config.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement config API**

Implement:

- `resolve_repo(repo_arg: str | None, cwd: Path) -> Path`
- `default_config() -> dict`
- `load_config(repo: Path) -> dict`
- `validate_config(config: dict, repo: Path) -> dict`
- `init_repo(repo: Path, force: bool) -> InitResult`

Use `subprocess.run(["git", "rev-parse", "--show-toplevel"])` without shell.

- [ ] **Step 3: Wire CLI `init`**

`paperctl --repo <path> init` must:

- fail if repo cannot be resolved;
- create config/work directories;
- not create `PAPER.md` or `PAPER.draft.md`;
- print created paths;
- return 0 on success.

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/test_config.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit config/init**

```bash
git add src/paperctl/config.py src/paperctl/_support/paths.py src/paperctl/_support/atomic.py src/paperctl/cli.py tests/test_config.py
git commit -m "Add config loading and init command"
```

### Task 4: Fixture Repository And Test Helpers

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/fixtures/minimal-research-repo/...`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Create fixture skeleton**

Add one question:

```text
tests/fixtures/minimal-research-repo/
├── paper.yaml
├── PAPER.md
└── questions/
    └── q001-throughput/
        ├── README.md
        └── experiments/
            ├── exp001-completed/
            ├── exp002-incomplete/
            ├── legacy-baseline/
            ├── exp003-structured-conflict/
            ├── exp004-smoke-and-full/
            └── exp005-unsupported-and-previews/
```

Include:

- sentinel `PAPER.md` content;
- explicit `experiment_report.json` in completed experiment;
- stale README number in one experiment;
- structured conflict with two valid canonical sources for same `fact_id`;
- smoke and full files with config selecting full fact;
- unsupported binary;
- small JSONL/log exceeding deliberately low limits;
- one obvious secret in a file for redaction tests.

- [ ] **Step 2: Add fixture helpers**

In `tests/conftest.py`, implement:

- `copy_fixture_repo(tmp_path) -> Path`
- `init_git_repo(path) -> None`
- `run_paperctl(repo, *args) -> subprocess.CompletedProcess`
- `read_json(path) -> dict`

- [ ] **Step 3: Assert fixture safety**

Add tests that copied fixture is mutated, not committed fixture. Assert sentinel `PAPER.md` starts with known bytes.

- [ ] **Step 4: Run fixture helper tests**

Run: `uv run pytest tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit fixture**

```bash
git add tests/conftest.py tests/fixtures tests/test_config.py
git commit -m "Add minimal research repository fixture"
```

### Task 5: Discovery Manifest

**Files:**
- Create: `src/paperctl/discovery.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_discovery.py`

- [ ] **Step 1: Write failing discovery tests**

Test:

- missing configured questions root is deterministic failure;
- existing root with zero experiments writes empty manifest;
- all fixture experiments are discovered, including legacy names;
- manifest entries include `question_readme_path` and `question_readme_sha256`;
- manifest entries include mirrored `inventory_path` and `evidence_path`;
- manifest has no `preanalysis_disposition`, `execution_status`, `evidence_status`, or `reason_codes`;
- byte-identical discovery output across two clean fixture copies.

Run: `uv run pytest tests/test_discovery.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement discovery**

Implement `discover(repo, config, force=False) -> ManifestResult`.

Manifest output:

```text
paper/work/manifest.json
```

Rules:

- sort by question path then experiment path;
- use POSIX repo-relative paths;
- compute README hash when present;
- mirror generated inventory/evidence paths;
- fingerprint directory entries and relevant config.

- [ ] **Step 3: Wire CLI `discover`**

`paperctl --repo <path> discover [--force]` loads config and writes manifest only.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_discovery.py tests/test_config.py -q`

Expected: PASS.

- [ ] **Step 5: Commit discovery**

```bash
git add src/paperctl/discovery.py src/paperctl/cli.py tests/test_discovery.py
git commit -m "Add discovery manifest stage"
```

### Task 6: Inventory Stage

**Files:**
- Create: `src/paperctl/inventory.py`
- Create: `src/paperctl/_support/fingerprints.py`
- Create: `src/paperctl/_support/sorting.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_inventory.py`
- Modify: `tests/test_fingerprints.py`

- [ ] **Step 1: Write failing inventory tests**

Test:

- command fails clearly when manifest is missing/stale;
- every regular file and symlink is recorded;
- exact exclusion list is honored;
- symlinks are not followed;
- inert external symlink is unsupported, not global health failure;
- canonical/configured symlink escape is later rejected;
- fixed extension map classifies known kinds;
- unknown binary is unsupported;
- inventory fingerprint detects additions, deletions, type changes, and content changes.

Run: `uv run pytest tests/test_inventory.py tests/test_fingerprints.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement fingerprints**

Implement shared structure with:

- stage name/version;
- relevant config hash;
- source file paths/hashes;
- prerequisite artifact hashes;
- schema version.

Freshness checks must validate prerequisite schemas first.

- [ ] **Step 3: Implement inventory**

Implement `inventory_all(repo, config, manifest, force=False)` and `inventory_one(...)`.

Write one inventory JSON per manifest entry at manifest-recorded path.

- [ ] **Step 4: Wire CLI `inventory`**

`paperctl --repo <path> inventory [--force]` reads manifest and writes only inventories.

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/test_inventory.py tests/test_fingerprints.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit inventory**

```bash
git add src/paperctl/inventory.py src/paperctl/_support/fingerprints.py src/paperctl/_support/sorting.py src/paperctl/cli.py tests/test_inventory.py tests/test_fingerprints.py
git commit -m "Add artifact inventory stage"
```

### Task 7: Evidence Adapters And Normalize Stage

**Files:**
- Create: `src/paperctl/normalize.py`
- Create: `src/paperctl/adapters/*.py`
- Create: `src/paperctl/_support/redaction.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_evidence.py`

- [ ] **Step 1: Write failing evidence tests**

Test:

- JSON/YAML scalar observations with JSON Pointer selectors;
- canonical selectors bypass observation limits;
- validated report canonical facts are not duplicated as observed values;
- report value/selector mismatch blocks with `source_contract_value_mismatch`;
- malformed recognized `experiment_report.json` blocks with `malformed_experiment_report`;
- unknown report version blocks with `unknown_experiment_report_version`;
- missing default report does not block by itself;
- distinct valid canonical declarations disagreeing on normalized value/type/unit create `canonical_conflict`;
- distinct declarations with same value/type/unit but different provenance do not conflict;
- user-authored `paper.yaml` `canonical_facts` missing files, invalid selectors, type mismatches, duplicate fact IDs, path escapes, and unsafe symlink escapes are deterministic-health/configuration errors rather than experiment evidence blockers;
- preview-only Markdown/log evidence can produce `available` and `analysis_candidate`;
- CSV/JSONL numeric summaries are diagnostics/previews, not observed values;
- secret-like values are redacted from evidence packets.

Run: `uv run pytest tests/test_evidence.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement adapters explicitly**

Adapters return normalized records, not markdown:

- JSON/YAML adapters: observed scalar values and canonical selector resolution.
- CSV/JSONL adapters: bounded previews and numeric diagnostics only.
- Markdown/log adapters: escaped previews and diagnostics only.
- Unknown/binary: unsupported records.

- [ ] **Step 3: Implement redaction**

Use fixed assignment-style patterns for keys containing:

```text
password, passwd, secret, token, api_key, apikey, access_key, private_key
```

Replace sensitive values with `[REDACTED]` and record redaction counts.

- [ ] **Step 4: Implement normalize**

Write one evidence packet per manifest entry at manifest-recorded path.

Evidence packet owns:

- `preanalysis_disposition`;
- `execution_status`;
- `evidence_status`;
- closed `reason_codes`;
- counts;
- canonical facts;
- observed values;
- previews;
- diagnostics;
- conflicts;
- unsupported artifacts;
- warnings.

- [ ] **Step 5: Wire CLI `normalize`**

`paperctl --repo <path> normalize [--force]` reads manifest and inventories, then writes only evidence packets.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_evidence.py tests/test_inventory.py -q`

Expected: PASS.

- [ ] **Step 7: Commit normalize**

```bash
git add src/paperctl/normalize.py src/paperctl/adapters src/paperctl/_support/redaction.py src/paperctl/cli.py tests/test_evidence.py
git commit -m "Add evidence normalization stage"
```

### Task 8: Rendering And Render State

**Files:**
- Create: `src/paperctl/rendering.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_rendering.py`

- [ ] **Step 1: Write failing render tests**

Test:

- render fails if manifest, inventory, or evidence packets are missing/stale;
- draft contains pre-analysis notice;
- draft renders question identity and README path/hash;
- draft renders evidence-packet statuses and bounded canonical/observed/preview sections;
- draft uses shared publication blocker derivation;
- draft does not contain interpretation, rankings, ratios, "best" claims, semantic comparison tables, or placeholder interpretation sections;
- CSV/JSONL numeric diagnostics appear only in preview/diagnostic sections, never as canonical facts or observed values;
- untrusted excerpts are escaped;
- obvious secrets are redacted;
- render writes `paper/work/render-state.json`;
- render never creates or modifies `PAPER.md`;
- two renders from identical inputs are byte-identical.

Run: `uv run pytest tests/test_rendering.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement blocker derivation helper**

Place helper in `src/paperctl/audit.py` or a small shared module only if needed by both render and audit. It must:

- handle zero manifest experiments as `no_experiments_discovered`;
- use evidence-packet status fields;
- apply precedence/deduplication;
- sort by question path, experiment path, priority, code.

- [ ] **Step 3: Implement renderer**

Render:

- all canonical facts;
- up to 20 observed values;
- up to 10 previews;
- up to 20 diagnostics;
- up to 20 warnings;
- up to 20 unsupported artifacts.

Report omitted counts and evidence packet path.

- [ ] **Step 4: Wire CLI `render`**

`paperctl --repo <path> render [--force]` writes draft and render state only.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_rendering.py tests/test_evidence.py -q`

Expected: PASS.

- [ ] **Step 6: Commit rendering**

```bash
git add src/paperctl/rendering.py src/paperctl/cli.py tests/test_rendering.py
git commit -m "Add deterministic draft rendering"
```

### Task 9: Audit Stage

**Files:**
- Create: `src/paperctl/audit.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_audit.py`

- [ ] **Step 1: Write failing audit tests**

Test:

- audit always computes deterministic health and publication gate groups;
- `publishable` is derived;
- deterministic audit passes with recorded experiment blockers;
- publication audit exits code 3 when blocked;
- publication blockers emit at most one primary blocker per experiment with precedence `needs_human_review`, `blocked`, `analysis_candidate`;
- publication blockers emit at most one evidence-status blocker per experiment ordered `conflicting`, `missing`, `unsupported`;
- publication blockers are deterministically sorted and do not contain duplicate codes for the same experiment;
- zero experiments produce `no_experiments_discovered`;
- missing questions root is deterministic failure;
- every manifest experiment must have fresh inventory and evidence at recorded paths;
- audit validates draft determinism by rendering to a buffer;
- audit never modifies `PAPER.md`.

Run: `uv run pytest tests/test_audit.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement audit**

Implement:

- `audit(repo, config, stage) -> AuditResult`;
- deterministic-health issue classification;
- publication blockers through shared helper;
- JSON report at configured path;
- exit-code mapping in CLI.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_audit.py tests/test_rendering.py -q`

Expected: PASS.

- [ ] **Step 4: Commit audit**

```bash
git add src/paperctl/audit.py src/paperctl/cli.py tests/test_audit.py
git commit -m "Add deterministic audit stage"
```

### Task 10: Build Orchestration And Cache Behavior

**Files:**
- Create: `src/paperctl/build.py`
- Modify: `src/paperctl/cli.py`
- Create: `tests/test_build.py`

- [ ] **Step 1: Write failing build/cache tests**

Test:

- `paperctl build` requires existing valid `paper.yaml`;
- build runs discover, inventory, normalize, render, deterministic audit;
- build exits 0 when deterministic pipeline passes, even though publication is blocked;
- build prints final status with draft and audit paths;
- second unchanged build reuses outputs;
- changing one experiment regenerates only that experiment inventory/evidence plus render/audit;
- adding an experiment invalidates discovery;
- changing renderer config leaves evidence reusable;
- `--force` regenerates requested scope;
- forced regeneration from unchanged inputs equals reused output bytes.

Run: `uv run pytest tests/test_build.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement build orchestration**

`build(repo, force=False)` calls Python APIs directly:

```text
discover
inventory
normalize
render
audit --stage deterministic
```

It also writes the full audit report including publication blockers.

- [ ] **Step 3: Wire CLI `build`**

Ensure output includes:

```text
deterministic build: passed
draft: PAPER.draft.md
publication: blocked by ...
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_build.py tests/test_audit.py -q`

Expected: PASS.

- [ ] **Step 5: Commit build**

```bash
git add src/paperctl/build.py src/paperctl/cli.py tests/test_build.py
git commit -m "Add deterministic build orchestration"
```

### Task 11: Skill Wrapper And Documentation

**Files:**
- Create: `skills/paper-build/SKILL.md`
- Create: `skills/paper-build/references/milestone-1-workflow.md`
- Modify: `README.md`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing documentation smoke tests**

Add tests that:

- skill file exists;
- skill uses explicit invocation language;
- skill references installed `paperctl`;
- skill does not mention LLM analysis, subagents, or `PAPER.md` promotion.

Run: `uv run pytest tests/test_cli.py -q`

Expected: FAIL.

- [ ] **Step 2: Add skill and docs**

`SKILL.md` should instruct:

```text
1. Resolve target repository.
2. Confirm paper.yaml exists.
3. Run paperctl --repo <repository-root> build.
4. Do not manually alter generated artifacts.
5. Report deterministic status, draft path, audit path, and blockers.
6. Never create or promote PAPER.md during Milestone 1.
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_cli.py -q`

Expected: PASS.

- [ ] **Step 4: Commit skill/docs**

```bash
git add README.md skills tests/test_cli.py
git commit -m "Add paper-build skill wrapper"
```

### Task 12: Golden Outputs And Final Verification

**Files:**
- Create/Update: `tests/golden/...`
- Modify: relevant tests to compare golden outputs.
- Generated: `uv.lock`

- [ ] **Step 1: Add golden comparison tests**

Golden outputs must cover:

- manifest;
- selected inventory;
- selected evidence packet;
- render state;
- `PAPER.draft.md`;
- audit report.

Assert no absolute paths, timestamps, temp names, platform separators, unredacted secrets, or unstable ordering.

- [ ] **Step 2: Generate golden outputs from fixture copy**

Run the implemented pipeline against a temporary fixture copy and copy stable outputs into `tests/golden/`.

- [ ] **Step 3: Verify full test suite**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected: all pass.

- [ ] **Step 4: Inspect git status**

Run: `git status --short`

Expected: only intended implementation, test, fixture, golden, and lockfile changes.

- [ ] **Step 5: Commit final verification artifacts**

```bash
git add tests/golden uv.lock
git commit -m "Add milestone 1 golden verification"
```

- [ ] **Step 6: Final acceptance run**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Expected: all pass with no uncommitted generated changes.
