# Visual Asset Ingestion Coordinator

Bounded offline coordinator for Issue #954.

## Boundary

The coordinator owns orchestration only. It must delegate image intake, duplicate reconciliation, semantic routing, Drive persistence, Notion synchronization, and ArtifactManifest validation to their existing canonical interfaces.

It must not reimplement #952, #953, #957, #958, or #959 behavior and must not create a second manifest contract.

## Required sequence

1. Validate the confirmed routing and execution-authorization evidence.
2. Reconcile duplicate and destination freshness before mutation.
3. Delegate Drive persistence to the #958 writer and require verified readback evidence.
4. Delegate Notion synchronization to the #959 writer and require verified destination evidence.
5. Build ArtifactManifest input only from supplied and verified evidence.
6. Run the canonical `validate_artifact_manifest` validator.
7. Return an ingested-candidate receipt; never infer classroom readiness or publication authority.

## Repair behavior

Verified external identities are checkpoints. A Drive success followed by a Notion failure preserves the Drive identity for retry. A verified Notion result followed by manifest failure preserves both external identities. Ambiguous external outcomes stop broad retry and require reconciliation.

Dry-run performs zero writer calls. Offline tests use injected fakes only.

## Authorization

This package does not contain Google or Notion credentials or live adapters. Live Drive/Notion execution, connected pilots, sharing changes, production activation, and classroom publication remain separately authorized.
