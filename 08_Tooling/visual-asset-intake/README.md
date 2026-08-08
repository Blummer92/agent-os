# Visual Asset Intake

Bounded local raster-image intake and deterministic duplicate reconciliation for Agent OS Issues #952 and #953.

## Public API

```python
from visual_asset_intake import (
    DuplicateCandidate,
    IntakePolicy,
    intake_visual_asset,
    reconcile_duplicate,
)

result = intake_visual_asset("candidate.jpg", output_dir="./derived")
duplicate = reconcile_duplicate(result, [DuplicateCandidate("asset-123", original_sha256="...")])
```

`intake_visual_asset` accepts one local JPEG, PNG, or WebP, enforces byte and decoded-pixel limits, records bounded technical observations, computes SHA-256 over exact source bytes, writes one metadata-stripped normalized PNG using an application-generated name, hashes that derivative, and returns immutable evidence with all authority false.

`reconcile_duplicate` consumes that evidence plus caller-supplied stable candidate identity and exact original/normalized SHA-256 evidence. Exact source matches may reconcile to an existing supplied identity; normalized matches remain distinguishable. Conflicting exact identities require manual review. Candidate ordering and filenames do not select identity.

Perceptual hashing is intentionally deferred. Resized, recompressed, cropped, and visually similar images do not become canonical matches without separately proven advisory similarity evidence.

## Safety boundary

- The original file is read-only and never overwritten.
- The default source ceiling is 25 MiB and decoded-pixel ceiling is 40 MP.
- SVG, GIF/animated or multi-frame images, PDF, archives, RAW, and unsupported raster formats fail closed.
- Pillow decompression-bomb protections remain enabled.
- EXIF orientation is applied to the derivative; GPS/private EXIF is not copied into it.
- CMYK and other non-alpha modes normalize to RGB; alpha-bearing inputs normalize to RGBA.
- Supplied filenames are display evidence only; derivative names come from the intake identity.
- Duplicate reconciliation performs no retrieval, semantic classification, mutation, deletion, archive action, or canonical-ID creation.
- No network, Drive, Notion, Google Cloud, AI, OCR, CV, generation, approval, privacy-clearance, rights-clearance, readiness, publication, or production action is performed.

## Identity boundary

Raw file identity uses chunked `hashlib.sha256()` over exact bytes. It is intentionally distinct from `instructional_workflow_contracts.common.sha256_hex`, which fingerprints canonical structured values. This package assigns only an intake identity and may reference a stable identity supplied by the caller; it never invents a canonical `asset_id`.

## Dependency decisions

Core runtime is Python plus Pillow. `puremagic` is omitted because Pillow decoded-format evidence plus mismatch tests are sufficient for this bounded V1. HEIC/HEIF is deferred: `pillow-heif` is not required until canonical validation environments prove its packaging cleanly. `ImageHash` is deferred because #953 exact original/normalized reconciliation does not require perceptual evidence.

## Downstream

Successful intake output is `READY_FOR_EXACT_DUPLICATE_LOOKUP` evidence for #953. Reconciliation output remains upstream evidence only. ArtifactManifest, duplicate lifecycle disposition, Visual Asset Compatibility, external identity ownership, rights/privacy resolution, approval, and classroom readiness remain downstream owners.

## References

Shared ownership and downstream rules:
- `01_Shared_Standards/instructional-design/instructional-materials-sources.md`
- `src/instructional_workflow_contracts/VISUAL_ASSET_COMPATIBILITY.md`

Implementation and verification surfaces:
- `08_Tooling/visual-asset-intake/src/visual_asset_intake/intake.py`
- `08_Tooling/visual-asset-intake/src/visual_asset_intake/duplicates.py`
- `08_Tooling/visual-asset-intake/src/visual_asset_intake/models.py`
- `08_Tooling/visual-asset-intake/src/visual_asset_intake/hashing.py`
- `08_Tooling/visual-asset-intake/tests/test_intake.py`
- `08_Tooling/visual-asset-intake/tests/test_duplicates.py`
