# Visual Asset Routing

Bounded deterministic semantic routing for Agent OS Issue #957, with the per-asset Icon System classification gate from #1025 and mixed-folder regression contract from #1026.

The package consumes already-supplied/provider-neutral semantic observations, duplicate evidence from #953, governed read-only destination references, and explicit per-asset visual classification evidence. It does not inspect image pixels, call a model, search Notion/Drive, or perform external writes.

## Per-asset Icon System classification gate

Every asset must carry its own bounded type (`ICON`, `PHOTOGRAPH`, `ILLUSTRATION`, `DIAGRAM`, `OTHER_VISUAL`, or `AMBIGUOUS`) before it can be considered for the Icon System path. A positive `ICON` decision is eligible only when backed by per-asset visual inspection or teacher-confirmed visual evidence.

Folder names, filenames, extensions, batch context, and teacher batch wording are intent/context signals only. They cannot independently establish that an asset is an icon. Non-icons stay out of the Icon System path, and `AMBIGUOUS` fails closed for that asset without contaminating neighboring classifications. Batch evaluation is a pure per-item projection, so one asset's result is never inherited by another.

Classification is advisory routing evidence only. It grants no execution, external-write, approval, classroom-readiness, rights, privacy, source-authority, publication, or production authority. Downstream #959 continues to own destination-specific Notion mutation and must consume confirmed upstream classification rather than inspect image semantics itself.

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

#957 owns provider-neutral semantic recommendation and teacher confirmation. #1025 adds only the per-asset type gate needed before an Icon System decision, while #1026 supplies synthetic regression evidence for mixed collections. Cross-system ownership, write authorization, and downstream authority remain governed by:

- [`00_Governance/ownership-and-source-of-truth.md`](../../00_Governance/ownership-and-source-of-truth.md)
- [`00_Governance/write-authorization-policy.md`](../../00_Governance/write-authorization-policy.md)
- [`02_Agent_Overlays/google-workspace-automation-engineer.md`](../../02_Agent_Overlays/google-workspace-automation-engineer.md)
- [`02_Agent_Overlays/integration-manager.md`](../../02_Agent_Overlays/integration-manager.md)

The package never mints a canonical Asset ID, invents destination identifiers, grants rights/privacy clearance, approval, classroom readiness, publication, production authority, or performs image generation. #952/#953 remain upstream; #958/#959 and #954 remain downstream.

## Dependencies

Python standard library only. No provider SDK, OCR, CV, embeddings, vector database, or workflow framework is required.
