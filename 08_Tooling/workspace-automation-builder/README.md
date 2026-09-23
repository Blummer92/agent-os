# Workspace Automation Builder Tooling

## Purpose

This package contains reusable Workspace automation safety tooling, validation
schemas, fixtures, and sample handoff files for review before any live Workspace
write.

Workspace Automation Builder is a capability workflow, not an executable agent.

## Ownership

Repository implementation owner: GitHub Service Agent, applying the shared
Workspace Automation Builder standard and any applicable language/runtime
standards.

Cross-system, source-of-truth, and external-operation routing belongs to ChatGPT
Orchestrator. QA / Test Agent owns independent validation evidence where
required.

Legacy names such as `Google Workspace Automation Engineer` are compatibility
input only. They resolve through `04_Registry/legacy-agent-alias-registry.md`
and do not create execution or write authority.

Live Workspace writes remain separately governed by
`01_Shared_Standards/google-workspace/workspace-write-authorization.md` and
require exact-target authorization independent of repository implementation.

This package does not create a new agent. It implements the tooling layer for the
shared Workspace Automation Builder capability workflow.

## Structure

- `apps-script/`: reusable Apps Script helper code and offline tests.
- `schemas/`: JSON schemas for generic sync handoff packets and dry-run receipts.
- `fixtures/`: sanitized valid and invalid handoff/receipt examples.
- `tests/`: local-only fixture validation tests.
- `docs/`: Markdown summaries of sync safety and collaboration requirements.
- `samples/`: non-generic fixtures that show guarded handoff patterns.

## Safety Boundary

- No live Drive, Sheets, Docs, Gmail, Calendar, Notion, Apps Script trigger,
  sharing, permission, or production write is authorized by this package.
- Repository implementation authorization never grants a live Workspace write.
- Tests use local fixtures and mocks only.
- Sample and fixture IDs are sanitized values.

## Schemas

- `schemas/sync-handoff.v1.schema.json`
- `schemas/sync-dry-run-receipt.v1.schema.json`

Use these schemas and fixtures to validate handoff packets and dry-run receipts
before any write path is considered. Passing fixture validation does not approve a
live write.

## How To Validate

Run the Apps Script files in a local JavaScript harness or Apps Script test
project without production services:

1. load `apps-script/AppsScriptSyncSafetyBridge.gs`
2. load `apps-script/AppsScriptSyncSafetyBridgeTest.gs`
3. run `runAppsScriptSyncSafetyBridgeTests()`

Run local fixture validation with Node:

```bash
node 08_Tooling/workspace-automation-builder/tests/validate-fixtures.test.js
```

Optional sample validation:

1. load `samples/unit-alignment-handoff/HandoffService.gs`
2. load `samples/unit-alignment-handoff/HandoffServiceTest.gs`
3. run `runHandoffServiceTests()`

## Version

0.1.2
