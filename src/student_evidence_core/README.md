# Student Evidence Core

Issue #848 defines a pure-local contract boundary for student evidence identity, provenance, organization proposals, teacher decisions, and projections.

## Ownership and reuse

- Provider-native systems remain authoritative for original artifacts and revisions.
- This package stores exact provider-native identifiers and stable references; it never promotes filenames into canonical identity.
- Derived responses bind to source revision, extraction recipe/version, confidence, trust, and review state.
- Organization proposals keep the machine suggestion, teacher correction, proposal state, and execution result distinct.
- Teacher decisions are separate immutable records and are never inferred from proposal state.
- Deterministic JSON serialization and SHA-256 fingerprinting are local utilities for these contracts only; no retry, client, persistence, authorization, or provider framework is introduced.

## Reused boundaries

The package is intentionally compatible with existing `visual_asset_sync`, `instructional_evidence_intake`, and `instructional_workflow_contracts` packages without importing or changing their public behavior. Those packages remain owners of their existing domain models and provider-specific normalization logic.

## Safety boundary

The package performs no network, filesystem, database, Notion, Drive, Microsoft 365, Adobe, OCR, model, or external-system access. All authority fields in `ProjectionRecord` are required to remain false. The contracts grant no grading, curriculum, movement, publication, or external-write authority.

Rollback is repository-local: revert `src/student_evidence_core/` and its focused tests. No external cleanup is required.
