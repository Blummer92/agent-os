# Visual Asset Drive Writer

Bounded #958 capability for persisting a teacher-confirmed visual asset to an exact governed Google Drive destination.

## Current implementation boundary

This package is **offline-first**. It imports no Google SDK, holds no credentials, and performs no live Drive calls by itself. `write_asset()` defaults to `dry_run=True`; dry-run validates the request and computes the deterministic operation key while making zero client calls. Non-dry execution exists only behind an injected `DriveClient` protocol so idempotency, ambiguous-create reconciliation, and exact readback verification can be proven with fakes before any separately authorized live adapter/pilot.

A valid new-write request requires:

- routing state `CONFIRMED`;
- `teacher_confirmed=True`;
- current exact destination evidence;
- explicit `ORIGINAL` or `NORMALIZED` representation;
- exact content SHA-256;
- exact parent folder ID.

Filename/local path is not an idempotency key. The operation key binds intake identity, selected representation, content fingerprint, and exact destination. An ambiguous post-create failure reconciles by operation key before any further create. `VERIFIED` is returned only after exact readback matches file identity, parent, MIME type, content fingerprint, and operation key.

## Authority boundary

This package does not route assets, choose original versus normalized representation, create folders, alter sharing/ACLs, write Notion, construct ArtifactManifest, infer rights/privacy, or grant approval, classroom readiness, publication, or production authority.

The next live step requires separate authorization naming the exact Drive execution target and scope. #959 consumes only verified Drive evidence; #954 later coordinates the writers.

## Tests

`python -m pytest tests -q`

Tests use only an injected in-memory fake and require zero network access, credentials, or Google APIs.
