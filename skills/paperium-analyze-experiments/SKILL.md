---
name: paperium-analyze-experiments
description: Use when analyzing selected Paperium experiments or running their Codex analysis and fact-check loop.
---

# Paperium Analyze Experiments

Read `docs/superpowers/specs/2026-06-28-paperium-ai-writer-v1-design.md` before acting.

Use `paperium --repo <repo> analyze` for selected experiments. Do not edit experiment READMEs.

Experiment/question READMEs are context only. Ground truth comes from run artifacts, especially `outputs/`. Experiments without usable run artifacts become `artifact_missing` and `needs_human_review`.
