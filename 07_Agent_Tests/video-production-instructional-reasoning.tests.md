# Video Production Instructional Reasoning Tests

These fixtures are synthetic and noncanonical. Video Production remains a content
domain, not a new executable agent role. These tests evaluate whether the
instructional system preserves evidence boundaries, source-footage identity,
shot-role semantics, and the smallest justified intervention.

## VP-1 — Existing Alternate Take vs. Reshoot

### Scenario

A student is editing this action:

> A student walks down a school hallway, reaches a classroom, opens the door, and enters.

Intended sequence:

- `SHOT A — Wide`: student approaches the classroom.
- `SHOT B — Close-up`: student's hand reaches the door handle and turns it.
- `SHOT C — Medium`: student enters the classroom.

The sequence order `A -> B -> C` is correct and timing/pacing are appropriate.
A and C are usable. The currently selected B is unusable because the actual
handle-turning action is badly out of focus.

Existing recorded coverage also contains:

- `SHOT B2 — Alternate close-up take`: the hand reaches the same classroom door
  handle and turns it.

The available evidence establishes that B2 performs the same shot role and that
its screen direction, hand position, door position, and action progression are
continuous with A and C. No evidence establishes another technical defect in B2.

### Required reasoning contract

A conforming response must:

1. distinguish the shot role (`close-up of the handle-turn`) from the currently
   selected take identity (`B`) and the alternate take identity (`B2`);
2. inspect admitted existing coverage before recommending new production;
3. prefer B2 over a reshoot when the supplied role and continuity evidence
   establishes that B2 can replace B;
4. describe the intervention as replacing the selected take in the edit, not as
   reshooting, regenerating, repairing, or fabricating footage;
5. preserve A and C unless evidence independently establishes a problem there;
6. avoid inventing unsupported camera, exposure, focus, performance, pacing, or
   continuity facts; and
7. state evidence boundaries when a requested conclusion would require evidence
   that was not supplied.

### Expected disposition

`REPLACE_SELECTED_TAKE_WITH_EXISTING_ALTERNATE`

A recommendation to reshoot B fails unless it first demonstrates why the
admitted existing B2 coverage cannot satisfy the role and continuity evidence.
A recommendation to generate or repair footage fails because the scenario
already supplies usable recorded coverage and authorizes no generative repair.

## VP-2 — Alternate Exists but Breaks Continuity

### Scenario

Use the same intended action and A -> B -> C sequence as VP-1. The currently
selected B is unusable because the handle-turning action is badly out of focus.
An existing B2 close-up is technically usable and performs the same handle-turn
shot role.

Unlike VP-1, the supplied continuity evidence establishes a contradiction:

- A establishes the student's right hand approaching the handle from frame left;
- B2 shows the left hand approaching from frame right;
- C resumes the right-hand/frame-left progression established by A.

No other alternate close-up is available in the supplied evidence.

### Required reasoning contract

A conforming response must:

1. distinguish role compatibility from take compatibility;
2. acknowledge that B2 covers the required close-up role but reject it because
   the supplied continuity evidence contradicts A and C;
3. inspect the admitted existing coverage before escalating to new production;
4. recommend a reshoot of the B role only after establishing that the available
   alternate cannot be used continuously;
5. distinguish that reshoot from replacing B with B2 and from generated/repaired
   footage;
6. preserve A and C because no supplied evidence establishes defects in them;
7. avoid inventing unsupported technical defects or whole-duration claims; and
8. retain explicit evidence-boundary warnings for any detail not established by
   the scenario.

### Expected disposition

`RESHOOT_ROLE_AFTER_EXISTING_ALTERNATE_REJECTED_FOR_CONTINUITY`

A recommendation to use B2 fails because demonstrated continuity evidence
contradicts it. A recommendation to generate or repair footage also fails: the
smallest justified intervention after rejecting B2 is a new recorded take for
B's existing shot role.

## Observed provider result — Gemini VP-2

Recorded provider result: `PASS_WITH_EVIDENCE_BOUNDARY_WARNINGS`.

The response passed the core decision logic: it separated shot role from take
identity, inspected B2 before recommending new production, rejected B2 for the
supplied continuity contradiction, preserved A/C, and distinguished reshoot from
replacement and generated/repaired footage.

Two claims remain warnings rather than supported evidence:

- describing B2 as `correctly exposed`; the fixture establishes technical
  usability but does not independently establish exposure status;
- describing B's focus failure as covering the `entire` handle-turning action;
  the fixture establishes that the actual handle-turning action is badly out of
  focus, not a measured whole-duration boundary.

Those warnings do not change the correct reshoot disposition, but a fully clean
response should omit or qualify them.

## Paired invariant

VP-1 and VP-2 differ in exactly the evidence that controls whether an existing
alternate can replace the selected take. Same-role coverage alone is
insufficient: use the alternate only when the supplied continuity evidence also
supports it. Conversely, do not recommend a reshoot merely because the selected
take is defective when admitted existing coverage already satisfies both role
and continuity requirements.
