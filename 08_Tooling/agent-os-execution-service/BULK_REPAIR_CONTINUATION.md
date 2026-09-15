# Finite bulk-repair continuation

Issue: #2487. Canonical generic continuation owner: #2220.

## Purpose

`classify_agent_os_bulk_repair_continuation_tool` exposes the existing
`scripts.agent_os_issue_acceptance.batch_repair_continuation` projection to the
Agent OS execution-service host.

The tool freezes the requested PR set supplied by the caller, consumes only
per-candidate disposition evidence, and returns the existing finite-batch next
action. It does not execute a repair, retry a blocked mutation, select a new
candidate population, create a scheduler/queue, or mutate GitHub.

## Item-local versus shared blockers

An item-local `blocked` disposition is recorded for that PR while later requested
PRs remain in `remaining_pull_requests`. The returned continuation action is
`reacquire-next-candidate`, so a safety-layer denial, conflict, or failed-repair
gate on one candidate does not become a parent-batch stop by itself.

A blocker terminates the parent batch only when the supplied candidate evidence
explicitly carries `shared_blocker=true`. The projection then returns
`halt-shared-blocker` and preserves the unattempted requested PRs in
`remaining_pull_requests` for final reporting.

## Failed-repair boundary

Retry-specific Lessons Learned remain owned by the canonical CKR6 failed-repair
path. The bulk projection accepts the existing normalized retry-boundary evidence
and reports whether re-entry is required, admitted, or blocked for the exact
candidate. It never grants retry mutation authority.

## Partial Git-object effects

Partially created unattached Git objects are represented as candidate evidence,
not as a repaired disposition. The projection performs no Git-object mutation and
cannot convert those objects into completion or authority.

## Authority

The tool is classification-only. `execution_authorized`,
`github_writes_authorized`, `mutation_authorized`, `merge_authorized`, and
`side_effects_performed` remain false. Merge, issue closure, workflows, protected
settings, credentials, production, and external-system writes remain outside this
contract.
