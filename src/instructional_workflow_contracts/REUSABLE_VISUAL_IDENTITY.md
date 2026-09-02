# Governed Reusable Visual Identity

## Purpose

`governed-reusable-visual-identity-v1` is the canonical pure contract for issuing
or reconciling Agent OS identity for a reusable visual that does not yet have a
canonical Asset ID. It is generic across icons, photographs, illustrations,
diagrams, interface captures, and other reusable visual types.

It is not an asset registry. It performs no retrieval, persistence, image
inspection, classification, rights/privacy decision, approval, or external
write. It returns deterministic validated identity evidence that downstream
ArtifactManifest, Visual Asset Library, Icon System, compatibility, and PPUX
projections may reference.

## Identity owner and API

Canonical issuance is owned by the instructional workflow contract layer through:

```python
issue_reusable_visual_identity(value)
```

The exact identity basis is:

- contract version;
- verified external provider/file/exact-reference identity;
- exact content SHA-256;
- exact provenance source reference/fingerprint/evidence reference;
- explicit lineage relationship and predecessor identity for derivatives.

The basis deliberately excludes filenames, titles, folder names, Notion prose,
visual classification, Icon System state, PPUX application/context state,
display order, timestamps alone, and model suggestions.

New canonical identity is deterministic:

- `asset_id = visual-asset-<first 24 hex chars of basis SHA-256>`;
- `stable_ref = visual-ref-<full basis SHA-256>`;
- initial record revision is `1`.

Drive `file_id`, Drive/shared-drive identity, exact external reference, canonical
Asset ID, and `stable_ref` remain distinct values. The contract rejects an
existing Asset ID/stable ref that aliases external identity.

## Existing identity reconciliation

A preassigned Asset ID is preserved only when supplied with verified binding
evidence whose fingerprint covers the exact current identity basis, Asset ID,
stable ref, evidence reference, and revision. Multiple conflicting identities or
revisions fail closed. Retrying the same exact evidence is idempotent.

## Lineage and renditions

`original` has no predecessor. `sanitized-derivative`, `rendition`, and
`superseding-version` require exact predecessor Asset ID and stable ref. Changed
content/external identity therefore creates a new deterministic identity whose
lineage remains explicit instead of silently reusing the predecessor identity.

## Standalone ArtifactManifest v2

`curriculum-artifact-manifest-v1` remains unchanged and MaterialRequirement-bound.
`curriculum-artifact-manifest-v2` is additive and currently supports the exact
`standalone-reusable-visual` subject. Its `subject_reference.identity_evidence`
must validate through `governed-reusable-visual-identity-v1` and match exactly
one manifest asset by Asset ID, stable ref, and content fingerprint. The manifest
reuses the existing v1 validators for external identity, rights, privacy,
transformations, quality, classroom readiness, references, and all-false
authority evidence.

No MaterialRequirement is fabricated for a standalone reusable visual.

## Compatibility v2

`validate_standalone_visual_asset_compatibility_evidence()` is the additive
compatibility-v2 entrypoint for standalone ArtifactManifest v2. It reuses the
existing compatibility-v2 evidence validators, exact library/Drive binding,
asset matching, freshness rules, cohesion rules, classification, and authority
behavior. Existing v1-manifest compatibility entrypoints remain unchanged.

The #1377 interface-capture acceptance shape is represented generically as:

- `visual_style_family = interface`;
- `medium = screen-capture`;
- `representation_class = interface-capture`;
- `background_treatment = interface`.

PPUX then adds application/context-state and current-UI claim semantics above the
generic governed identity and compatibility layers; it does not own Asset ID.

## Safety boundary

This lifecycle performs no Drive/Notion/schema/sharing mutation, creates no Icon
System identity, creates no PPUX-specific registry, and grants no execution,
external-write, production, or publication authority.
