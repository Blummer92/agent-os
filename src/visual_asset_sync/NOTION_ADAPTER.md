# Read-Only Notion Extraction Adapter

Issue #735 adds a fixture-first, bounded reader for existing Visual Asset Library
records. It feeds the reconciliation planner and performs no external write.

## Authorization boundary

No live Notion access, credentials, Google Sheets call, Google Drive call, or
production synchronization is authorized here. The concrete reader accepts an
injected query callable, and construction performs no request. Fixture tests use
fake readers only. Issue #737 owns live target, schema, sharing, access, and smoke
verification.

The production target is one exact Notion `data_source_id`. A database ID is not
interchangeable with a data-source ID. The adapter pins `Notion-Version` to
`2025-09-03`. Fixture property names are proposals, not verified live names.

## Limits

`NotionReadRequest` applies exact built-in type checks and these defaults:

- page size: 25; maximum supported: 100
- maximum pages: 25; implementation ceiling: 1000
- maximum records: 625; implementation ceiling: 100000
- maximum retries per requested page: 2; implementation ceiling: 10
- total retry-delay ceiling per requested page: 30.0 seconds; maximum: 300.0
- data-source ID length: at most 256 characters

Boolean integer values, hostile conversion objects, empty identifiers,
unsupported versions, non-finite delays, and out-of-range limits fail closed.

## Mapping contract

Callers provide an exact mapping from planner fields to verified Notion property
names. Supported planner targets are `drive_file_id`, `drive_url`, `asset_title`,
`approved_use`, `asset_type`, `human_review_status`, and `review_date`.

Mapped fields are optional by default and become `None` when absent. Callers may
provide an exact `frozenset` of configured fields that must be present. Missing
required fields fail closed.

Supported Notion property shapes are title, rich text, URL, select, status, date,
checkbox, and number. Unrelated supported properties are preserved in
`ExistingAssetRecord.extra_fields`. Unsupported or malformed shapes fail closed;
values are not stringified, represented, truth-tested, or arbitrarily flattened.

## Pagination and retries

Response order is preserved. Responses, results, and result records require exact
container types. `has_more` is an exact Boolean, and `next_cursor` must be a
non-empty exact string only while more pages exist. Cursors are opaque. Repeated
cursors, cycles, malformed metadata, and page or record ceilings fail closed.

Only explicit `NotionRateLimitError` values are retryable. Their exact finite,
non-negative delays are passed to an injected sleep function. Retry count and
cumulative delay reset for each requested page and remain bounded. Other failures
are not retried.

## Errors and safety

Adapter errors use fixed diagnostics. Raw API messages, tokens, response bodies,
property values, and target payloads are excluded. External exceptions are
translated outside their active exception context and are not chained into the
surfaced traceback.

The adapter exposes a query-only protocol and no create, update, archive, delete,
comment, upload, sharing, relation, permission, or schema mutation method. Live
Notion execution remains unauthorized until the separate #737 handoff is approved.
