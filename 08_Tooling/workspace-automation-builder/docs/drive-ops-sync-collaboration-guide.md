# Drive Operations Sync Collaboration Guide

## Purpose

Shared protocol for Drive or Sheets discovery, Apps Script dry runs, and Notion
write-safety review.

## Operating Rule

Discovery may collect, normalize, and dry-run evidence. Validation must approve
that evidence before any production or Visual Asset Library write path is enabled.

## Handoff Packet Fields

Every handoff should include:

- `schema_version` equal to `sync-handoff.v1`
- `sheet_id` and `range_a1`
- `row_scope` with first data row, start row, end row, batch size, and cursor
- `target` as `staging` or `visual_asset_library`
- `field_mapping`
- `approval_key_required`
- `skipped_records`

Missing fields stop the workflow during review, not during a live write.

## Recommended Workflow

1. Collect bounded source data and create a manifest.
2. Run an Apps Script dry run that builds payloads only.
3. Validate row scope, cursor math, target selection, mapping, and skips.
4. Compare candidate, verified, and planned synced counts.
5. Set explicit approval only after validation passes.
6. After write, require `synced_count === verified_count`.

## Write Gates

- Dry-run gate: blocks missing, false, or stale dry-run receipts.
- Approval gate: blocks missing or wrong-target approval.
- Target gate: blocks target database mismatches.
- Count gate: blocks `synced_count !== verified_count`.

## Failure Handling

Wrong target database selection is high risk. Missing `file_id` is a skip, not a
partial payload. Staging receipts cannot authorize Visual Asset Library writes.
If code or docs cannot be inspected, confidence is incomplete.

## Version

0.1.0
