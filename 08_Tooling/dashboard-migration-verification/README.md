# Dashboard Migration Verification Toolkit

This toolkit gives Agent OS a local, reusable evidence layer for dashboard migration
verification. It reduces repeated live lookup by preferring local registry files,
snapshots, dependency graphs, and validation outputs first.

## Purpose

Use this toolkit to:

- register known dashboard surfaces
- define structured proposed migration changes
- capture local dashboard snapshots
- build reusable dependency graphs
- validate migration proposals conservatively
- produce machine-readable results and human-readable reports

## Safety Boundary

This toolkit is verification-only. It does not archive, delete, rename, merge, or
update Notion data. It does not mutate Google Sheets, Drive, Apps Script, Notion, or
any production system.

Missing evidence is not neutral evidence. Placeholder snapshots are scaffolding, not
proof. If evidence is incomplete, stale, missing, uncertain, or contradictory, classify
as `Requires manual review` or `Blocked by missing information`.

See `01_Shared_Standards/dashboard-governance/dashboard-migration-verification.md` for
the governing standard.

## Directory Structure

See `docs/directory_structure.md` for the full expected layout.

## Commands, Inputs, And Outputs

See:

- `docs/agent_workflow.md` for the recommended operating order and rules
- `docs/workspace_commands.md` for the exact commands to run
- `docs/workspace_io.md` for expected inputs, outputs, and commit rules
- `docs/evidence_model.md` for the file-by-file evidence schema

## Recommended Run Order

1. Refresh the latest dashboard snapshot.
2. Build the dependency graph from the latest snapshot and target manifest.
3. Validate the proposed changes.
4. Use live systems only if local evidence is missing, stale, or contradictory.

## Ownership

Primary owner: Modeling & Dashboard Governance Agent.

Support:

- QA / Test Agent for validation evidence
- Google Workspace Automation Engineer for Workspace automation boundaries
- GitHub Service Agent for repository implementation
