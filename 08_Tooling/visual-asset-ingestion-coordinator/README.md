# Visual Asset Ingestion Coordinator

Bounded offline coordinator for issue #954.

## Purpose

Compose the existing visual-asset pipeline without duplicating component logic:

`#952 intake -> #953 duplicate reconciliation -> #957 teacher-confirmed routing -> #958 Drive writer -> #959 Visual Asset Library / Icon System writer`.

When an image came from the governed external-generation workflow, the coordinator also preserves the merged #2564 generation/returned-image provenance. Ordinary teacher uploads remain valid without fabricated gap or ImageIntent history.

## Boundary

The package owns orchestration and repair-state projection only. It contains no Google, Notion, image, or provider client and grants no execution, external-write, approval, readiness, publication, or production authority.

Injected writer steps are caller-supplied executions of separately governed component boundaries. Dry-run calls none of them.

The coordinator never derives provenance from filenames, prompt text, provider/model claims, image similarity, source notes, or conversation memory.

## Repair behavior

Verified external identities are checkpoints. Drive success followed by metadata failure returns `DRIVE_VERIFIED_METADATA_PENDING`; ambiguous writer outcomes stop broad progression; a confirmed reusable icon is not fully synchronized until its Icon System step verifies.

Existing exact/normalized duplicates do not trigger a new binary write through this coordinator.

## Artifact-first rule

Successful ingestion or catalog registration is not classroom-artifact fulfillment. This package does not mutate lesson readiness, approval, publication, or production state.

## Authorization

Repository implementation and tests are offline. Live Drive/Notion execution, credentials, schema/sharing changes, production, classroom publication, merge, and issue closure remain separately governed.
