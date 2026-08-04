# Visual Asset Compatibility

The visual asset compatibility contract is a pure validation boundary that binds one Visual Asset Library record to one exact asset inside one valid `ArtifactManifest`.

Supported versions:

- `curriculum-visual-asset-compatibility-v1`
- `curriculum-visual-asset-compatibility-v2`

V1 behavior and deterministic identity remain unchanged. V2 adds explicit visual-cohesion and audience-compatibility evidence.

## Input envelope

The validator accepts exactly three fields:

- `library_record`: one normalized `ExistingAssetRecord` or its exact built-in mapping;
- `artifact_manifest`: raw or validated `curriculum-artifact-manifest-v1` evidence;
- `compatibility_evidence`: bounded identity, purpose, accessibility, orientation, approved-use, freshness, and all-false authority evidence.

V2 requires one additional exact `cohesion_profile`. Unknown fields, missing required fields, malformed identities, incompatible revisions, fingerprint mismatches, and library-to-manifest Drive identity mismatches fail closed.

## V2 cohesion profile

The profile requires exact controlled values for visual style family, medium, representation class, palette family, line treatment, rendering style, perspective, and background treatment.

`complexity_rating` and `cognitive_load_rating` must be built-in integers from 1 through 5. Boolean values, strings, floats, and out-of-range integers are invalid.

Audience compatibility requires:

- `state`;
- nullable `reviewer_ref`;
- nullable `reviewed_at`;
- nullable `evidence_reference`;
- built-in boolean `stale`;
- built-in boolean `contradictory`.

The validator preserves supplied evidence and does not infer cohesion from titles, descriptions, metadata, or other free-form fields.

## Classifications

- `eligible`: all supplied governed evidence permits downstream candidate filtering.
- `hard-rejection`: supplied evidence proves incompatibility.
- `manual-review-required`: evidence is valid but incomplete, stale, contradictory, not assessed, pending, unspecified, or insufficiently attributable.
- invalid `ValidationResult`: the envelope, evidence, or an upstream contract is malformed.

Hard rejection includes decorative-only purpose, failed accessibility review, missing required description, orientation mismatch, denied or expired approved use, incompatible representation and medium evidence, and attributable human-reviewed audience rejection.

Unspecified cohesion values route to manual review. Stale, contradictory, or unattributed audience evidence also routes to manual review.

## Boundaries

This contract performs no retrieval, ranking, scoring, selection, prompt construction, generation, image decoding, OCR, embedding, computer vision, model invocation, network access, filesystem write, publication, or production action.

Free-form library fields and `extra_fields` cannot manufacture governed compatibility or cohesion evidence.

Every output is deterministic, immutable, SHA-256 fingerprinted, bounded by the shared result-size ceiling, and carries all authority fields as `false`.

## Rollback

Rollback is removal or reversion of the additive v2 cohesion fields, focused fixture and tests, and this document update. V1 identities and behavior require no migration. Existing `ArtifactManifest`, Visual Asset Sync, Drive, Notion, and classroom artifact behavior require no cleanup.
