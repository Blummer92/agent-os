# Sync Safety Validation Checklist

## Purpose

Checklist and test matrix for dry-run-first Drive or Sheets to Notion sync
workflows.

## Decision Standard

A write is allowed only when dry-run, target, approval, and verification-count
checks pass for the exact batch under review.

## Required Fixtures

- rows 2-11 with at least one missing `file_id`
- 25-row fixture ending with a non-null next cursor
- 50-row fixture validating multi-batch cursor progression
- final batch fixture where `nextCursor` is null
- distinct staging and Visual Asset Library target IDs
- approval properties absent, false, and true

## Required Test Areas

- row scope guard rejects out-of-range rows
- cursor math for rows 2-11, 25-row, 50-row, and final batches
- missing `file_id` is skipped and counted
- payload fields map from intended source columns
- target selection resolves distinct database IDs and approval keys
- dry run invokes no write path
- write gate blocks unless dry run passed
- production or library writes block without target-specific approval
- count mismatches block write approval

## Pre-Write Review

Require source evidence, bounded range, dry-run receipt, skipped-record list,
target database match, explicit approval property, and count verification.

## Failure Conditions

Block when a write is attempted from a dry-run path, rows outside scope are used,
cursor math skips or repeats rows, staging approval is reused for library writes,
missing `file_id` creates a partial payload, or counts drift.

## Version

0.1.0
