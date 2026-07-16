# Fixture-Backed Issue Queue Loader

## Purpose

This note documents the Phase 2 fixture-backed issue queue loader for #155.
It keeps early orchestration local, static, and dry-run only.

## Boundary

The loader converts local JSON fixture data into `ProjectJob` objects for the
existing project execution model. It does not read live GitHub issues and does
not write to GitHub, Notion, Google Drive, or any external system.

## Fixture Shape

A fixture is a JSON object with a `jobs` list. Each job supports:

- `id`: local unique job identifier.
- `issue_number`: GitHub issue number represented by the fixture.
- `title`: issue title.
- `priority`: optional integer priority.
- `dependencies`: optional list of predecessor job ids.
- `blocked`: optional boolean for blocked jobs.
- `governance_blocked`: optional boolean for governance-blocked jobs.
- `blocked_reason`: optional text explaining why a job is blocked.
- `status`: optional explicit `JobStatus` value.

## Validation Rules

The loader rejects malformed fixture data with `FixtureValidationError`.
It validates required fields, duplicate ids, dependency list shape, status values,
and boolean blocked fields.

## Non-Goals

- No live GitHub issue discovery.
- No issue-to-PR automation.
- No autonomous coding.
- No autonomous merge.
- No external writes.
- No dashboard or full worker pool.

## Smoke Tests

The smoke tests prove independent jobs become ready, dependencies block until
completion, blocked jobs remain blocked, invalid data fails clearly, loaded jobs
can be selected by Project Manager, and assignments still use the lease path.

## Next Step

After #155 merges, the next issue should be #156: dependency graph behavior for
safe parallel issue execution.
