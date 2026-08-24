# #1375 Governed Pre-PR Runtime Handoff

Status: `needs-capable-runtime`

Issue: #1375 — PPUX-VRL2 — Wire current visual-reference retrieval into Tutorial 0 prompt generation

Authorized branch: `agent/1375-ppux-vrl2-tutorial0`

Base / current branch head before this handoff commit: `ccdde85b4094d173f599a2ed7145b7b4f153a38f`

Resume this exact branch. Do not create another branch or Draft PR before the declared developer loop passes.

## Resume objective

Wire the merged `visualReference` contract into the real Tutorial 0 prompt-generation path before `buildPortablePrompt()` determines a Ready card. Current approved application-state evidence must participate as additional authority for current UI appearance/state while historical Recorder/F1/F2 capture evidence remains preserved and independently authoritative.

The implementation must prevent stale Tutorial 0 UI such as `Create new` from becoming Ready when current approved Adobe Express evidence establishes `Create` -> `Create file`.

## Inspected implementation seams

### `src/promptIntent.ts`

The current `VisualSpecification` and `projectReviewedStepToVisualSpecification()` bind F1/F2 capture evidence through `bindCaptureEvidence()` and `buildPortablePrompt()` uses approved captured screen evidence as the visual base for screen-fidelity frames.

#1375 should extend this existing projection rather than create a second prompt pipeline. The minimum new binding must carry current-reference identity, application variant, context/state, stable reference identity, visible UI claims, blocker/status reasons, and provenance.

### `src/visualReference.ts`

The merged #1372 contract already provides:

- exact application + optional variant + context/state selection;
- one-reference-only claim support with no cross-reference unioning;
- deterministic newest-current selection;
- stale/privacy/ineligible/missing/co-visibility blocker vocabulary;
- explicit `visual-reference-current-recorded-ui-conflict` manual-review behavior;
- stable asset/reference identity and provenance;
- `buildVisualReferenceDirective()` with the non-reconstruction / no-cross-state-mixing boundary.

Reuse this contract directly. Do not add another visual registry, Adobe-only core abstraction, or duplicate current-reference policy.

### `src/fixtures/tutorial0-prompts.ts`

The canonical Tutorial 0 fixture currently projects only through `tutorial0SyntheticCapture` and still contains historical authoring such as:

```text
Create new
```

The current-reference integration must make that historical/current mismatch explicit rather than silently rewriting the fixture or Recorder evidence.

### `src/fixtures/tutorial0-capture.ts`

The F2 synthetic capture intentionally preserves historical Tutorial 0 observations, including `Create new`. Do not rewrite this evidence to match current UI. It is historical evidence and must remain independently testable.

## Bounded implementation target

Prefer the smallest changes around:

```text
src/promptIntent.ts
src/visualReference.ts
src/fixtures/tutorial0-prompts.ts
focused tests/docs
```

A small privacy-safe Tutorial 0 current-reference fixture may be added when needed to exercise the merged selector contract. Use metadata/synthetic fixtures only; do not commit raw private screenshots.

The intended projection is approximately:

```text
reviewed instructional step
-> resolve required application context/state
-> selectVisualReference(...)
-> reconcile current reference claims with historical Recorder/UI evidence
-> bind selected approved current reference into VisualSpecification
-> retain F1/F2 capture evidence as separate historical/action authority
-> buildPortablePrompt()
-> Ready only when current-reference and historical evidence are compatible
```

## Tutorial 0 required state mapping

At minimum preserve these issue-defined mappings and constraints:

1. `tutorial0-step-01-organize-location` -> `navigation/your-stuff/files`
   - select the approved Your Stuff / Files current reference;
   - preserve the exact state;
   - do not mix Create/editor/Text/Media/Elements controls;
   - do not fall back to synthetic appearance when an approved current reference is available.

2. Create flow -> `navigation/create-menu`
   - historical evidence remains `Create new`;
   - current approved evidence establishes `Create` + `Create file`;
   - unreconciled mismatch must be manual-review/blocked, never Ready;
   - an explicitly reconciled current-state fixture may emit current `Create` / `Create file` instructions without rewriting historical Recorder evidence.

3. `tutorial0-step-05-landscape-file` -> `creation/get-started`
   - selected reference must support both `Landscape` and `16:9` on the same reference;
   - Square/Portrait context is allowed only when the selected same-state reference establishes it;
   - editor-state controls must not be mixed into the frame.

