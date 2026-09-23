# PPUX Adversarial Acceptance Protocol

Issue: #1627

## Purpose

Stress-test the existing Picture Perfect / PPUX contract without contaminating earlier behavior with instructions that belong to later tests.

Hard invariant:

```text
broad adversarial campaign
-> bounded sequential test cases
-> freeze evidence between dependent stages
-> attribute the first violated contract
-> synthesize only after the sequence is complete
```

A single mega-prompt containing the entire future test suite is not the default protocol because it destroys diagnostic isolation.

This protocol changes no PPUX product semantics. The existing `Model -> Upload -> Review -> Prompts -> Ready` flow remains authoritative. Product behavior owned by #1535, #1542, and #1543 is consumed as evidence and is not redefined here.

## Test status vocabulary

Each test records exactly one status:

- `PASS` — the tested contract is satisfied by concrete evidence.
- `WARN` — the test completed, but bounded evidence identifies a non-blocking uncertainty.
- `FAIL` — concrete evidence proves the tested contract was violated.
- `BLOCKED` — required prerequisite evidence is unavailable or invalid, so the test cannot make a truthful downstream claim.

`BLOCKED` is never converted into a fabricated `PASS`.

## Bounded evidence packet

Every completed test emits a compact packet:

```text
test_id
status
contract_under_test
inputs_used
frozen_baselines_read
observed_evidence
newly_frozen_baselines
blockers
first_violation
staleness_conditions
```

Packets carry evidence, not authority. They do not authorize provider execution, repository implementation, merge, issue closure, external writes, classroom publication, or governed-state mutation.

## Freeze rules

A baseline becomes immutable for dependent tests once a stage explicitly freezes it. Later tests may validate or invalidate that baseline, but may not silently rewrite it.

Canonical freeze points are:

1. source identity after source resolution;
2. instructional sequence after evidence reconstruction;
3. presentation modality after modality resolution;
4. required image count and order after sequence planning;
5. canonical prompt bodies after prompt-artifact generation.

If upstream evidence becomes stale or a rerun intentionally changes a frozen baseline, mark dependent packets stale and rerun only the tests whose evidence depends on the changed baseline. Unrelated successful tests do not need replay.

## Failure attribution

Report the earliest test whose own contract is violated.

Do not attribute a downstream failure when the downstream test is merely consuming an already-invalid prerequisite. Dependent tests become `BLOCKED` until the upstream defect is repaired or fresh evidence is supplied.

Distinguish:

- `product-failure` — PPUX violates the product contract under test;
- `harness-contamination` — the test supplied future-stage instructions or rewrote a frozen baseline;
- `missing-evidence` — the contract cannot be evaluated truthfully from available evidence.

## Sequential stress sequence

Run the following tests in order. Give each test only its own mission plus the bounded packets/frozen baselines it is permitted to consume. Do not preload later adversarial constraints.

### Test 1 — Canonical source resolution

Mission: resolve the authoritative tutorial/source identity only.

Freeze: source identity and provenance.

Do not test prompt wording, provider behavior, fidelity, typography, or cross-frame consistency yet.

### Test 2 — Instructional evidence and sequence reconstruction

Mission: reconstruct the instructional intent and ordered steps from the frozen source.

Freeze: canonical instructional sequence.

If source evidence is insufficient, record `BLOCKED` and block claims that depend on reconstructed intent.

### Test 3 — Presentation modality

Mission: determine the required presentation modality for each instructional step from existing PPUX contracts.

Freeze: modality decisions tied to the instructional sequence.

Do not invent interface content when evidence is missing.

### Test 4 — Image count and order

Mission: determine and freeze the required image/frame count and exact order.

Freeze: ordered frame identities.

Once frozen, Test 5 and later tests may not add, remove, reorder, or merge frames without invalidating this baseline.

### Test 5 — Copy-ready prompt artifacts

Mission: evaluate #1535-owned prompt-artifact behavior against the already-frozen frame sequence.

Freeze: one canonical prompt body per required frame, preserving exact order and copy integrity.

This test does not preload #1542 single-image fidelity or #1543 cross-frame evaluation instructions.

