# codex-paper

`codex-paper` is a deterministic Python package for compiling research-question
and experiment artifacts into an evidence-grounded paper workflow.

Milestone 1 starts with the `paperctl` command-line interface and deterministic,
LLM-free tooling. Later stages will add discovery, inventory, normalization,
rendering, and audit behavior.

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
