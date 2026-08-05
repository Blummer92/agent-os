# Visual Asset Compatibility

`curriculum-visual-asset-compatibility-v1` is a pure validation contract that binds one Visual Asset Library record to one exact asset inside one valid `ArtifactManifest`.

## Input envelope

The validator accepts exactly three fields:

- `library_record`: one normalized `ExistingAssetRecord` or its exact built-in mapping;
- `artifact_manifest`: raw or validated `curriculum-artifact-manifest-v1` evidence;
- `compatibility_evidence`: bounded purpose, accessibility, orientation, approved-use, freshness, identity, and all-false authority evidence.

Unknown fields, malformed identities, incompatible revisions, fingerprint mismatches, and library-to-manifest Drive identity mismatches fail closed.

## Classifications

- `eligible`: all supplied governed evidence permits downstream candidate filtering.
- `hard-rejection`: supplied evidence proves the asset is not compatible, including decorative-only purpose, failed accessibility review, missing required description, orientation mismatch, or denied/expired approved use.
- `manual-review-required`: evidence is structurally valid but incomplete, stale, not assessed, pending, or cannot be associated with exactly one asset.
- invalid `ValidationResult`: the envelope or an upstream contract is malformed or contradictory.

A hard rejection remains a structurally valid compatibility record. Its rejection reasons are recorded in the validated payload. Manual-review classifications are also surfaced through `ValidationResult.status` and `reason_codes`.

## Boundaries

This contract performs no retrieval, ranking, scoring, selection, prompt construction, generation, image decoding, OCR, embedding, computer vision, model invocation, network access, filesystem write, publication, or production action. Free-form library fields and `extra_fields` cannot manufacture governed compatibility.

Every output is deterministic, immutable, SHA-256 fingerprinted, bounded by the shared result-size ceiling, and carries all authority fields as `false`.

## Rollback

Rollback is removal or reversion of the additive compatibility module, focused fixture and tests, and this document. Existing `ArtifactManifest`, Visual Asset Sync, Drive, and Notion behavior require no migration or cleanup.
