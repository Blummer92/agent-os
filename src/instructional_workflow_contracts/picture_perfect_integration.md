# Picture Perfect RJ Integration

Canonical responsibility chain:

`RJ1 = understand -> RJ2 = clean -> RJ3 = conform -> RJ4 = replay-verify -> Teacher Modeling Coach = teach -> Picture Perfect = show`

This integration is intentionally offline and deterministic. It does not prove live Adobe replay, selector stability, screenshot fidelity, authentication persistence, or production readiness.

## Inputs and ownership

RJ evidence contributes what happened, source indexes, target/evidence references, fragility/recovery evidence, and RJ2 rewrite disposition. RJ3/RJ4 may be `pending`, `passed`, `failed`, or `indeterminate`.

Teacher Modeling owns instructional disposition and sequence. A semantic/rewrite result never automatically decides `keep`, `combine`, `not-instructional`, or `needs-review`.

Picture Perfect consumes modeled instructional steps and may add only visual-state requirements: `action`, `result`, or `action+result`, must-show/must-not-show constraints, orientation, and annotation-space guidance.

Canonical provider-neutral visual intent remains `curriculum-image-intent-v1`; this integration does not define a second Picture Perfect image schema.

## Software-interface fidelity boundary

This module models software-tutorial frames, so its public `build_image_intent(...)` path now fails closed. A Picture Perfect software-tutorial visual cannot be converted into a generative `ImageIntent`, and therefore cannot reach `assemble_gemini_manual_prompt(...)` as paste-ready reconstructed UI.

This is the smallest boundary because the module already owns the software-tutorial integration. It does not add a capture flag, screenshot reference, UI-name heuristic, or second compatibility contract. Actual interface assets remain governed by `curriculum-visual-asset-compatibility-v2`, whose canonical cohesion rule hard-rejects `representation_class = interface-capture` unless `medium = screen-capture`. This module does not duplicate that rule or consume capture evidence; capture binding belongs to the separate fidelity lane.

Rejected alternatives:

- `build_visual_requirement(...)` remains usable because deterministic visual planning and provenance are still needed before capture binding.
- A new `requires_screen_fidelity` caller field was rejected because callers could misclassify the frame and it would duplicate the derived boundary established by Picture Perfect.
- Adding capture references here was rejected because this issue does not own capture consumption or a second reference contract.
- Sanitizing the former generated prompt into a generic software-like image was rejected because the documented Python path is specifically a software-tutorial integration and could still be mistaken for screen evidence.

The former hardcoded `creative-software workspace`, `software-tutorial frame`, realistic-interface look, and Adobe Express handoff text are removed with the generative path rather than softened.

## Application identity decision

`modeled_application` is not added to the Python contract. In this integration, application identity is relevant to real interface fidelity, and real interface fidelity requires captured screen evidence. Adding an application name to a generative path would make an unsupported reconstruction more convincing without adding evidence. Legitimate non-interface imagery continues to use the independent `curriculum-image-intent-v1` contract directly and does not require application identity metadata.

## Provenance and route-back

Every retained visual can trace to a Modeling step, one or more semantic action identities, original Recorder source indexes, and the recording identity/digest.

Missing or conflicting provenance fails closed. Unsupported Recorder evidence remains visible as unresolved evidence. An unproven/rejected rewrite cannot silently replace source evidence.

RJ2 `remove-noise` and Teacher Modeling `not-instructional` are distinct decisions. RJ3/RJ4 success cannot authorize an instructional sequence.

## Tutorial 0 fixture

The synthetic golden path covers:

`open Your Stuff -> create Digital Media -> name Digital Media -> enter Digital Media -> create Tutorial 0 - Organize My Files -> name Tutorial 0 - Organize My Files`

The fixture includes viewport/navigation, click/double-click, change, Enter key events, stable `data-testid` evidence, synthetic fragile identity evidence, and keyboard noise without real Adobe account identifiers, student data, credentials, or private URLs.

## Authority boundary

All outputs preserve `execution_authorized: false` or the equivalent canonical authority evidence. Generated non-interface ImageIntents remain derived presentation artifacts, never source instructional evidence.

No browser execution, Notion/Drive mutation, image-provider call, classroom publication, production action, or credential use belongs in this module.
