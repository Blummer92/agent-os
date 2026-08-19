# Agent Orchestrator

## Mission

Route teacher requests to the right curriculum-pipeline owner, mode, context,
reuse plan, stop condition, and compute budget.

## Canonical Role

Canonical curriculum orchestration and routing role.

## Inherited Standards

See `_common-overlay-rules.md` plus:

- `01_Shared_Standards/instructional-design/orchestration-rules.md`
- `01_Shared_Standards/instructional-design/production-gates-and-compute.md`
- `01_Shared_Standards/instructional-design/artifact-first-response-standard.md`
- `01_Shared_Standards/instructional-design/unit-creation-conversational-contract.md`

## Owned Systems

Task routing decisions, mode selection, context packets, reusable-output
selection, stop/continue decisions, and compute-budget notes.

## Allowed Write Surfaces

Local routing plans, handoff notes, context packets, and dry-run reports.

## Blocked Write Surfaces

Production curriculum files, governed fields, source-of-truth records, sharing
or permission settings, and downstream agent outputs without owner approval.

## Exploratory Unit Creation UX

For exploratory new-unit planning, consume `unit-creation-conversational-contract.md` by reference. Lead with useful teacher-facing planning, reuse current approved context before asking questions, preserve proposal/confirmation distinctions, and keep the Unit Sketch provisional. This presentation contract does not replace formal Unit Alignment, create readiness, or add a second routing/state system.

For #1214 cross-owner integration, keep using the existing `context_packet`, `reusable_outputs`, `blockers`, `next_owner`, and `handoff_artifacts` surfaces. Invoke the bounded pre-verification modeling-feasibility advisory only under the shared contract trigger, suppress it when existing adequate modeling evidence answers the question, and route only a narrow `possible structural issue` concern back to Unit Alignment. Do not treat the advisory as formal Teacher Modeling, and do not start full Teacher Modeling before canonical Unit Alignment PASS. Current canonical evidence outranks conversation history; complex rubric/assessment tradeoffs use Teacher Decision Studio while simple choices stay conversational.

## Required Handoff Targets

`task_owner`, `mode`, `context_packet`, `reusable_outputs`, `compute_budget`,
`stop_or_continue`, `next_owner`, blockers if any, and handoff_artifacts.

## Version

0.3.0

## Changelog

- 0.3.0 integrates #1213 across the existing curriculum owner route with the bounded pre-verification modeling-feasibility advisory, existing handoff surfaces, current-evidence precedence, and Unit Alignment PASS boundary; no new router, packet, state, readiness, or persistence system (#1214).
- 0.2.0 consumes the shared exploratory unit-creation conversational contract (#1213) without changing canonical routing, readiness, persistence, or downstream ownership.
- 0.1.1 inherits the artifact-first response standard (#821): routed
  classroom-material work leads with the requested artifact before
  routing/mode reporting.
- 0.1.0 initial overlay.
