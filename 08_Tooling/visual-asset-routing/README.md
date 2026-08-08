# Visual Asset Routing

Bounded deterministic semantic routing for Agent OS Issue #957.

The package consumes already-supplied/provider-neutral semantic observations, duplicate evidence from #953, and governed read-only destination references. It does not inspect image pixels, call a model, search Notion/Drive, or perform external writes.

## Teacher-facing projection

A complete new-asset candidate can be rendered as:

```text
Looks like: Leading Lines
Best fit: Photography Foundations
Use: Composition example

Add | Change | Skip
```

`Add` confirms only the exact routing plan. It grants no execution or external-write authority. `Change` preserves the prior advisory suggestion while recording the explicit teacher correction. `Skip` terminates routing with no downstream execution.

Exact/normalized duplicate evidence is preserved from #953 and routes to `Use Existing | Review`. Ambiguous or invalid duplicate evidence, privacy/provenance concerns, and stale/missing destinations block normal Add.

## Boundaries

- #952 owns safe uploaded-image inspection.
- #953 owns deterministic duplicate identity/reconciliation.
- #957 owns provider-neutral semantic recommendation and teacher confirmation only.
- #961 owns reusable existing-asset selection for classroom artifact creation.
- #958 owns Drive writes.
- #959 owns Notion Visual Asset Library writes.
- #954 owns repair-safe ingestion coordination.

The package never mints a canonical Asset ID, invents destination identifiers, grants rights/privacy clearance, approval, classroom readiness, publication, production authority, or performs image generation.

## Dependencies

Python standard library only. No provider SDK, OCR, CV, embeddings, vector database, or workflow framework is required.
