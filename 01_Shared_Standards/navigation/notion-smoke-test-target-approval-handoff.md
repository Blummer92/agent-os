# Notion Smoke-Test Target Approval Handoff

## Purpose

Provide the target-approval handoff template for the first Navigation Registry
Notion live smoke test. This document is a placeholder-only approval record until
one safe Notion page or database is selected.

This handoff does not implement live Notion calls, add a Notion SDK, add an HTTP
client, store credentials, modify production systems, write cache records, or
read page body content.

## Target Tuple Template

| Field | Value |
|---|---|
| Notion target type | `PENDING: page or database` |
| Notion target id | `PENDING: placeholder only` |
| Target display name | `PENDING: placeholder only` |
| Owner | `PENDING: placeholder only` |
| Approval status | `pending` |
| Sensitive data status | `pending verification` |
| Production status | `pending verification` |
| Approved target count | `1 maximum for first smoke test` |

## Approval Evidence Checklist

Before any live smoke test, confirm and record:

- [ ] owner approval recorded;
- [ ] target is non-production or explicitly safe for smoke testing;
- [ ] target contains no sensitive student data;
- [ ] read-only integration access only;
- [ ] one target id only;
- [ ] metadata-only lookup only;
- [ ] page body reads blocked;
- [ ] cache writes blocked;
- [ ] mutation/write operations blocked.

## Credential Model Decision

For the first manual smoke test:

- local environment variables only;
- no GitHub Actions secrets yet;
- no CI live smoke test yet;
- no credentials in source files, fixtures, logs, PR comments, or test snapshots.

Required local variables when the smoke test is approved:

- `NOTION_LIVE_MODE=readonly`
- `NOTION_ALLOWED_TARGET_IDS=<approved-single-target-id>`
- `NOTION_READONLY_TOKEN=<local-secret-source>`

## Smoke-Test Allowed Command Placeholder

Allowed command is pending until the implementation branch defines the manual
smoke-test entry point.

Placeholder:

```bash
PENDING_SAFE_COMMAND --target-id "$NOTION_ALLOWED_TARGET_IDS"
```

The command must perform one metadata-only lookup and then stop.

## Sanitized Evidence Template

After the first approved live metadata lookup, record only:

| Evidence field | Value |
|---|---|
| Timestamp | `PENDING` |
| Command or script name | `PENDING` |
| Target id | `PENDING: redacted if needed` |
| Target type | `PENDING` |
| Resource type returned | `PENDING` |
| Normalized fields recorded | `PENDING: exclude secrets and body content` |
| `write_allowed=false` confirmed | `PENDING` |
| `page_body_read=false` confirmed | `PENDING` |
| Cache write count | `0 required` |
| Mutation/write count | `0 required` |
| Offline tests passed | `PENDING` |
| Errors or drift findings | `PENDING` |

Never record token values, API headers, page body content, sensitive student
data, or full private Notion payloads.

## Stop Conditions

Stop immediately if:

- approval status is not approved;
- owner approval evidence is incomplete;
- target id is missing or not allowlisted;
- more than one target id is present;
- target may contain sensitive student data;
- production status is unclear;
- `NOTION_LIVE_MODE` is not `readonly`;
- `NOTION_READONLY_TOKEN` is missing or appears in logs;
- page body content would be read;
- cache writes are attempted;
- any mutation/write method is required;
- Notion permissions differ from expected read-only access;
- the connector would broaden scope beyond the approved target.

## Handoff Conditions

Integration Manager may hand off to Google Workspace Automation Engineer only
after the approval evidence checklist is complete and QA confirms the smoke-test
execution plan.

The handoff must include:

1. approved target tuple;
2. owner approval evidence;
3. credential model confirmation;
4. allowed smoke-test command;
5. stop conditions;
6. sanitized evidence template.

## Success Criteria

The template is ready when a single safe Notion page or database can be selected
and documented without enabling live access or changing any production system.

## Version

0.1.0
