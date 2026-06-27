# Reject Current Paperctl Concept

- Date: 2026-06-27
- Status: Accepted decision
- Scope: Current Milestone 1 through Milestone 3 paper generation concept

## Decision

Reject the current paperctl concept as the accepted architecture for generating the final paper.

The rejected concept is the current direction where deterministic evidence packets and exhaustive pre-analysis listings dominate the generated draft, and where later Codex analysis is built around feeding workers normalized evidence JSON instead of a concise, paper-oriented task.

## Rationale

The generated draft is too long, too noisy, and not useful as a paper. It includes too much artifact inventory detail and too little judgment about what matters.

Evidence packets are useful audit/debug artifacts, but they are not paper content. Treating them as the main semantic substrate makes the workflow harder to inspect and produces unreadable intermediate and draft output.

Codex workers should help interpret selected experiments and synthesize concise findings. The current concept underuses that capability by centering the workflow around large generated JSON/evidence dumps.

The desired output is a much shorter paper containing only important findings, limitations, and decision-relevant claims.

## Consequences

Do not continue extending the current M1-M3 architecture as the accepted design without a new architecture decision.

Treat the existing implementation as experimental and potentially disposable. Its deterministic discovery, inventory, evidence, and validation pieces may still be reused later, but the current paper-generation concept is rejected.

Future design work should start from the target paper experience: concise, curated, paper-first output. Detailed evidence should remain available for audit and validation, not become the paper body.

## Not Decided

This decision does not choose the replacement architecture.

This decision does not define a migration or removal plan for the current implementation.

This decision does not reject the goal of an evidence-grounded paper compiler; it rejects the current over-complicated concept and output shape.
