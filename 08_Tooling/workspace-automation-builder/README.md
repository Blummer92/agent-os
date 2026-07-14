# Workspace Automation Builder Tooling

## Purpose

This package contains reusable Workspace automation safety tooling and sample
handoff fixtures for review before any live Workspace write.

## Ownership

Canonical owner: Google Workspace Automation Engineer.

This package does not create a new agent. It implements the tooling layer for the
shared Workspace Automation Builder standard.

## Structure

- `apps-script/`: reusable Apps Script helper code and offline tests.
- `docs/`: Markdown summaries of sync safety and collaboration requirements.
- `samples/`: non-generic fixtures that show guarded handoff patterns.

## Safety Boundary

- No live Drive, Sheets, Docs, Gmail, Calendar, Notion, Apps Script trigger,
  sharing, permission, or production write is authorized by this package.
- Tests use local fixtures and mocks only.
- Sample IDs are sanitized fixture values.

## How To Validate

Run the Apps Script files in a local JavaScript harness or Apps Script test
project without production services:

1. load `apps-script/AppsScriptSyncSafetyBridge.gs`
2. load `apps-script/AppsScriptSyncSafetyBridgeTest.gs`
3. run `runAppsScriptSyncSafetyBridgeTests()`

Optional sample validation:

1. load `samples/unit-alignment-handoff/HandoffService.gs`
2. load `samples/unit-alignment-handoff/HandoffServiceTest.gs`
3. run `runHandoffServiceTests()`

## Version

0.1.0
