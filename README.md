# codex-paper

`codex-paper` provides `paperctl`, a deterministic Python CLI for compiling
research-question and experiment artifacts into a pre-analysis evidence draft.

Milestone 1 discovers experiments, inventories artifacts, normalizes bounded
evidence, renders `PAPER.draft.md`, and writes `paper/PAPER.audit.json`.
Publication remains blocked in this milestone because semantic review is not
implemented. Milestone 1 never writes `PAPER.md`.

## CLI Usage

Install and run through `uv` from this repository:

```bash
uv run paperctl --help
```

Initialize a target research repository once:

```bash
uv run paperctl --repo /path/to/research-repo init
```

Build the deterministic draft and audit report:

```bash
uv run paperctl --repo /path/to/research-repo build
```

`build` runs discovery, inventory, normalization, rendering, and deterministic
audit. It reports the draft path, audit path, deterministic status, and
publication blockers. It does not edit research questions, experiments, source
artifacts, or `PAPER.md`.

Run publication audit explicitly when you need the publication gate result:

```bash
uv run paperctl --repo /path/to/research-repo audit --stage publication
```

In Milestone 1, deterministic audit can pass while publication audit remains
blocked. Failed validation writes `PAPER.draft.md` and the audit report for
review instead of creating a final paper.

When stdout is an interactive terminal, `build` and `audit` use Rich-formatted
human output. Redirected output stays plain, and plain output can be forced:

```bash
uv run paperctl --repo /path/to/research-repo build --plain
uv run paperctl --repo /path/to/research-repo audit --stage publication --plain
```

## Development

Run the smoke tests:

```bash
uv run pytest tests/test_cli.py -q
```

Run formatting checks:

```bash
uv run ruff check .
uv run ruff format --check .
```
