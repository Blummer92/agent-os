# Notion Live Access Approval Plan

## Purpose

Define the approval path for the first safe, read-only, metadata-only Notion live
smoke test for the Navigation Registry.

This plan does not enable live Notion access, add a Notion SDK, add an HTTP
client, store credentials, read page body content, write cache records, or modify
production systems.

## Credential Storage Model

Use a Notion internal integration token with the minimum read-only permission
scope available. The token must never be committed to the repository.

Approved storage locations:

1. Local developer environment variables for manual smoke tests.
2. GitHub Actions repository secrets only after CI smoke testing is explicitly
   approved.

Required variables:

| Variable | Required for live smoke test | Purpose |
|---|---:|---|
| `NOTION_READONLY_TOKEN` | yes | Notion integration token stored outside the repository. |
| `NOTION_ALLOWED_TARGET_IDS` | yes | Comma-separated allowlist of approved page or database ids. |
| `NOTION_LIVE_MODE` | yes | Must equal `readonly`. |

Secrets must not be printed, logged, written to fixtures, placed in PR comments,
or copied into test snapshots.

## Approved Non-Production Target Requirements

The first live target must be one known Notion page or database that is safe for
metadata-only testing.

The approved target must:

1. Be non-production or explicitly designated as safe for smoke testing.
2. Contain no sensitive student data.
3. Be shared only with the read-only integration required for the test.
4. Have a stable Notion page or database id recorded outside code.
5. Have an identified owner who can approve read-only metadata lookup.
6. Be limited to one target id for the first smoke test unless a follow-up
   approval expands scope.

## Owner Approval Checklist

Before any live smoke test, record approval evidence that confirms:

- target owner name or role;
- target page or database id;
- target is non-production or safe for smoke testing;
- target contains no sensitive student data;
- integration has the minimum required access;
- live test is metadata-only;
- page body reads are blocked;
- cache writes are blocked;
- mutation/write operations are blocked;
- approval is limited to the named target id only.

## Allowed Metadata-Only Read Scope

The first live smoke test may read only metadata required to normalize a Notion
resource into a `RegistryResource`.

Allowed fields when available:

- object type;
- stable Notion id;
- title or display name;
- parent id;
- created timestamp;
- last edited timestamp;
- URL;
- archived status;
- visible database schema metadata for an approved database;
- permission or visibility signals needed for health evidence.

## Blocked Operations

The live smoke test must not:

- create, update, archive, delete, move, share, comment, invite, or change
  permissions;
- modify Notion database schema;
- update Notion page properties;
- read page body content by default;
- write Navigation Registry cache records;
- repair relationships;
- create aliases;
- write GitHub repository files during the smoke test;
- print or store secrets;
- broaden the target id allowlist without new approval.

## Local Developer Setup Requirements

A local developer may run the smoke test only after the owner approval checklist
is complete.

Required local setup:

1. Pull the latest `main` after the approval-plan PR is merged.
2. Create a new implementation branch.
3. Export `NOTION_LIVE_MODE=readonly`.
4. Export `NOTION_ALLOWED_TARGET_IDS` with only the approved target id.
5. Export `NOTION_READONLY_TOKEN` from a local secret source.
6. Run all offline tests before attempting a live smoke test.
7. Run one targeted metadata lookup only.
8. Remove shell history or local files if they accidentally capture secrets.

## GitHub Actions And CI Secret Handling

GitHub Actions must not run live Notion smoke tests by default.

CI live smoke tests require a later explicit approval that defines:

- the GitHub secret name and owner;
- the approved non-production target id;
- whether CI may access the target;
- how logs will avoid printing secrets or raw Notion payloads;
- whether live tests are manually triggered only.

Default CI should continue to run offline fixture, boundary, and adapter-wrapper
tests without secrets.

## Live Smoke-Test Procedure

The first live smoke test must be targeted and manual.

Procedure:

1. Confirm approval checklist is complete.
2. Confirm only one approved target id is present in `NOTION_ALLOWED_TARGET_IDS`.
3. Confirm `NOTION_LIVE_MODE=readonly`.
4. Confirm offline tests pass.
5. Construct a read-only client outside repository secrets.
6. Perform one metadata lookup for the approved id.
7. Normalize the response into a `RegistryResource`.
8. Confirm `write_allowed=false`.
9. Confirm `page_body_read=false`.
10. Confirm no cache writes occurred.
11. Record sanitized evidence.
12. Stop before any broader discovery.

## Evidence To Record After First Live Metadata Lookup

Record only sanitized evidence:

- command or script name used;
- timestamp;
- approved target id or redacted suffix if needed;
- resource type returned;
- normalized `RegistryResource` fields excluding secrets and raw page content;
- `write_allowed=false` confirmation;
- `page_body_read=false` confirmation;
- cache write count of zero;
- mutation/write count of zero;
- test results for offline suites;
- any errors or drift findings.

Do not record token values, raw API headers, page body content, sensitive student
data, or full private payloads.

## Stop Conditions

Stop immediately if:

- `NOTION_READONLY_TOKEN` is missing or appears in logs;
- `NOTION_LIVE_MODE` is not `readonly`;
- the target id is not in `NOTION_ALLOWED_TARGET_IDS`;
- more than one target id is present for the first smoke test;
- owner approval is incomplete;
- the target may contain sensitive student data;
- page body content would be read;
- any mutation/write method is required;
- cache writes are attempted;
- Notion permissions differ from expected read-only access;
- source-of-truth ownership is unclear;
- the connector would broaden scope beyond the approved target.

## Handoff Requirements

Before implementation begins, Integration Manager must hand off:

1. approved target tuple;
2. owner approval evidence;
3. credential storage decision;
4. allowed smoke-test command;
5. stop conditions;
6. evidence-recording template.

Google Workspace Automation Engineer may implement live metadata lookup only
after this handoff is complete. QA / Test Agent must review the live smoke-test
plan before execution.

## Success Criteria

The first live smoke test is approved only when it can perform one targeted,
metadata-only lookup against an approved Notion page or database without reading
page body content, exposing credentials, writing cache records, modifying Notion,
or broadening discovery scope.

## Version

0.1.0
