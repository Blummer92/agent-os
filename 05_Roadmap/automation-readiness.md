# Agent OS Automation Readiness

## Purpose

This note defines the safe automation boundary for Agent OS before scheduled builds, CI workflows, dry-run classroom artifact workflows, or live writes are added.

It is an implementation-readiness note only. It does not implement A1, create GitHub Actions, authorize live writes, change governance, or expand Agent OS scope.

## Current Safe Automation Boundary

Safe now:

- Manual issue-by-issue implementation.
- Read-only roadmap and issue review.
- Preparation and planning of validation commands.
- Documentation-only readiness notes that clarify sequencing and safety.

Not yet safe:

- Daily autonomous code edits.
- Unattended live Google Drive writes.
- Automatic source-of-truth updates.
- Automatic governance changes.
- Automatic live classroom artifact generation.

## Dependency Ladder

1. **Current state:** Only manual issue-by-issue implementation and read-only review are safe.
2. **After A1 (#106):** A local aggregate validation command is safe to run manually.
3. **After A2 (#107):** GitHub Actions validation is safe on pull requests, manual dispatch, and a scheduled daily run.
4. **After C3 (#118):** A dry-run classroom artifact workflow is safe when it produces receipts and does not write to live Google Drive.
5. **After explicit approval and C4 (#119):** A governed live artifact run may be performed only inside the approved workflow and destination boundaries.

## Blocked Automation

Blocked until A1 exists:

- Any scheduled or CI automation that depends on a repo-wide aggregate validation command.
- Any daily build claiming to validate the whole repository.

Blocked until A2 exists:

- Pull-request validation through GitHub Actions.
- Manual GitHub Actions validation through workflow dispatch.
- Scheduled daily GitHub Actions validation.

Blocked until C3 exists:

- Classroom artifact workflow dry-runs through the Scheduler -> Materials Coach path.
- Any repeatable classroom artifact workflow validation.

## Approval-Required Automation

The following require explicit approval and live-system boundary confirmation before use:

- Live Google Drive writes.
- Live classroom artifact generation.
- Production system changes.
- Source-of-truth updates.
- Governance changes.
- Sharing, readiness, approval, ownership, or other governed-field changes.
- Any automation that modifies irreversible artifacts.

## Recommended Next Issue

Start with **A1 — Add repo-wide aggregate test runner** (#106).

Reason: A1 creates the local validation command that A2 and later scheduled automation depend on. Without A1, a daily build or CI workflow would not have a safe, canonical command to run.

## Stop Conditions

Stop before automation if:

- the target system of record is unclear;
- authorization is unclear;
- the automation would modify live systems before a dry-run exists;
- the automation would write to Google Drive without an approved folder and explicit approval;
- the automation would update source-of-truth, governance, sharing, readiness, approval, or ownership fields automatically;
- the automation would bypass the issue sequence A1 -> A2 -> C3 -> C4.

## Status

Agent OS is ready to begin issue #106. It is not yet ready for scheduled GitHub Actions, daily automated builds, dry-run classroom artifact workflows, or live classroom artifact generation.
