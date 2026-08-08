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

`Add` confirms only the exact routing plan. It grants no execution or external-write authority. `Change` preserves the prior advisory suggestion while recording the explicit teacher correction and re-applies duplicate/destination safeguards. `Skip` terminates routing with no downstream execution.

Exact/normalized duplicate evidence is preserved from #953 and routes to `Use Existing | Review`. Supplied possible-near-duplicate evidence can expose `Use Existing | Keep New | Review` only when an existing identity is supplied. Ambiguous or invalid duplicate evidence, privacy/provenance concerns, and stale/missing destinations block normal Add.

## Package boundary

#957 owns only provider-neutral semantic recommendation and teacher confirmation. Cross-system ownership, write authorization, and downstream authority remain governed by:

- [`00_Governance/ownership-and-source-of-truth.md`](../../00_Governance/ownership-and-source-of-truth.md)
- [`00_Governance/write-authorization-policy.md`](../../00_Governance/write-authorization-policy.md)
- [`02_Agent_Overlays/google-workspace-automation-engineer.md`](../../02_Agent_Overlays/google-workspace-automation-engineer.md)
- [`02_Agent_Overlays/integration-manager.md`](../../02_Agent_Overlays/integration-manager.md)

The package never mints a canonical Asset ID, invents destination identifiers, grants rights/privacy clearance, approval, classroom readiness, publication, production authority, or performs image generation. #952/#953 remain upstream; #958/#959 and #954 remain downstream.

## Dependencies

Python standard library only. No provider SDK, OCR, CV, embeddings, vector database, or workflow framework is required.
