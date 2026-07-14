# Notion Read-Only Connector Pilot Plan

## Purpose

Define the first implementation pilot for the Navigation Registry: a read-only
Notion connector that proves the registry data model, connector framework, and
workspace discovery flow against a real system without modifying Notion or
writing operational cache records.

## Pilot Scope

The pilot supports read-only lookup and verification for Notion databases and
pages. It may read metadata required for registry mapping and discovery evidence.
It must not create, edit, archive, move, share, or delete Notion records.

Out of scope: cache writes, production sync, Apps Script, Python runtime,
student-facing artifacts, Notion database schema edits, and automated registry
repair.

## Likely Files Or Modules

Future implementation may require:

- connector interface definitions
- Notion connector adapter
- Notion metadata normalizer
- registry data model mapper
- discovery evidence formatter
- connector health reporter
- permission and failure classifier
- read-only test fixtures
- conformance tests against the Connector Adapter Framework

Exact filenames should be chosen during implementation after repository layout
review.

## Connector Responsibilities

The connector should discover, look up, verify, list relationships, report drift,
report health, and validate permissions for Notion resources. All outputs are
evidence only. The connector does not authorize writes or decide source of truth.

## Data Model Mapping

| Notion item | Registry entity | Canonical id | Notes |
|---|---|---|---|
| Notion database | Database | Notion database id | display_name from title |
| Notion page | Page | Notion page id | parent maps to page or database |
| Linked page relation | Relationship | relationship_id | derived from source, target, type |
| User-facing name | Alias | alias_id | only when approved for registry use |
| Template page/database | Template | Notion id | only if governed as a template |

Required mapped fields: system, canonical_id, display_name, owner when available,
parent, source_of_truth, verification_state, cache_status, human_review_required,
and write_allowed=false.

## Connector Framework Conformance

The connector must declare connector_id, connector_name, connector_version,
supported_resource_types, authentication_model, authorization_requirements,
verification_strategy, discovery_capabilities, lookup_capabilities,
relationship_capabilities, cache_capabilities, write_capabilities, failure_modes,
adapter_metadata, owner, source_of_truth mapping, and health model.

Write support for this pilot is `none`.

## Workspace Discovery Support

The connector should support targeted discovery first, then limited incremental
discovery. Full workspace scan is deferred until rate limits, scope, and owner
approval are understood. Discovery output must normalize into the Navigation
Registry Data Model and include evidence for drift recommendations.

## Readable Metadata

The connector may read stable id, title/display name, parent id, object type,
last edited timestamp, created timestamp, URL, archived status if visible,
properties schema for databases, relation hints when visible, and permission
visibility signals available to the connector.

It should avoid reading page body content unless explicitly needed for a verified
lookup use case and approved by the owner.

## Prohibited Writes

The connector must never write to Notion, modify database schema, update page
properties, create aliases, repair relationships, change sharing, modify
permissions, write cache records, or update governed repository files.

## Failure Modes

| Failure | Required behavior |
|---|---|
| Authentication failed | stop and report AuthenticationFailed |
| Permission denied | stop and report PermissionDenied |
| Resource missing | retry/verify before reporting ResourceMissing |
| Resource moved | report ResourceMoved if stable id remains valid |
| Rate limited | back off and report RateLimited |
| API unavailable | report SystemUnavailable |
| Metadata incomplete | report MetadataIncomplete and mark human review |
| Source conflict | report SourceOfTruthConflict |

## Security And Permission Boundaries

Use the minimum read-only permission scope available. Treat Notion output as live
evidence, not governance authority. Do not store secrets, credentials, private
page content, or unnecessary student data in registry evidence. All
write-impacting actions require live verification and owner approval outside the
connector.

## Test Plan

Required tests before active pilot status:

1. Maps a Notion database to a Registry Database entity.
2. Maps a Notion page to a Registry Page entity.
3. Sets write_allowed=false for every output.
4. Reports PermissionDenied without fallback writes.
5. Reports ResourceMissing only after verification retry.
6. Normalizes parent relationships.
7. Emits connector health state.
8. Blocks page-body reads unless explicitly enabled by test fixture.
9. Produces Workspace Discovery evidence for rename and stale cache cases.
10. Passes Connector Adapter Framework conformance checks.

## Acceptance Criteria

The pilot is acceptable when it can perform read-only lookup and verification for
approved Notion pages/databases, map outputs to the Navigation Registry Data
Model, satisfy connector framework fields, produce discovery evidence, report
failures safely, and pass tests without modifying Notion, cache, or production
systems.

## Rollout Sequence

1. Confirm repository implementation layout.
2. Confirm Notion read-only auth model and owner approval path.
3. Build connector skeleton and contract tests.
4. Add metadata normalizer for pages and databases.
5. Add targeted lookup for known Notion ids.
6. Add health and failure reporting.
7. Add limited discovery evidence output.
8. Run conformance tests with fixtures.
9. Pilot against one approved non-production Notion target.
10. Review evidence before enabling broader discovery.

## Open Blockers

- Approved Notion target page/database is not selected.
- Notion credential model is not selected.
- Repository implementation layout is not confirmed.
- Operational cache destination remains unresolved.
- Executable conformance test harness does not exist yet.

## Handoff Recommendations

Integration Manager should own pilot routing and boundaries. Google Workspace
Automation Engineer should implement only after QA approves this plan. QA / Test
Agent should define fixtures before connector code is written.

## Version

0.1.0
