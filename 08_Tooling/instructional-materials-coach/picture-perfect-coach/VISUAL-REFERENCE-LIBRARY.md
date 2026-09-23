# PPUX Current-Application Visual-Reference Library

Issue: #1372

## Purpose

PPUX uses current application visual-reference evidence to establish what software currently looks like without treating a model-generated reconstruction as interface evidence.

```text
Recorder evidence = what the teacher did
Teacher Modeling = what students need to learn
Current application visual-reference evidence = what the software currently looks like
PPUX = selects the smallest state-specific evidence needed for the frame
```

No source silently overwrites another source's authority.

## Record and existing authority reuse

`src/visualReference.ts` is an additive projection over the existing ArtifactManifest and visual-asset compatibility evidence already consumed by PPUX capture binding. It is not a second asset registry.

A reusable reference carries application identity, optional application variant, context/state, capture/verification dates, source provenance, sanitized derivative identity, visible state-local UI claims, manifest identity, and stable asset identity.

Admission reuses existing requirements for verified access, classroom readiness, privacy resolution, cleared rights, direct-use readiness, no replacement requirement, eligible visual compatibility, `screen-capture` medium, `interface-capture` representation, and non-stale freshness.

## Teacher-supplied screenshot ingestion

A raw teacher screenshot is evidence only. Upload does not grant reuse.

A reusable reference requires a distinct sanitized derivative and explicit evidence that browser chrome and private context were removed. Cropping or transformation does not itself establish privacy clearance; unresolved privacy returns `manual-review-required`. Raw screenshots from the 2026-08-24 live PPUX test are not committed to Git.

## State taxonomy

The first Adobe Express acceptance corpus uses these application-neutral state keys:

```text
navigation/home
navigation/your-stuff/files
navigation/create-menu
creation/get-started
editor/shell
editor/add-content
editor/media
editor/elements
editor/generative-ai
editor/text/edit
editor/text/effects
editor/text/animation
editor/image/edit
editor/image/effects
editor/image/animation
editor/elements/backgrounds
editor/elements/background-filters
editor/elements/shapes
editor/shape/edit
editor/shape/fill-color
editor/shape/border-color
```

The keys are data, not executable agent identities, and other applications may define their own bounded states.

## Retrieval

Retrieval matches exact application identity, optional variant, and exact context/state. One reference must support every required UI claim. Claims from multiple references are never unioned to fabricate a screen.

When multiple eligible references satisfy the same state, selection is deterministic: newest verification date, then newest capture date, then reference ID.

## Current-vs-recorded conflict

Current visual evidence does not rewrite historical Recorder evidence. When a required current claim and the supplied recorded claim set disagree, selection returns `manual-review-required` with `visual-reference-current-recorded-ui-conflict`.

The minimum regression is Tutorial 0:

```text
historical evidence: Create new
current reference: Create -> Create file
```

PPUX must request reconciliation/recapture/manual review rather than silently substituting either label.

## Presentation boundary

An approved reference may produce a bounded presentation directive that names its stable asset reference and exact state. The directive requires preserving the supplied interface appearance and prohibits redrawing, reconstruction, invention, or mixing controls/labels/geometry/states from another reference.

This contract does not authorize image generation, live Adobe access, browser automation, external writes, or publication.

## Addressable regions and fill safety (#1485)

An approved reference's sanitized derivative may carry a `ReferenceRegionSet`: bounded, flat, non-nested `ReferenceRegion` entries (`region_id`, optional `claim`, `rect`, `fill_allowed`). There are no region roles, parent/child nesting, policy enum beyond `fill_allowed`, icon taxonomy, typography taxonomy, or fidelity enum.

`ReferenceRegion.rect` is `[x, y, width, height]`, normalized `[0,1]` against the sanitized derivative's own pixel box. That is the repository's existing rectangle ordering, shared with `TargetGeometry`'s `target_x/target_y/target_width/target_height` and with `TargetStyleEvidence.rect_normalized` in `src/captureEvidence.ts`, so #1485 introduces no second rectangle convention. Only the evidence space differs: capture geometry is raw capture-viewport pixels or normalized against the capture viewport, region geometry is normalized against the sanitized derivative. Nothing converts one space into the other, and both files carry an explicit cross-reference comment. Because the two spaces are numerically indistinguishable by rect shape alone, the enforced guarantee is identity binding (`reference_id` + `content_fingerprint`), not rect ordering.

`admitReferenceRegions()` fails closed unless: the region set's `reference_id` and `content_fingerprint` match the exact approved reference (so a recaptured derivative, whose `asset_reference.content_fingerprint` changes, can never silently inherit stale region geometry); every rect is in-bounds and non-degenerate; `region_id` values are unique; every non-null `claim` is present in that exact reference's `visible_ui_claims`; and no `fill_allowed:true` rect intersects a `fill_allowed:false` rect (`visual-reference-fill-region-overlaps-anchor`). Anchored (`fill_allowed:false`) regions may overlap other anchored regions; separate non-overlapping fill regions may coexist.

## Capture-v2 target style evidence (#1485)

Capture format v2 (`software-tutorial-capture-v2`, `src/captureEvidence.ts` and `capture/safe_recording.mjs`) adds one optional bounded `target_style: TargetStyleEvidence | null` on resolved action evidence, captured only from the already-resolved target handle in `capture/replay_capture.mjs` using a frozen `getComputedStyle` property allowlist (`TARGET_STYLE_PROPERTY_ALLOWLIST`). There is no DOM traversal and no per-child style trees.

RGBA is canonical for captured colors (`parseComputedColorToRgba`); hex is never persisted. Gradients, shadows, transforms, line height, letter spacing, and border radius remain bounded raw computed strings; no parsed style subsystem is introduced. `background_image` is sanitized before persistence (`sanitizeBackgroundImage`): bounded CSS gradient layers are retained, while `url(...)`, `blob:`, and `data:` layers (and any unsupported function) become `null` rather than persisting external/private resource identity.

Adding `target_style` does not change `fingerprintAction()` output, recording SHA/digest, source fingerprint joins, or F1/F2 identity binding — this is covered by a required regression test, not an assumption. Capture v1 remains supported unchanged (`buildCaptureEnvelope()` defaults to v1 and strips `target_style` from v1 output even if the caller's evidence happens to include it); `bindCaptureEvidence()` accepts both v1 and v2 and fails closed on any other `format_version`.

Canvas, WebGL, raster artwork, photographs, and other surfaces without trustworthy computed style are unaffected: source pixels remain authoritative, and no CV/OCR/texture inference is added.

## Validation

Focused acceptance coverage lives in `src/visualReference.test.ts`. The governing #1372 developer loop remains mandatory before Draft PR creation:

```bash
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm run guard
npm run test:e2e
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

The tests are offline and use metadata/synthetic references only.

## Rollback

Remove `src/visualReference.ts`, `src/visualReference.test.ts`, and this document. Existing F1/F2 capture evidence, ArtifactManifest, visual-asset compatibility, Recorder evidence, and prompt behavior remain unchanged.

For #1485 specifically: reverting `admitReferenceRegions`/`ReferenceRegion`/`ReferenceRegionSet` from `src/visualReference.ts` (and their tests) leaves the pre-#1485 reference-admission/selection contract unchanged. Reverting `target_style`/`TargetStyleEvidence`/`buildTargetStyleEvidence`/`sanitizeBackgroundImage`/`parseComputedColorToRgba` from `capture/safe_recording.mjs`, `capture/replay_capture.mjs`, and `src/captureEvidence.ts` (and their tests) leaves capture format v1 as the only supported format again; no action fingerprint, recording identity, or F1/F2 join depends on either addition.
