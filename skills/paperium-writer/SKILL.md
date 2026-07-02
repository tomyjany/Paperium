---
name: paperium-writer
description: Use when running the Paperium V2 agent-led workflow that turns selected experiment run artifacts into a concise client-facing paper via the sections workbench.
---

# Paperium Writer

Read `docs/superpowers/specs/2026-06-28-paperium-ai-writer-v1-design.md` before acting.

Workflow:
1. Run `paperium --repo <repo> init`.
2. Select experiments manually or with `paperium --repo <repo> select --experiments-menu`.
3. Use `paperium-analyze-experiments`, then run `paperium --repo <repo> analyze`.
4. Use `paperium-rank-findings`; produce or review `.paperium/ranking.json`, then run `paperium --repo <repo> rank`.
5. Review `.paperium/ranking.md`, `.paperium/dispositions.md`, and `.paperium/question-focus.md` with the user, then run `paperium --repo <repo> approve ranking` and `paperium --repo <repo> approve question-focus` after explicit approval.
6. Use `paperium-write-paper`; register sections via `paperium section add <id> --title "..."`, curate facts in `.paperium/sections/<id>.facts.md`, and drive the write-iterate-approve loop with `paperium section run/prompt/record/notes/approve <id>`.
7. When each section is approved, the facts lock and its draft becomes final.
8. Assemble the report: `paperium assemble` (all sections approved) or `paperium assemble --allow-draft` for a preview at `.paperium/REPORT.draft.md`.
9. PDF export happens outside Paperium.

Rules:
- Never edit experiment `README.md`.
- Treat experiment/question READMEs as context only.
- Run artifacts, especially `outputs/`, are factual ground truth.
- Keep `PAPER.md` short and client-readable.
