# Milestone 1 Workflow

Use this reference only after the `paper-build` skill is explicitly requested.

1. Resolve the target path to a Git repository root.
2. Verify `<repository-root>/paper.yaml` exists.
3. Run:

   ```bash
   paperctl --repo <repository-root> build
   ```

4. Read the command output for:

   - deterministic build status
   - `PAPER.draft.md` path
   - audit report path
   - publication blockers

5. Report those results without editing generated files.

Milestone 1 produces a deterministic evidence draft and audit report. It never writes `PAPER.md`.
