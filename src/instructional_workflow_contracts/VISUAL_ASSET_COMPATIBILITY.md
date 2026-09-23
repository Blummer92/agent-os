# Visual Asset Compatibility

This pure deterministic boundary binds one normalized Visual Asset Library record to one exact asset in one validated `ArtifactManifest` and preserves governed evidence for candidate filtering.

Supported IDs are `curriculum-visual-asset-compatibility-v1` and `curriculum-visual-asset-compatibility-v2`. `CONTRACT_ID` remains v1. Dispatch uses only exact `compatibility_evidence.contract_version`; unsupported versions fail closed, no automatic conversion occurs, and v2 fields never appear in v1 output.

## Ownership and inference boundary

`ArtifactManifest` owns manifest/asset identity, duplicate and canonical disposition, context preservation, direct-use and repair-source status, replacement state, verification, and lifecycle evidence. The normalized `ExistingAssetRecord` owns working Visual Asset Library page and Drive identity. This contract owns validated candidate-specific purpose, accessibility, orientation, approved use, freshness, classification, reasons, and v2 cohesion. Candidate filtering owns deterministic projection.

Titles, filenames, MIME types, captions, prompts, notes, comments, `extra_fields`, image bytes/content, OCR, computer vision, caller scores, and free-form fields cannot manufacture governed evidence.

## Exact inputs and governed groups

The top level contains exactly `library_record`, `artifact_manifest`, and `compatibility_evidence`. The library record must be a normalized `ExistingAssetRecord` or exact built-in mapping. The manifest must be raw or validated `curriculum-artifact-manifest-v1` evidence whose identity and fingerprint reconstruct exactly.

V1 evidence contains exactly `contract_version`, `manifest_reference`, `asset_reference`, `library_reference`, `purpose`, `accessibility`, `orientation`, `approved_use`, `freshness`, and `authority`. V2 contains all v1 fields plus required `cohesion_profile`. V1 with cohesion, v2 without cohesion, unknown fields, wrong built-in types, malformed identities, incompatible revisions, fingerprint/verification contradictions, or Drive identity mismatch are invalid.

Validated bounded groups are:

- `manifest_reference`: manifest ID, positive built-in integer revision, SHA-256 fingerprint, `verified_at`, external file ID.
- `asset_reference`: asset ID, stable reference, SHA-256 content fingerprint.
- `library_reference`: page ID and Drive file ID.
- `purpose`: canonical role types and built-in boolean `decorative_only`.
- `accessibility`: review state, description state, nullable description reference.
- `orientation`: controlled orientation and aspect state.
- `approved_use`: controlled state, canonical role types, canonical material types.
- `freshness`: manifest revision/fingerprint/verification, compatibility verification, built-in boolean `stale`.
- `authority`: exact all-false values.

Role collections allow at most 10 entries; approved material types allow at most 16; shared serialized-result limits apply.

## V2 cohesion profile

The exact required profile is controlled as follows; every `unspecified` controlled value routes to manual review and is never inferred.

| Field | Allowed value/type |
|---|---|
| `visual_style_family` | `instructional`, `documentary`, `editorial`, `technical`, `interface`, `unspecified` |
| `medium` | `digital`, `photographic`, `vector`, `raster`, `screen-capture`, `mixed-media`, `unspecified` |
| `representation_class` | `illustration`, `photography`, `diagram`, `interface-capture`, `unspecified` |
| `palette_family` | `full-color`, `limited-color`, `monochrome`, `grayscale`, `unspecified` |
| `line_treatment` | `none`, `clean`, `technical`, `organic`, `sketch`, `unspecified` |
| `rendering_style` | `flat`, `realistic`, `simplified`, `annotated`, `wireframe`, `unspecified` |
| `perspective` | `front`, `three-quarter`, `top-down`, `isometric`, `orthographic`, `mixed`, `unspecified` |
| `background_treatment` | `transparent`, `plain`, `isolated`, `contextual`, `interface`, `unspecified` |
| `complexity_rating` | built-in integer 1–5; booleans, floats, strings, and out-of-range values invalid |
| `cognitive_load_rating` | built-in integer 1–5; booleans, floats, strings, and out-of-range values invalid |
| `audience_compatibility` | exact group below |

`audience_compatibility` contains exact fields `state`, nullable stable `reviewer_ref`, nullable `reviewed_at`, nullable stable `evidence_reference`, built-in boolean `stale`, and built-in boolean `contradictory`. State is one of `approved`, `rejected`, `not-assessed`, `pending`, `manual-review-required`, or `unspecified`. Approval/rejection is attributable only when reviewer, timestamp, and evidence reference are all present. Attributable rejection is hard rejection; unattributed approval/rejection, stale/contradictory evidence, and all nonfinal states require manual review.

## Classification and output

Validated records classify as `eligible`, `hard-rejection`, or `manual-review-required`; malformed input returns invalid with no record. Hard rejection includes decorative-only purpose, failed accessibility, missing required description, aspect mismatch, denied/expired use, `interface-capture` with non-`screen-capture` medium, and attributable audience rejection. Manual review includes missing asset association/roles, incomplete accessibility, unspecified orientation, pending use, missing approved roles/materials, stale evidence, any unspecified cohesion value, and stale, contradictory, unattributed, pending, unassessed, manual-review-required, or unspecified audience evidence. Hard rejection takes precedence.

Every record preserves contract version, compatibility ID, classification, reason codes, manifest/asset/library references, purpose, accessibility, orientation, approved use, freshness, matched asset, and authority; v2 also preserves complete cohesion. V2 `matched_asset` adds duplicate relationship, disposition, canonical reference, duplicate group, required/preserved context flags, context completeness, direct-use status, repair-source status, and replacement-required state. V1 matched-asset behavior remains unchanged.

`compatibility_id` is deterministic and version-bound. Records are immutable, revision `1`, and SHA-256 fingerprinted over exact normalized payloads.

## Authority and rollback

All authority fields—execution, external write, production, publication, and side effects—must be built-in `false`. The contract performs no retrieval, ranking, scoring, selection, prompt construction, generation, image decoding, OCR, embeddings, vector search, computer vision, GPU/model use, network/filesystem write, Notion/Drive access, publication, readiness/approval mutation, or production action.

Rollback removes only additive v2 compatibility support, focused fixture/tests, and this documentation. V1 behavior needs no migration; manifests, Visual Asset Sync, Drive, Notion, and classroom artifacts need no cleanup.
