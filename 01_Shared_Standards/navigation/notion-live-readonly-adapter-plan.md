# Notion Live Read-Only Adapter Plan

## Purpose

Plan the live read-only Notion adapter implementation after Navigation Registry
RC1. This plan does not implement live Notion calls, credentials, cache writes,
or production discovery.

## Auth Model

Use a Notion internal integration token with the minimum read-only workspace scope
available. The token must be created and stored outside the repository. The
adapter reads only from pages and databases explicitly shared with the integration.

## Environment Variables

| Variable | Purpose | Required |
|---|---|---:|
| `NOTION_READONLY_TOKEN` | Notion integration token for read-only API calls. | yes for live mode |
| `NOTION_ALLOWED_TARGET_IDS` | Comma-separated approved page/database ids. | yes for live mode |
| `NOTION_LIVE_MODE` | Must equal `readonly` to enable live reads. | yes for live mode |

Fixture mode remains the default when these variables are absent.

## Read-Only API Boundary

Allowed future read calls: retrieve page metadata, retrieve database metadata,
query a specifically approved database, and retrieve block children only when a
future owner-approved page-body-read test enables that path.

Blocked calls: create, update, archive, delete, move, share, comment, invite,
change permissions, change schema, write cache records, or repair relationships.

## Mock-Based Test Strategy

Before live implementation, add mock tests that prove:

1. missing token disables live mode;
2. unapproved target ids are rejected before any API call;
3. live mode requires `NOTION_LIVE_MODE=readonly`;
4. API responses normalize to `RegistryResource`;
5. all normalized outputs keep `write_allowed=false`;
6. page-body reads remain blocked by default;
7. Notion API failures map to Connector Adapter Framework errors;
8. no mutation endpoint can be reached by adapter code.

## Fixture Tests To Preserve

Keep all RC1 fixture tests for page normalization, database normalization,
`write_allowed=false`, `page_body_read=false`, `ResourceMissing`,
`PermissionDenied`, `MetadataIncomplete`, health reporting, and
`write_capabilities=none`.

## Live Target Approval Requirements

Live testing requires an approved non-production Notion page or database id,
explicit owner approval, confirmation that the target contains no sensitive
student data, and evidence that the integration has read-only access only.

## Rollout Plan

1. Keep fixture mode as default.
2. Add mock-only live adapter boundary tests.
3. Add live adapter wrapper with mutation methods absent by design.
4. Run fixture and mock tests locally and in CI.
5. Select one approved non-production Notion target.
6. Run one targeted read-only verification.
7. Review evidence before broader discovery planning.

## Stop Conditions

Stop immediately if credentials are missing, target id is not approved, token
scope is unclear, page body content would be read without approval, a mutation
method is needed, Notion permissions differ from expected read-only access, or
source-of-truth ownership is unclear.

## Success Criteria

The next implementation PR can add a live read-only adapter safely without
risking writes, credentials exposure, cache writes, page-body reads by default,
or production Notion changes.

## Version

0.1.0
