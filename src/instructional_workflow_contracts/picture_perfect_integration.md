# Picture Perfect RJ Integration

Canonical responsibility chain:

`RJ1 = understand -> RJ2 = clean -> RJ3 = conform -> RJ4 = replay-verify -> Teacher Modeling Coach = teach -> Picture Perfect = show`

This integration is intentionally offline and deterministic. It does not prove live Adobe replay, selector stability, screenshot fidelity, authentication persistence, or production readiness.

## Inputs and ownership

RJ evidence contributes what happened, source indexes, target/evidence references, fragility/recovery evidence, and RJ2 rewrite disposition. RJ3/RJ4 may be `pending`, `passed`, `failed`, or `indeterminate`.

Teacher Modeling owns instructional disposition and sequence. A semantic/rewrite result never automatically decides `keep`, `combine`, `not-instructional`, or `needs-review`.

Picture Perfect consumes modeled instructional steps and may add only visual-state requirements: `action`, `result`, or `action+result`, must-show/must-not-show constraints, orientation, and annotation-space guidance.

Canonical provider-neutral visual intent remains `curriculum-image-intent-v1`; this integration does not define a second Picture Perfect image schema.

## Provenance and route-back

Every retained visual can trace to a Modeling step, one or more semantic action identities, original Recorder source indexes, and the recording identity/digest.

Missing or conflicting provenance fails closed. Unsupported Recorder evidence remains visible as unresolved evidence. An unproven/rejected rewrite cannot silently replace source evidence.

RJ2 `remove-noise` and Teacher Modeling `not-instructional` are distinct decisions. RJ3/RJ4 success cannot authorize an instructional sequence.

## Tutorial 0 fixture

The synthetic golden path covers:

`open Your Stuff -> create Digital Media -> name Digital Media -> enter Digital Media -> create Tutorial 0 - Organize My Files -> name Tutorial 0 - Organize My Files`

The fixture includes viewport/navigation, click/double-click, change, Enter key events, stable `data-testid` evidence, synthetic fragile identity evidence, and keyboard noise without real Adobe account identifiers, student data, credentials, or private URLs.

## Authority boundary

All outputs preserve `execution_authorized: false` or the equivalent canonical authority evidence. Generated prompts/images are derived presentation artifacts, never source instructional evidence.

No browser execution, Notion/Drive mutation, image-provider call, classroom publication, production action, or credential use belongs in this module.
