# Project Manager Agent Boundary

## Purpose

This note defines the governed Phase 2 Project Manager Agent boundary for
multi-issue orchestration. It does not authorize live issue-to-PR automation.

## Role

The Project Manager coordinates dry-run project execution state. It chooses ready
jobs and assigns bounded work through existing queue and lease behavior.

## Inputs

- Job queue state.
- Dependency state.
- Governance and blocked-job state.
- Validation state already produced by the dry-run execution model.

## Outputs

- Selected ready jobs.
- Worker assignment decisions.
- Blocked-job reports.
- Audit events for selection and assignment.

## Owned State

- Selection history.
- Assignment history through existing audit events.

## Forbidden Actions

- Merge pull requests.
- Create pull requests.
- Write to external systems.
- Bypass the validation gate.
- Change governed source-of-truth fields automatically.

## Relationship To Existing Code

The MVP implementation reuses the dry-run project execution model from
`workflow_scheduler.project_execution`. It does not introduce a new live worker
pool, merge queue, GitHub issue reader, Notion writer, or Google Drive writer.

## Smoke Test Requirements

- Select only ready jobs.
- Do not select blocked or governance-blocked jobs.
- Assign jobs through the lease path.
- Reject forbidden actions.
- Perform zero external writes.

## Next Step

After this boundary is validated, the next issue should add fixture-backed issue
queue loading without live GitHub reads or writes.
