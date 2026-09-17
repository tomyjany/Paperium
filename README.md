# Paperium

Turn existing experiment results into a report you can explain and check.
You choose the questions and useful findings; AI workers interpret and write;
Python tracks the files and assembles the report.

**Present the idea:** open [the summer challenge slides](docs/presentation/index.html)
in a browser. Arrow keys advance, `N` shows notes, and Print → Save as PDF exports
it. [Presenter instructions](docs/presentation/README.md) include sources and the
workflow trial.

## Status

Early and rough. The sections workbench (`init` → `section add/run/record/approve`
→ `assemble`) is the part that works end to end. `select`/`analyze`/`rank` exist but
are less exercised, and `src/paperctl/` is a rejected prototype kept only for reference.
Expect to read the code when something surprises you.

## Install

Requirements: Python 3.11+, `git`, [`uv`](https://docs.astral.sh/uv/), and at least one
model CLI on `PATH` (`codex` or `claude`, signed in). The CLI itself runs without them;
only `section run` and `analyze` shell out to a model.

```bash
git clone git@github.com:tomyjany/Paperium.git
cd Paperium
uv tool install .
paperium --help
```

`uv tool install .` puts `paperium` (and the legacy `paperctl`) on `PATH` via
`~/.local/bin`. If that directory is not on your `PATH`, run `uv tool update-shell`
and restart the shell. To upgrade later: `git pull && uv tool install --force .`.

Prefer not to install globally? Work from the checkout instead:

```bash
uv run paperium --help
```

Both forms are used interchangeably below; `uv run paperium` is the same program.

### Install instructions for a coding agent

Paste this into Claude Code, Codex, or a similar agent:

```text
Install Paperium for me.

1. Check that `git`, `uv`, and Python 3.11+ are available. If `uv` is missing,
   install it with: curl -LsSf https://astral.sh/uv/install.sh | sh
2. Clone https://github.com/tomyjany/Paperium into ~/src (or my usual code
   directory) and cd into it. Use the SSH remote
   git@github.com:tomyjany/Paperium.git if my SSH key is set up, otherwise HTTPS.
   The repo is currently private, so tell me if the clone is rejected.
3. Run `uv tool install .` from the checkout.
4. Verify with `paperium --help`. If the command is not found, run
   `uv tool update-shell`, then report which shell rc file needs reloading.
5. Report whether `codex` and/or `claude` are on PATH. Do not install or
   authenticate them; just tell me which are missing.
6. Do not run `paperium init` anywhere yet, and do not modify any repository
   other than the Paperium checkout.

Then read README.md and docs/paperium-workflow.md in the checkout and summarize
the first three commands I should run against my own research repository.
```

The agent only needs to clone and install. Pointing it at a research repository is a
separate, deliberate step — `paperium init` writes a `.paperium/` directory there.

## Start with one section

Once installed, run these from anywhere. Keep the target research repository
separate from this checkout.

1. Initialize the target and register a section:

   ```bash
   paperium --repo /path/to/research-repo init
   paperium --repo /path/to/research-repo section add findings --title "What we learned"
   ```

2. Fill `.paperium/sections/findings.facts.md` in the target with its purpose,
   checked facts, source paths/selectors, and limitations. Set the audience and
   language in `.paperium/style.md`.

3. Inspect the prompt, or start the writer:

   ```bash
   paperium --repo /path/to/research-repo section prompt findings
   paperium --repo /path/to/research-repo section run findings --backend codex
   ```

   `prompt` is local. `run` sends the prepared context to the named model CLI,
   which must be installed and signed in. The default backend is Claude.
   For a manual writer run, save its result to `.paperium/sections/findings.md`,
   then use `section record findings`.

4. Preview the report:

   ```bash
   paperium --repo /path/to/research-repo assemble --allow-draft
   ```

   Open `.paperium/REPORT.draft.md`. Add `/revision notes/` to the section and
   repeat the writing step as needed. Record manual edits. After reviewing the
   final text, use `section approve findings`, then `assemble` to produce
   `.paperium/REPORT.md`. PDF export is a separate step.

This writing-only start assumes you already have checked facts. For a new
corpus, follow the [evidence-to-report workflow](docs/paperium-workflow.md) first.
Omitting `--repo` resolves the current Git root.

## What gets checked

Paperium combines agent analysis, a separate agent fact-check, explicit
include/exclude/defer decisions, curated facts, and human review. Python checks
structured result shapes, managed write boundaries, file/state consistency,
section approvals, image presence, and assembly. Changed approved drafts must
be recorded and approved again. Failed and draft assemblies preserve the final report.

**V2 does not mechanically verify every number or claim in final prose.** Keep
sources/selectors in the evidence layer and check interpretation and comparisons.
The historical Datera report used interactive AI writing and manual assembly;
its old state does not certify a completed automated workflow.

## Repository map

| Location | Purpose |
|---|---|
| `src/paperium/`, `skills/paperium-*/` | Current evidence workflow and sections workbench |
| `docs/presentation/` | Offline slides, notes, verified examples, and trial record |
| `tests/paperium/` | Current workflow regression tests |
| `src/paperctl/`, `tests/test_*.py` | Earlier deterministic compiler prototype |
| `datera-instance` | Optional local link to a separate research repository |

The earlier `paperctl` paper-generation direction was
[rejected](docs/decisions/2026-06-27-reject-current-paperctl-concept.md).
It remains callable; its Milestone 1 build creates an evidence draft and audit,
never `PAPER.md`. The current writing contract is the
[V2 sections design](docs/superpowers/specs/2026-07-02-paperium-v2-sections-workbench-design.md).

## Development

```bash
uv run python -m pytest -q
uv run python -m ruff check .
uv run python -m ruff format --check .
```

`uv run` uses the checkout's own `.venv`, so it always tests the working tree,
not the copy installed by `uv tool install`.

If the default `uv` cache is read-only, set `UV_CACHE_DIR` to a writable directory.
Tests use fake workers and do not require live model calls.
