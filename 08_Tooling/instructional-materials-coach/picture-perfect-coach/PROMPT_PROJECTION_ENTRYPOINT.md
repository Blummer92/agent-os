# PPUX prompt projection entrypoint

Issue: #2524

`src/promptProjectionEntrypoint.ts` is the non-UI, side-effect-free boundary for obtaining canonical Picture Perfect prompt-card output from an already-resolved tutorial/process handoff.

## Input

The entrypoint accepts `picture-perfect-prompt-projection-input-v1` with:

- the existing `ReviewedTutorialProjection`;
- the existing `RoutedTutorialNeed`, including `routeId`, `sourceHandoffRef`, and `sourceFingerprint`;
- optional existing `CaptureEvidenceBundle`;
- optional existing `VisualReferenceLibrary`.

It does not accept raw Notion data, chat prose, provider instructions, arbitrary commands, or a second tutorial schema. Upstream curriculum/modeling source resolution remains outside this package.

## Projection

`projectTutorialPromptCards(value)` validates the bounded transport envelope and delegates semantic projection to the existing `buildTutorialPackage(...)` owner. That owner continues to use the canonical PPUX prompt projection, capture binding, current-reference selection, application identity, and fail-closed card behavior.

The result preserves:

- route and source-handoff identity;
- source fingerprint;
- recording identity;
- modeled application identities;
- the canonical `TutorialPackage`, including ordered ready/blocked prompt cards and existing provenance;
- all-false execution, external-write, and production authority.

Blocked prompt cards are not rewritten and have no replacement portable prompt.

## Failure behavior

Unsupported envelope versions, unknown top-level fields, malformed input, or runtime-invalid structured input return a bounded `blocked` result instead of throwing. Semantic route/package blockers remain owned by `buildTutorialPackage(...)` and are returned unchanged.

## Serialization

`serializePromptProjectionResult(...)` emits the structured result as JSON. Standard output, remote execution registration, GitHub artifact transport, provider execution, and ChatGPT routing are deliberately outside #2524 and belong to downstream governed execution work.

## Tutorial 0

Tutorial 0 is regression evidence only. Tests prove the entrypoint produces the same package as the existing in-process projection; no Tutorial 0 fixture becomes runtime authority for other tutorials.

## Authority boundary

The entrypoint performs no network access, browser execution, provider call, GitHub mutation, Notion/Drive/classroom write, publication, or production action.
