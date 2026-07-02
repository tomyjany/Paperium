---
name: paperium-review-paper
description: Use when reviewing Paperium paper sections for factual support, concise tone, and client readability.
---

# Paperium Review Paper

Read `docs/superpowers/specs/2026-06-28-paperium-ai-writer-v1-design.md` before acting.

Review generated sections against approved experiment notes and run artifacts. Keep tone professional, simple, and concise. Flag unsupported factual claims.

Write the canonical review result to `.paperium/sections/<section-id>.review.json` using `{"status": "passed", "findings": []}` for passed sections, or `{"status": "failed", "findings": [{"severity": "error", "claim": "...", "reason": "...", "artifact_path": "...", "selector": "..."}]}` for failures.

This skill supports the section approval loop; it does not add a separate final review gate in V1. Experiment/question READMEs are context only, not factual authority.
