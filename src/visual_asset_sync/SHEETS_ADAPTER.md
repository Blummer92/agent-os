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

The live `Approved Use Review` contract is verified under Issue #733. Current
verified target: spreadsheet `1S3GNwqu0ehPXUA1j4FEksH1uEMKlxyEwAZWfIADPfpo`,
worksheet `Approved Use Review`, header row 1, bounded range `A1:N455`.

The verified mapping is:

- `drive_file_id` -> `File ID`
- `drive_url` -> `Drive URL`
- `file_name` -> `File Name`
- `approved_use` -> `Approved Use`
- `audience` -> `Audience`
- `review_status` -> `Review Status`
- `review_date` -> `Reviewed Date`
- `visual_rationale` -> `Visual Rationale`
- `worksheet_fit` -> `Worksheet Fit`
- `slideshow_fit` -> `Slideshow Fit`
- `poster_fit` -> `Poster Fit`
- `format_decision_notes` -> `Format Decision Notes`

`Source Row` and `Confidence` are intentionally unmapped. `source_row` is derived
from the physical Sheet row, while `Confidence` has no planner target. The live
sheet has no `excluded` column, so unmapped `excluded` remains `False`.

Live worksheets may contain unrelated columns. They are ignored after the full
header row passes structural validation. Duplicate, blank, or non-string headers
still fail closed, as do unsupported targets, repeated source-header assignments,
and missing configured headers.

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

The current live contract has been revalidated as of 2026-09-05 without schema or
rendering drift: locale `en_US`, timezone `America/New_York`, 455x14 grid, exact
14-header order, formula-backed File ID/File Name/Drive URL, ISO-text Reviewed
Date, and text-dropdown review/audience/fit fields. `FORMATTED_VALUE` remains
compatible with the mapped contract.

#734 remains the separately governed live smoke-test lane. Before executing it,
verify the exact adapter commit, credential injection route, and the OAuth scopes
actually granted to the token; the required scope is
`https://www.googleapis.com/auth/spreadsheets.readonly`.
