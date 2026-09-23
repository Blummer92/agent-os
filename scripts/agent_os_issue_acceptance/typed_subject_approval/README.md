# Typed-subject approval successor

Issue #1976 adds an **additive** typed-subject seam over the canonical #398 approval lifecycle and #407 approved-execution projection.

- Approval schema successor: `1.2`.
- Projection schema successor: `1.1`.
- Supported subject kind: `instructional-materials-live-operation`.
- Supported subject schema: the public #1975 `instructional-materials-live-operation-subject-v1` contract.
- Stored subject binding is only `subject_kind`, `subject_schema_version`, and `subject_id`.
- Candidate construction and currentness require the complete subject object and recompute the reference with `validate_live_operation_subject`; arbitrary subject-ID strings are never accepted as approval input.
- Approval lifecycle state, decision revisions, expiry, invalidation, supersession, and repository/proposal applicability remain delegated to `approval_records.py`.
- The projection composes the existing #407 `1.0` projection and carries the exact typed subject reference plus typed approval ID/revision.
- Typed approval and projection objects remain `execution_authorized=false`; the projection also remains `authoritative=false` and `side_effects_performed=false`.

Historical #398 approval schemas `1.0` and `1.1`, historical #407 projection schema `1.0`, `implementation_contract_fingerprint`, and WSC3 proposal/handoff identity are not modified. There is no automatic conversion of historical records.

This package performs no Scheduler dispatch, Google/provider access, credential discovery, persistence, production execution, or external write. #1196 must still supply separate exact-invocation execution/live-write authorization before any Google mutation.

## Rollback

Remove this additive package, its focused tests, and this note. Historical approval/projection schemas and the #1975 subject contract remain independently valid.