### Test 6 — Provider neutrality

Mission: verify the canonical prompts do not depend on an unauthorized provider-specific execution path or silently alter instructional intent for a provider.

Read-only: frozen prompt bodies.

### Test 7 — Exact UI/interface fidelity

Mission: evaluate interface claims against admitted capture/reference evidence and existing PPUX fidelity contracts.

Read-only: frozen source, frame intent, and prompt bodies.

Missing approved interface evidence must remain visibly blocked rather than reconstructed.

### Test 8 — Typography and source-text boundary

Mission: verify text that must be exact is sourced from authoritative evidence and that generated typography instructions do not invent source text.

Read-only: frozen instructional and prompt evidence.

### Test 9 — Cross-frame consistency

Mission: evaluate #1543-owned consistency across already-frozen frames.

Cross-frame evaluation consumes frame intent; it does not define or retroactively rewrite frame intent.

### Test 10 — Negative constraints

Mission: evaluate #1542-owned negative constraints and prohibited additions against each frozen frame/prompt.

Do not broaden the product contract here.

### Test 11 — Reference/source authority

Mission: verify every authoritative visual/textual claim traces to the correct source class and that presentation guidance is not promoted into instructional authority.

### Test 12 — Ambiguity/adversarial self-check

Mission: introduce bounded ambiguity and verify the system fails visibly or requests review rather than guessing, reconstructing, or changing a frozen baseline.

### Test 13 — Context-loss / standalone prompt test

Mission: evaluate each frozen prompt independently from conversational history.

A standalone prompt must preserve the frozen canonical intent without relying on hidden future-stage context.

### Test 14 — Copy integrity

Mission: verify each discrete prompt artifact is independently copy-ready, complete, ordered, and unchanged from the Test 5 canonical body unless an explicit upstream rerun invalidated it.

### Test 15 — Ready/handoff integrity and synthesis

Mission: evaluate the existing Ready/handoff boundary and synthesize all sequential evidence.

The final report must preserve every prior `PASS`, `WARN`, `FAIL`, and `BLOCKED` result, identify the first failing stage, list stale/dependent stages, and distinguish product failure from harness contamination or missing evidence.

Ready/handoff evidence never implies implementation, provider, external-write, merge, or issue-closure authority.

## Required regression scenarios

The protocol is conformant only if it proves all of these behaviors:

1. A mega-prompt containing all future constraints is rejected as the default stress-test shape.
2. Test 1 receives source-resolution instructions only and emits a bounded packet.
3. Test 4 freezes image count/order; Test 5 cannot silently change it.
4. A Test 2 failure blocks dependent downstream claims rather than being masked by later instructions.
5. #1535 prompt-artifact behavior is evaluated independently from later #1542/#1543 instructions.
6. Cross-frame evaluation consumes frozen frame intent rather than defining it retroactively.
7. Provider/fidelity tests cannot rewrite canonical instructional intent.
8. Final synthesis identifies the earliest failing stage and preserves all prior evidence.
9. A failed stage can be rerun without replaying unrelated successful stages unless their evidence is stale.
10. No test creates provider execution, Drive/Notion mutation, classroom publication, merge, closure, workflow/protected-setting, credential, or production authority.

## Runner checklist

For each test:

1. Load only the current test mission.
2. Load only permitted frozen baselines/evidence packets.
3. Execute or inspect the current contract.
4. Record concrete evidence.
5. Assign `PASS`, `WARN`, `FAIL`, or `BLOCKED`.
6. Freeze only the baseline owned by this stage.
7. If failed, mark dependent downstream tests blocked until repaired.
8. Do not continue by inventing missing prerequisite evidence.

## Final stress report

The consolidated report contains:

```text
sequence_run
per_test_status
first_failing_test
first_violated_contract
frozen_baselines
stale_or_blocked_dependents
product_failures
harness_contamination
missing_evidence
ownership_preservation (#1535/#1542/#1543)
ready_handoff_integrity
excluded_surfaces_confirmation
```

The synthesis is a report over sequential evidence. It is not a new PPUX product contract or an authorization record.
