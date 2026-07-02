---
name: paperium-writer
description: Use when running the Paperium V1 agent-led workflow that turns selected experiment run artifacts into a concise client-facing paper.
---

# Paperium Writer

Read `docs/superpowers/specs/2026-06-28-paperium-ai-writer-v1-design.md` before acting.

Workflow:
1. Run `paperium --repo <repo> init`.
2. Select experiments manually or with `paperium --repo <repo> select --experiments-menu`.
3. Use `paperium-analyze-experiments`, then run `paperium --repo <repo> analyze`.
4. Use `paperium-rank-findings`; produce or review `.paperium/ranking.json`, then run `paperium --repo <repo> rank`.
5. Review `.paperium/ranking.md`, `.paperium/dispositions.md`, and `.paperium/question-focus.md` with the user, then run `paperium --repo <repo> approve ranking` and `paperium --repo <repo> approve question-focus` after explicit approval.
6. Use `paperium-write-paper`; write each section to `.paperium/sections/<section-id>.md`. Continue only after user approval for each section.
7. Use `paperium-review-paper` during the section approval loop. Write `.paperium/sections/<section-id>.review.json` with `{"status": "passed", "findings": []}` or failed findings.
8. After review passes and the user approves, run `paperium --repo <repo> section approve <section-id> --title <title> --path .paperium/sections/<section-id>.md`.
9. Run `paperium --repo <repo> write` only after Paperium state gates are ready.

Rules:
- Never edit experiment `README.md`.
- Treat experiment/question READMEs as context only.
- Run artifacts, especially `outputs/`, are factual ground truth.
- Keep `PAPER.md` short and client-readable.
