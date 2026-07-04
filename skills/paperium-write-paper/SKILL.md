---
name: paperium-write-paper
description: Drive the Paperium V2 sections workbench; register sections, curate facts, run writers, iterate via notes, and assemble the final report.
---

You are using the paperium-write-paper skill.

PURPOSE

Drive the Paperium V2 sections workbench: register report sections ad hoc,
curate per-section facts, run writer workers, iterate via inline notes, and
assemble the final report.

WORKFLOW

1. Ensure the pipeline half is done: analyses fact-check-approved, ranking and
   question focus approved (`paperium status`).
2. Discuss report structure with the user. The user may keep a private outline
   file; never edit it. Register sections as they are decided:
   `paperium section add <id> --title "..." [--break-before]`.
3. For each section, curate `.paperium/sections/<id>.facts.md` with the user:
   purpose, what the section is NOT, whitelisted facts from approved
   `analysis.md` files, interpretation guardrails, optional structure skeleton.
4. Draft with `paperium section run <id>` (default). If the launcher blocks,
   fall back to `paperium section prompt <id>`, run the writer manually, save
   the section file, then `paperium section record <id>`.
5. The user adds inline `/.../` notes to drafts. Check them with
   `paperium section notes <id>`, then re-run `paperium section run <id>` —
   the revision prompt carries the notes and a fact-lock automatically.
6. When a revision note establishes a term or tone rule, propose adding it to
   `.paperium/style.md` (user approves). style.md is injected into every
   writer prompt.
7. Approve finished sections: `paperium section approve <id>`.
8. Assemble: `paperium assemble` (all sections approved) or
   `paperium assemble --allow-draft` for a preview at
   `.paperium/REPORT.draft.md`. PDF export happens outside Paperium.
9. If state and files drift, run `paperium reconcile` (add `--fix` to sync).

RULES

- Never edit the user's outline or hand-written structure files.
- Facts files contain only facts traceable to approved analyses.
- Do not hand-edit `.paperium/REPORT.md`; edit sections and re-assemble.
