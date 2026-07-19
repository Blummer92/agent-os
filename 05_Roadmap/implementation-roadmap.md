# Agent OS Implementation Roadmap

## Purpose

This is the durable outcome roadmap for Agent OS Implementation Phase 1. GitHub
issues remain the work-tracking surface, while active child roadmaps own their
local contracts and dependency order.

This roadmap does not authorize implementation, merge, scheduling, concurrency, or external writes.

## Portfolio Interpretation

Agent OS now evaluates work across four separate dimensions:

| Dimension | Meaning |
|---|---|
| Program priority | Relative value across the active portfolio |
| Issue readiness | Whether the issue is sufficiently defined and unblocked |
| Implementation authorization | Whether the operator approved the exact repository change |
| Execution safety | Whether current evidence permits bounded execution |

A favorable result in one dimension never implies a favorable result in another.
PP0 / #333 owns the planning contract for this separation.

## Current Status — 2026-07-19

| Milestone | Status | Current interpretation |
|---|---|---|
| M1 — Trustworthy Foundation | Complete | #106–#110, #122, and #123 are closed completed. Validation and packaging foundations exist. |
| M2 — Unified Connectors | Nearly complete | #111–#114 are complete. #115 remains the final open clarification/shim issue. |
| M3 — First Classroom Artifact | Re-sequenced | #116 is ready but not authorized. #117 needs contract reconciliation. #118–#121 are dependency-blocked. |
| M4 — Hygiene | Deferred unless blocking | #124 is ready; #125 remains blocked. Hygiene must not outrank active reliability or orchestration foundations without a recorded reason. |

Implementation Phase 1 still targets one governed classroom artifact, but that outcome must consume the newer planning, authorization, capability, and Scheduler contracts rather than bypass them.

## Active Program Portfolio

| Track | Canonical owner | Portfolio role |
|---|---|---|
| This roadmap | Integration Manager | Outcome roadmap for Phase 1 and classroom value |
| DOC0 / #304 | Integration Manager | Documentation lifecycle and report-only rollout |
| IDB0 / #261 | Integration Manager | Issue planning, authority, approval, and draft lifecycle |
| GEX0 / #266 | Integration Manager | Execution-environment capability and preflight evidence |
| WSC0 / #330 | Integration Manager | Safe Scheduler ingestion and concurrency ladder |
| PP0 / #333 | Integration Manager | Cross-roadmap prioritization and issue-recommendation contract |
| Branch protection / #231 | GitHub Service Agent | Independent repository-protection track |

Local roadmap owners remain authoritative for their own sequencing. PP0 may rank work across tracks, but it may not replace local contracts, readiness decisions, approval ownership, or execution gates.

## Current Recommended Sequence

1. Complete PP0 / #333 planning so portfolio recommendations use one explainable contract.
2. Treat WSC1 / #331 as the highest-priority implementation candidate, but begin only after separate explicit approval.
3. Treat WSC2 / #332 as ready planning that follows or coordinates with WSC1 while keeping work in progress low.
4. Keep C1 / #116 as `do-after-current`; it is a bounded documentation prerequisite and remains unauthorized.
5. Reconcile C2 / #117 with WSC0, IDB0, GEX0, and #88 before implementation.
6. Keep C3–C6 / #118–#121 blocked until their recorded predecessors and approval boundaries are satisfied.
7. Complete B5 / #115, M4 hygiene, and other independent tracks when they unblock active work or receive a higher PP0 recommendation.

## Classroom Artifact Chain

```text
#116 OAuth and approved-destination runbook
  -> #117 Scheduler task-spec reconciliation
  -> #118 no-write dry-run proof
  -> #119 separately authorized live artifact run
     |-> #120 sanitized example workflow
     `-> #121 evidence-based repeatable recipe
```

No issue in this chain may infer live-write authorization from readiness, program
priority, a dry-run pass, or the existence of an approved destination.

## Issue and Label Rules

- Use exactly one `owner:*` label for the primary owner.
- Record supporting agents in the issue body unless a governed support-label taxonomy is approved.
- `status:ready` means sufficiently defined and unblocked; it never means implementation is authorized.
- Program-priority recommendations are advisory evidence only.
- Blocked and `needs-decision` issues must record the exact dependency or unresolved decision.
- New issues should be created just in time and only after overlap, owner, roadmap, dependency, and capability checks.
- PP1 and PP2 remain uncreated until PP0 is approved and complete.

## Definition of Phase 1 Complete

Phase 1 is complete when M1 and M2 are complete, one governed classroom artifact
has been produced through the approved M3 chain, M4 is complete or explicitly
deferred, and roadmap, issue, readiness, authorization, and validation records
agree on the result.

## Authorization Boundary

This roadmap and every priority recommendation are evidence only. Repository
changes require separate approval and GitHub Service Agent execution. Live Google
Drive writes require exact destination confirmation and explicit live-write
approval. Merge remains a separate operator decision.