4. `tutorial0-step-07-verify-location`
   - exact favorite-food filenames/final arrangement remain blocked unless approved evidence establishes them;
   - current-reference support must not weaken this fail-closed behavior.

## Prompt authority boundary

For screen-fidelity frames, when a compatible approved current reference exists, prompt generation must include the selected current reference as the current visual base while preserving the existing capture/Recorder evidence contract.

The current-reference directive must preserve the #1372 boundary:

```text
Use only the selected approved current application-state reference.
Do not redraw, reconstruct, invent, or merge controls, labels, geometry, or states from another reference.
```

Do not allow provider adapters to remove this directive or the selected reference identity.

## State-locality / co-visibility invariants

Preserve all existing behavior:

- no cross-reference claim unioning;
- no cross-state control mixing;
- no generic application screenshot when a state-specific reference is required;
- before/after capture roles stay distinct;
- current-reference selection does not widen Recorder evidence;
- combined reviewed steps do not widen visual authority;
- stale/privacy-unresolved references cannot become Ready;
- missing required current reference fails closed;
- blocked cards expose no copyable prompt.

## Required acceptance coverage

At minimum prove:

1. Tutorial 0 Your Stuff selects `navigation/your-stuff/files`.
2. Historical `Create new` vs current `Create file` cannot become Ready.
3. Reconciled Create flow emits current reference-backed `Create` / `Create file` instructions.
4. Landscape selects `creation/get-started` and requires `Landscape` + `16:9` co-visibility.
5. No prompt can combine UI claims from two current visual references.
6. Missing required current reference fails closed.
7. Stale/privacy-unresolved reference cannot become Ready.
8. Final filename/arrangement uncertainty remains blocked.
9. Existing F1/F2 capture regressions remain green.
10. Provider adapters cannot remove current-reference non-reconstruction text or selected reference identity.

## Required pre-PR developer loop

From `08_Tooling/instructional-materials-coach/picture-perfect-coach`:

```bash
npm ci
npm run typecheck
npm run lint
npm test
npm run build
npm run guard
npm run test:e2e
```

Then from repository root:

```bash
bash 07_Agent_Tests/validate-repo-structure.sh
./scripts/validate-all.sh
```

If the known Cloud Shell `/usr/local/bin/agent-os-capabilities` environment-only failure recurs, document it separately. Do not change unrelated reusable-capability-registry code to make #1375 green.

Draft PR creation remains blocked until every issue-required developer-loop command above has actually executed on a capable runtime. Do not use the Draft PR as the first runtime.

## Current execution-surface evidence

The ChatGPT GitHub connector can read and write repository files/branches but does not provide the package/runtime execution surface needed to run the mandatory PPUX npm developer loop. The prior shell route could not resolve GitHub and therefore could not provide a valid checkout/runtime.

Resume this branch on a qualified code/runtime executor with GitHub checkout plus Node/npm dependencies. Reacquire current `main`, this branch head, #1375 scope, and any active Scheduler lease before changing code. If a conflicting active or ambiguous lease exists, fail closed rather than creating competing execution lineage.

## Authorization / exclusions

Authorized by the current ordinary Safe Implementation Lane instruction:

- this one existing non-protected branch;
- bounded #1375 implementation;
- directly corresponding offline tests/docs;
- one Draft PR only after the required developer loop passes;
- exact-head validation and Ready-for-Review only when all required checks pass and blockers are resolved.

Not authorized:

- merge or auto-merge;
- issue closure;
- protected branch/settings/ruleset/required-check changes;
- workflow changes;
- credentials, secrets, IAM, or permission changes;
- production deployment;
- live Adobe/provider execution;
- Notion/Drive/classroom writes;
- raw private screenshot commits;
- provider/image-generation execution;
- any other external write or materially expanded architecture.

## Required final report

Return:

- actual branch;
- exact final head;
- files changed and why each support file was necessary;
- tests/checks run with exact-head evidence;
- docs updated;
- exact Tutorial 0 current-reference integration path;
- Create drift reconciliation behavior;
- state-locality/co-visibility behavior;
- F1/F2 regression status;
- Draft PR state;
- unresolved blockers;
- handoff recommendations;
- rollback;
- remaining risks;
- authorization and excluded-surface confirmation.
