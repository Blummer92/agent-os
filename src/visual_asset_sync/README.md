# Visual Asset Sync — Reconciliation Planner

Deterministic, offline, dry-run reconciliation planner for moving reviewed icon
assets from the `Approved Use Review` Google Sheet into the Notion Visual Asset
Library. See Issue #693.

The reconciliation planner core performs **zero network calls and zero external
writes**. Related optional Google Sheets and Notion adapters may perform only
separately authorized bounded reads. No component performs an external write.
Live credentials, targets, smoke testing, and production synchronization remain
separately authorized.

The fixture-first Notion read boundary for Issue #735 is documented in
[`NOTION_ADAPTER.md`](NOTION_ADAPTER.md).

## Input contract

`normalize_source_record` accepts an exact built-in dictionary. `source_row` is
a required, non-empty exact string of at most 128 characters. Optional text
fields accept only exact built-in strings or `None`, and `excluded` accepts only
an exact built-in Boolean. Values are never coerced with `str()`, `repr()`, or
truthiness. Unsupported objects fail closed with fixed diagnostics.

`normalize_existing_record` applies the same exact-string boundary, requires a
non-empty `page_id`, and preserves unrelated fields verbatim in `extra_fields`
without coercing their values.

Supported source fields include: `drive_file_id`, `drive_url`, `file_name`,
`approved_use`, `audience`, `review_status`, `review_date`, `visual_rationale`,
`worksheet_fit`, `slideshow_fit`, `poster_fit`, `format_decision_notes`, and
`source_row`.

## Identity precedence

1. A valid `drive_file_id` is the authoritative identity key.
2. `drive_url` is used only when the explicit ID is absent and the URL yields
   exactly one unambiguous Drive File ID.
3. `file_name` never establishes identity; it is diagnostic only.
4. A valid explicit ID conflicting with any URL-derived candidate produces
   `CONTRADICTORY_RECORD`.
5. Missing, malformed, unsupported, or ambiguous identity produces
   `MALFORMED_IDENTITY`.
6. Existing records use the same rules. Contradictory existing evidence blocks
   both false updates and false creates for every involved identity.

### URL identity rules

Only `drive.google.com` and `docs.google.com` over `http` or `https` may
establish Drive identity. URLs are structurally parsed; strings, unsupported
hosts, lookalike hosts, and embedded `/d/<id>` fragments contribute no evidence.

`extract_drive_id_candidates` returns every distinct valid candidate from all
`/d/<id>` path segments and `id=` query parameters. A URL carrying multiple
distinct IDs is ambiguous and never silently resolves to the first candidate.

### Drive File ID format

`is_valid_drive_file_id` applies a bounded shape check: 20–128 characters drawn
from `[A-Za-z0-9_-]`. This rejects malformed tokens but does not prove that a
file exists or points to the intended asset.

## Result types

Every source record receives exactly one result:

| Result | Meaning |
|---|---|
| `UPDATE_EXISTING` | Identity matches one valid existing record. |
| `CREATE_MISSING` | Identity is valid and matches no existing evidence. |
| `DUPLICATE_ID` | Source or existing identity is duplicated. |
| `MALFORMED_IDENTITY` | No single usable identity exists. |
| `CONTRADICTORY_RECORD` | Source or existing identity evidence conflicts. |
| `EXCLUDED` | Record is explicitly outside synchronization scope. |

## Idempotency and simulation

`build_reconciliation_plan` is a pure function whose output order mirrors the
source-record order. `simulate_apply` pairs plan entries and source records
positionally, verifies row and identity agreement, and materializes only
`CREATE_MISSING` entries in memory. Duplicate row labels are preserved rather
than collapsed through a dictionary. Count, order, or identity mismatches fail
closed with fixed diagnostics.

Passing the simulated records into a second plan reclassifies prior creates as
updates, so a repeated dry run does not propose duplicate creates.

## Reporting and boundaries

`plan_to_dict` and `plan_to_json` provide machine-readable output;
`plan_to_summary` provides readable counts. `dry_run` and
`zero_write_confirmed` remain true for planner-produced output.

The planner does not prove live Drive existence, read Google Sheets or Notion,
measure real duplicate rates, or perform end-to-end synchronization. Optional
read adapters remain separately authorized, and all external writes remain
excluded.
