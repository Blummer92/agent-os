# Read-Only Google Sheets Extraction Adapter

Issue #731 adds a fixture-first adapter that turns one bounded worksheet range
into `SourceAssetRecord` values for the reconciliation planner.

## Authorization boundary

`GoogleSheetsValuesReader` exposes only `spreadsheets.values.get` and is intended
for credentials carrying the `spreadsheets.readonly` OAuth scope. This code does
not authorize live access, query Notion, write to Sheets, modify Drive, create
credentials, schedule work, or run production synchronization.

## Read request

`SheetReadRequest` requires an exact spreadsheet ID, worksheet name, final A1
column, start row, and end row, with at most 10,000 rows per request. Worksheet
names are quoted and apostrophes escaped in the A1 range. The API request uses
row-major formatted values so dates remain text and Booleans map explicitly.

Identifiers must be exact built-in strings and row bounds exact built-in integers.
Boolean row values and objects offering conversion methods are rejected without
coercion.

## Header mapping

The live `Approved Use Review` contract was unavailable during implementation,
so callers supply an exact, non-empty mapping from selected planner fields to
verified Sheet headers. Supported targets are:

- `drive_file_id`, `drive_url`, `file_name`, `approved_use`
- `audience`, `review_status`, `review_date`, `visual_rationale`
- `worksheet_fit`, `slideshow_fit`, `poster_fit`
- `format_decision_notes`, `excluded`

Only configured headers are required. Unmapped text fields become `None`, and
unmapped `excluded` becomes `False`. Unconfigured column values never enter
planner records.

Live worksheets may contain unrelated columns. They are ignored after the full
header row passes structural validation. Duplicate, blank, or non-string headers
still fail closed, as do unsupported targets, repeated source-header assignments,
and missing configured headers.

Fixture display labels support offline tests only. They do not claim to match the
live Sheet and must be replaced with a verified mapping before an authorized read.

## Row behavior

- Source order follows worksheet order; `source_row` is the one-based Sheet row.
- Fully blank rows are skipped without renumbering later rows.
- Missing trailing cells become `None` for configured text fields.
- Nonblank cells beyond the declared header fail closed.
- Text cells accept only exact strings or `None`.
- `excluded` accepts exact Booleans, `TRUE`, `FALSE`, or blank.
- Unsupported objects and scalar types are never coerced.

Every mapped row passes through `normalize_source_record`. The adapter does not
validate or repair Drive IDs or URLs; the planner owns identity classification.

## Error contract

- `SheetReadError`: API or response-shape failure.
- `SheetSchemaError`: mapping or header failure.
- `SheetRowError`: incompatible row or cell failure.

Diagnostics are deterministic and exclude raw external values. API failures are
translated outside their active exception context, so original messages are not
retained in surfaced chained tracebacks.

## Testing and deployment handoff

Offline fixture tests cover partial and complete mappings, unrelated columns,
ordering, row identity, strict request and cell types, bounded reads, traceback
sanitization, absent write methods, and the planner smoke path.

Before live use, the Integration Manager must verify header names, spreadsheet
and worksheet IDs, bounded range, rendering and locale policy, credential route,
and read-only OAuth scope. #734 remains separately authorized after #733.
