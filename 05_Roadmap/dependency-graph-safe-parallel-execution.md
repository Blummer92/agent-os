# Dependency Graph Safe Parallel Execution

## Purpose

This note documents the Phase 2 dependency graph behavior for #156. It extends
the dry-run project execution model so safe parallel batches can be computed from
local `ProjectJob` state.

## Boundary

The dependency graph remains simulation-only. It does not parse live GitHub issue
relationships, predict merge conflicts, execute autonomous work, merge pull
requests, or write to external systems.

## Behavior

- `safe_parallel_batch()` returns all unleased jobs whose dependencies are complete.
- Independent jobs can appear in the same safe batch.
- Dependent jobs keep visible `dependency_blocking_reasons` until predecessors complete.
- Missing dependencies are reported as blocking reasons.
- Cycles are detected with a DFS pattern adapted from the Workflow Scheduler resolver.
- Cyclic jobs are blocked rather than scheduled.
- Audit events record `dependency_blocked` and `dependency_cycle_detected`.

## Non-Goals

- No live GitHub issue dependency parsing.
- No merge conflict prediction.
- No autonomous execution.
- No issue-to-PR automation.
- No full worker pool.
- No dashboard.

## Smoke Tests

Smoke tests cover three-job dependency order, predecessor completion, independent
parallel batches, cycle blocking, visible dependency status, fixture-loaded jobs,
Project Manager selection, and zero external writes.

## Next Step

After #156 merges, the next issue should be #157: Worker assignment and lease
lifecycle.
