# Workspace Automation Builder Tooling

## Purpose

This package contains reusable Workspace automation safety tooling, validation
schemas, fixtures, sample handoff files, and local validation commands for review
before any live Workspace write.

## Ownership

Canonical owner: Google Workspace Automation Engineer.

This package does not create a new agent. It implements the tooling layer for the
shared Workspace Automation Builder standard.

## Structure

- `apps-script/`: reusable Apps Script helper code and offline tests.
- `bin/`: local command-line validation entry points.
- `lib/`: shared local validation helpers.
- `schemas/`: JSON schemas for generic sync handoff packets and dry-run receipts.
- `fixtures/`: sanitized valid and invalid handoff/receipt examples.
- `tests/`: local-only fixture and CLI validation tests.
- `docs/`: Markdown summaries of sync safety and collaboration requirements.
- `samples/`: non-generic fixtures that show guarded handoff patterns.

## Safety Boundary

- No live Drive, Sheets, Docs, Gmail, Calendar, Notion, Apps Script trigger,
  sharing, permission, or production write is authorized by this package.
- Tests use local fixtures and mocks only.
- Sample and fixture IDs are sanitized values.
- Local validators read JSON files and print validation results only.

## Schemas

- `schemas/sync-handoff.v1.schema.json`
- `schemas/sync-dry-run-receipt.v1.schema.json`

Use these schemas and fixtures to validate handoff packets and dry-run receipts
before any write path is considered. Passing validation does not approve a live
write.

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

Validate a handoff packet or dry-run receipt file with the reusable local command:

```bash
node 08_Tooling/workspace-automation-builder/bin/validate-handoff.js \
  08_Tooling/workspace-automation-builder/fixtures/sync-handoff.valid.json
```

```bash
node 08_Tooling/workspace-automation-builder/bin/validate-handoff.js \
  08_Tooling/workspace-automation-builder/fixtures/dry-run-receipt.valid.json
```

Run local CLI validation tests:

```bash
node 08_Tooling/workspace-automation-builder/tests/validate-handoff-cli.test.js
```

Optional sample validation:

1. load `samples/unit-alignment-handoff/HandoffService.gs`
2. load `samples/unit-alignment-handoff/HandoffServiceTest.gs`
3. run `runHandoffServiceTests()`

## Version

0.1.2
