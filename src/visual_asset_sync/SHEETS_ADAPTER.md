# Read-Only Google Sheets Extraction Adapter

Issue #731 adds a fixture-first adapter that turns one bounded worksheet range
into `SourceAssetRecord` values for the reconciliation planner.

## Authorization boundary

The adapter is read-only. `GoogleSheetsValuesReader` exposes only
`spreadsheets.values.get` and is intended for credentials carrying the
`https://www.googleapis.com/auth/spreadsheets.readonly` scope.

This implementation does not authorize live Sheet access. It does not query
Notion, write to Sheets, change Drive files, create credentials, schedule work,
or run production synchronization.

## Read request

`SheetReadRequest` requires:

- an exact spreadsheet ID;
- an exact worksheet name;
- an explicit final A1 column;
- an explicit start and end row;
- no more than 10,000 rows per request.

Worksheet names are quoted and apostrophes are escaped when constructing the A1
range. The Google API request uses row-major, formatted values so dates remain
text and Boolean cells can be mapped explicitly.

Request identifiers must be exact built-in strings and row bounds must be exact
built-in integers. Boolean row values and objects that merely implement string
or numeric conversion are rejected without coercion.

## Header mapping

The live `Approved Use Review` header contract was not available in the
implementation environment. The adapter therefore does not guess live column
names. Callers must supply an exact, non-empty mapping from selected planner
fields to verified Sheet headers.

Supported target fields are:

- `drive_file_id`
- `drive_url`
- `file_name`
- `approved_use`
- `audience`
- `review_status`
- `review_date`
- `visual_rationale`
- `worksheet_fit`
- `slideshow_fit`
- `poster_fit`
- `format_decision_notes`
- `excluded`

Only configured headers are required. Unmapped text fields are supplied to the
planner as `None`, and unmapped `excluded` is supplied as `False`. Values from
unconfigured columns are never copied into planner records.

Live worksheets may contain unrelated columns. Those columns are ignored after
the complete header row passes structural validation. Duplicate, blank, or
non-string headers still fail closed, as do unsupported target fields, repeated
source-header assignments, and missing configured headers.

The fixture uses proposed display headers only for offline tests. Those labels
are not a claim about the live Sheet and must be replaced with a verified mapping
before any authorized live read.

## Row behavior

- Source order follows worksheet order.
- `source_row` is the actual one-based Sheet row number.
- Fully blank rows are skipped without renumbering later rows.
- Missing trailing cells become `None` for configured text fields.
- Cells beyond the declared header row fail closed when nonblank.
- Text fields accept only exact strings or `None`.
- `excluded` accepts exact Booleans, `TRUE`, `FALSE`, or blank.
- Unsupported objects and scalar types are never coerced.

Every mapped row is passed through `normalize_source_record`. The adapter does
not validate or repair Drive IDs or URLs; identity classification remains owned
by the planner.

## Error contract

- `SheetReadError`: API or response-shape failure.
- `SheetSchemaError`: mapping or header failure.
- `SheetRowError`: incompatible row or cell failure.

Diagnostics are deterministic and do not include raw external values. External
API failures are translated outside their active exception context so original
exception messages are not retained in surfaced chained tracebacks.

## Testing and deployment handoff

Offline tests use a JSON fixture and fake Sheets service. They verify partial and
complete mappings, unrelated-column handling, ordering, row identity, strict
request and cell types, bounded reads, traceback sanitization, no write methods,
and a planner smoke path.

Before live use, the Integration Manager must verify the real header names,
spreadsheet ID, worksheet name, bounded range, rendering and locale policy,
approved credential mechanism, and read-only OAuth scope. Live smoke testing
remains separately authorized under #734 after #733 completes.