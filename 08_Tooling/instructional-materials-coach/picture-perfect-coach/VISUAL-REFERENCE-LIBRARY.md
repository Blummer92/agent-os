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
