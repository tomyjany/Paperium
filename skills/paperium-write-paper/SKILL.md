---
name: paperium-write-paper
description: Use when writing Paperium paper sections after ranking and question focus are approved.
---

# Paperium Write Paper

Read `docs/superpowers/specs/2026-06-28-paperium-ai-writer-v1-design.md` before acting.

Write a short technical report, not an artifact dump. Write one section at a time to `.paperium/sections/<section-id>.md` and ask for user approval before continuing.

Numeric and factual claims must be supported by fact-check-approved experiment notes and run artifacts. After review passes and the user approves the section, run `paperium --repo <repo> section approve <section-id> --title <title> --path .paperium/sections/<section-id>.md`.

Do not write `PAPER.md` until Paperium state gates are ready. Experiment/question READMEs are context only, not factual authority.
