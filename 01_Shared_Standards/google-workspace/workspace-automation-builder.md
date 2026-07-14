# Workspace Automation Builder

## Purpose

Use this standard when designing or building Google Workspace automations for
Drive, Docs, Sheets, Gmail, Calendar, Apps Script, or related workspace flows.

This is a builder workflow, not a new agent. The canonical owner remains the
Google Workspace Automation Engineer unless the registry says otherwise.

## Builder Outputs

A safe automation build should produce the smallest useful set of:

- automation spec
- target inventory
- source-of-truth check
- data-flow map
- read/write operation list
- validation plan
- rollback or disable plan
- deployment handoff

Do not deploy, create triggers, change sharing, mutate live data, or alter
production files until target, owner, scope, and write authorization are explicit.

## Required Automation Spec

Before implementation, capture:

- user goal and success condition
- systems involved
- exact file, folder, sheet, doc, calendar, label, or script IDs when available
- trigger type: manual, scheduled, event-based, or external
- input data and source of truth
- output destination and owner
- fields, tabs, pages, or ranges affected
- read operations
- write operations
- permissions and OAuth scopes needed
- failure modes and rollback path

If any target or write scope is unclear, stop before building live-write code.

## Build Phases

1. Discovery: inspect only approved sources and identify targets.
2. Spec: define automation behavior, boundaries, and success criteria.
3. Dry-run design: prefer read-only preview, mock clients, or fixture tests.
4. Implementation: build local code or Apps Script plan without live writes.
5. Validation: test pure logic, mocked API calls, and expected receipts.
6. Approval handoff: list live-write steps still needing explicit approval.

## Safety Rules

- Prefer stable IDs over names.
- Separate Drive, Docs, Sheets, Gmail, Calendar, Notion, and Apps Script duties.
- Keep reads, writes, triggers, and deployment actions separate.
- Never write directly to template or master files.
- Never create installable triggers without explicit deployment approval.
- Never broaden sharing or permissions silently.
- Store secrets outside the repository.

## Handoff Checklist

A complete handoff names:

- files changed or generated
- targets verified and targets still missing
- tests run and dry-run evidence
- OAuth scopes or permissions required
- live-write approval still needed
- rollback, disable, or recovery steps
- unresolved blockers and remaining risks

## Version

0.1.0
