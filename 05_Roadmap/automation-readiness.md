# Agent OS Automation Readiness

## Purpose

This note defines the safe automation boundary for Agent OS before dry-run classroom artifact workflows, live writes, or issue-to-PR automation are added.

It is an implementation-readiness note only. It does not authorize live writes, change governance, or expand Agent OS scope.

## Current Safe Automation Boundary

Safe after A2 is merged:

- Manual issue-by-issue implementation.
- Read-only roadmap and issue review.
- Local aggregate validation with `./scripts/validate-all.sh`.
- Pull-request validation through the `Agent OS Validation Gate` GitHub Actions workflow on the self-hosted `agent-os` runner.
- Manual GitHub Actions validation through workflow dispatch on the self-hosted `agent-os` runner.
- Weekday scheduled GitHub Actions validation on the self-hosted `agent-os` runner.
- Documentation-only readiness notes that clarify sequencing and safety.

Not yet safe:

- Issue-to-PR automation.
- Daily autonomous code edits.
- Unattended live Google Drive writes.
- Automatic source-of-truth updates.
- Automatic governance changes.
- Automatic live classroom artifact generation.

## Dependency Ladder

1. **After A1 (#106):** The local aggregate validation command `./scripts/validate-all.sh` is safe to run manually.
2. **After A2a (#143):** A self-hosted Agent OS runner labeled `agent-os` is available for validation jobs.
3. **After A2 (#107):** GitHub Actions validation is safe on pull requests, manual dispatch, and a scheduled weekday run when it uses the self-hosted `agent-os` runner.
4. **After C3 (#118):** A dry-run classroom artifact workflow is safe when it produces receipts and does not write to live Google Drive.
5. **After explicit approval and C4 (#119):** A governed live artifact run may be performed only inside the approved workflow and destination boundaries.

## Blocked Automation

Blocked until C3 exists:

- Classroom artifact workflow dry-runs through the Scheduler -> Materials Coach path.
- Any repeatable classroom artifact workflow validation.

Blocked until a future governed workflow is explicitly approved:

- Automatic issue-to-branch implementation.
- Automatic issue-to-PR implementation.
- Any automation that commits, pushes, opens pull requests, or changes source-of-truth records without human approval.

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

After A2 is merged, continue the M1 validation/status work before attempting any issue-to-PR automation.

Reason: A2 creates a validation-only GitHub Actions gate on a self-hosted Agent OS runner. It does not create autonomous implementation or build-from-issue behavior.

## Stop Conditions

Stop before automation if:

- the target system of record is unclear;
- authorization is unclear;
- the automation would modify live systems before a dry-run exists;
- the automation would write to Google Drive without an approved folder and explicit approval;
- the automation would update source-of-truth, governance, sharing, readiness, approval, or ownership fields automatically;
- the automation would bypass the issue sequence A1 -> A2a -> A2 -> C3 -> C4.

## Status

After this A2 workflow is merged, Agent OS is ready for validation-only GitHub Actions on pull requests, manual dispatch, and weekday scheduled runs through the self-hosted `agent-os` runner. It is not ready for issue-to-PR automation, dry-run classroom workflows, or live classroom artifact generation.
