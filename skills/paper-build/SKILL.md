---
name: paper-build
description: Use when the user explicitly asks Codex to build a Milestone 1 paper draft with paperctl in a target research repository.
---

# Paper Build

This is a thin, explicitly invoked wrapper around the installed `paperctl` executable. Use only when explicitly requested. It builds a deterministic pre-analysis evidence draft from an initialized research repository.

## Workflow

1. Resolve the target Git repository root from the user's path or current working directory.
2. Confirm `paper.yaml` exists at that repository root; if it is missing, stop and ask before any initialization.
3. Run `paperctl --repo <repository-root> build`.
4. Do not manually alter generated artifacts after the command finishes.
5. Report the deterministic build status, draft path, audit path, and publication blockers from the command output.
6. State that Milestone 1 never writes `PAPER.md`.

## Boundaries

- Preserve research artifacts and avoid editing question or experiment content.
- Do not modify source metadata, README files, or output artifacts in the target repository.
- Do not duplicate discovery, extraction, rendering, caching, validation, or audit logic.
- Do not include schemas or adapter implementations in this skill.
- Do not perform semantic interpretation or resolve evidence conflicts manually.
- Do not run `paperctl init` unless the user explicitly asks for initialization.

For the concise command flow, see [milestone-1-workflow.md](references/milestone-1-workflow.md).
