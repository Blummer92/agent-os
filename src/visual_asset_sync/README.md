# Visual Asset Sync — Reconciliation Planner

Deterministic, offline, dry-run reconciliation planner for moving reviewed
icon assets from the `Approved Use Review` Google Sheet into the Notion
Visual Asset Library. See Issue #693.

This package performs **zero external writes and zero network calls**. It
accepts already-normalized in-memory records and returns a plan. Live
Google Sheets reads, live Notion queries, and live Notion writes are
out of scope and are implemented by future adapters, not this planner.

## Input contract

`normalize_source_record` builds a `SourceAssetRecord` from a spreadsheet
row dict supporting at least: `drive_file_id`, `drive_url`, `file_name`,
`approved_use`, `audience`, `review_status`, `review_date`,
`visual_rationale`, `worksheet_fit`, `slideshow_fit`, `poster_fit`,
`format_decision_notes`, `source_row`. An optional `excluded` flag marks a
record as intentionally out of sync scope (for example, a non-icon asset)
without dropping it from the plan.

`normalize_existing_record` builds an `ExistingAssetRecord` from a Notion
record dict supporting at least: `page_id`, `page_url`, `drive_file_id`,
`drive_url`, `asset_title`, `approved_use`, `asset_type`,
`human_review_status`, `review_date`. Any other keys are preserved verbatim
in `extra_fields` so unrelated Notion fields are never lost.

## Identity precedence

1. `drive_file_id` is the authoritative identity key.
2. `drive_url` is used only when `drive_file_id` is absent, and only when an
   unambiguous Drive File ID can be extracted from it.
3. `file_name` never establishes identity; it is diagnostic only.
4. A `drive_file_id` present alongside a `drive_url` whose embedded ID
   disagrees produces `CONTRADICTORY_RECORD`.
5. No usable identity (no ID, and no URL or an unparseable URL) produces
   `MALFORMED_IDENTITY`.

## Result types

Every source record receives exactly one `ReconciliationResult`:

| Result | Meaning |
|---|---|
| `UPDATE_EXISTING` | Identity matches exactly one existing Notion record. |
| `CREATE_MISSING` | Identity is well-formed and matches no existing record. |
| `DUPLICATE_ID` | Identity matches more than one existing record, or more than one source record shares the identity. No write action is proposed. |
| `MALFORMED_IDENTITY` | No usable identity. No write action is proposed. |
| `CONTRADICTORY_RECORD` | Conflicting ID/URL evidence. No write action is proposed. |
| `EXCLUDED` | Record is explicitly marked out of sync scope. Represented, never silently dropped. |

## Idempotency

`build_reconciliation_plan` is a pure function of its two input
collections: identical inputs always produce an identical plan, in the
same order as the input source records. `plan.simulate_apply` returns a
new, in-memory existing-records collection with this plan's
`CREATE_MISSING` entries materialized as simulated pages, without mutating
its inputs. Passing that simulated collection into a second
`build_reconciliation_plan` call reclassifies those rows as
`UPDATE_EXISTING`, so a second run never proposes a duplicate create.

## Dry-run and reporting

`ReconciliationPlan.dry_run` is always `True` for output produced by this
package; `zero_write_confirmed` mirrors it. `report.plan_to_dict` /
`report.plan_to_json` produce the machine-readable plan, including per-entry
`preserved_fields` carried from the matched existing record. `report.plan_to_summary`
produces the human-readable summary.

## Boundary with future adapters

This package assumes normalized in-memory records. It has no Google Sheets
client, no Notion client, and issues no HTTP calls. Reading the spreadsheet,
querying Notion, and applying an approved plan as a real Notion write are
separate, separately authorized follow-up adapters.
