# Visual Asset Drive Writer

Bounded #958 capability for persisting a teacher-confirmed visual asset to an exact governed Google Drive destination.

## Ownership and governance

Implementation ownership follows `02_Agent_Overlays/google-workspace-automation-engineer.md` and repository-write ownership follows `04_Registry/responsibility-matrix.md`. Workspace write authorization is governed by `01_Shared_Standards/google-workspace/workspace-write-authorization.md`, with Drive safety in `01_Shared_Standards/google-workspace/drive-docs-sheets-safety.md`. Those canonical sources control authorization; this README documents only this package's implementation boundary.

## Current implementation boundary

This package is **offline-first**. It imports no Google SDK, holds no credentials, and performs no live Drive calls by itself. `write_asset()` defaults to `dry_run=True`; dry-run validates the request and computes the deterministic operation key while making zero client calls. Non-dry execution exists only behind an injected `DriveClient` protocol so idempotency, ambiguous-create reconciliation, and exact readback verification can be proven with fakes before any separately authorized live adapter/pilot.

A valid new-write request requires:

- routing state `CONFIRMED`;
- `teacher_confirmed=True`;
- current exact destination evidence;
- explicit `ORIGINAL` or `NORMALIZED` representation;
- exact content SHA-256;
- exact parent folder ID.

Filename/local path is not an idempotency key. The operation key binds intake identity, selected representation, content fingerprint, and exact destination. Existing-operation reconciliation and ambiguous post-create reconciliation both require exact `fetch_file()` readback before returning verified reconciliation evidence. `VERIFIED` is returned only after exact readback matches file identity, parent, MIME type, content fingerprint, and operation key.

This package does not route assets, choose original versus normalized representation, create folders, alter sharing/ACLs, write Notion, construct ArtifactManifest, infer rights/privacy, or grant approval, classroom readiness, publication, or production authority. #959 consumes only verified Drive evidence; #954 later coordinates the writers.

## Tests

`python -m pytest tests -q`

Tests use only an injected in-memory fake and require zero network access, credentials, or Google APIs.
