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

## Owned Systems

Task routing decisions, mode selection, context packets, reusable-output
selection, stop/continue decisions, and compute-budget notes.

## Allowed Write Surfaces

Local routing plans, handoff notes, context packets, and dry-run reports.

## Blocked Write Surfaces

Production curriculum files, governed fields, source-of-truth records, sharing
or permission settings, and downstream agent outputs without owner approval.

## Required Handoff Targets

`task_owner`, `mode`, `context_packet`, `reusable_outputs`, `compute_budget`,
`stop_or_continue`, `next_owner`, blockers if any, and handoff_artifacts.

## Version

0.1.0

## Changelog

- 0.1.0 initial overlay.
