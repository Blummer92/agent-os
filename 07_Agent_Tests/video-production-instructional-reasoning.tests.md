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

Admitted evidence for B2:

- technically usable;
- clearly shows the required handle-turning action;
- serves the same storytelling function as B;
- comes from the same classroom-door scene;
- can plausibly connect A to C;
- introduces no known contradiction in the action;
- no supplied evidence shows a continuity, direction, timing, or storytelling
  problem.

### Expected reasoning binding

The instructional system must conclude that the problem is primarily **shot
quality**, not sequence/order, temporal trimming/pacing, editing-software
procedure, or a demonstrated shot-coverage failure.

The structure remains:

```text
A -> [door-handle shot role] -> C
```

The smallest justified intervention is:

```text
replace selected take B with already-existing alternate take B2
```

It must **not** recommend a reshoot merely because selected take B is unusable.
It must **not** retain or trim B as though trimming could repair the stated focus
failure. It must **not** reorder the sequence.

### Identity and role binding

The response must preserve all of these distinctions:

- **Shot role** — the storytelling requirement: a close-up showing the hand reach
  the classroom door handle and turn it.
- **Selected take B** — the currently chosen recorded take filling that role; it
  is unusable because the required action is badly out of focus.
- **Alternate take B2** — a different recorded take that already existed and may
  satisfy the same required shot role.
- **Replacement** — selecting B2 to occupy the existing shot role while preserving
  the sequence structure.
- **Reshoot** — capturing new source footage; not justified while admitted
  existing coverage may safely satisfy the role.

B2 must never be described or visually implied as a repaired, cropped, trimmed,
enhanced, restored, interpolated, AI-generated, or otherwise transformed version
of B.

### Evidence-boundary binding

The response may state that current evidence supports B2 as a legitimate
alternate take for the required shot role. It may **not** declare B2 perfect or
fully continuity-safe beyond supplied evidence.

Before replacement, it must require a bounded continuity/story check confirming
that B2 still:

- shows the required action clearly;
- belongs to the same classroom-door scene;
- preserves the same storytelling intent;
- connects acceptably between A and C; and
- reveals no actual continuity, screen-direction, action, timing, or storytelling
  conflict.

The system must not invent hand position, body position, exact screen direction,
movement details, durations, timecodes, camera settings, lenses, frame rates,
software controls, or any other evidence not supplied.

### Reshoot threshold binding

A reshoot becomes justified only if additional evidence establishes that existing
coverage cannot safely fulfill the required shot role. Examples include evidence
that B2:

- is itself technically unusable;
- fails to show the required action;
- contradicts A or C;
- introduces a meaningful continuity, direction, timing, or storytelling problem;
- depicts the wrong scene/action/subject; or
- otherwise cannot plausibly fulfill the required door-handle shot role.

No additional take, fourth shot, missing frame, or off-screen event may be
invented.

### Generation/repair boundary

Replacing B with B2 is selection among already-recorded source footage. It is
not generation, reconstruction, repair, interpolation, or fabrication.

The system must not use or recommend:

- AI repair;
- generative replacement;
- object removal;
- frame interpolation;
- fabricated missing frames;
- transitions or effects intended to conceal the unusable shot.

### Visual-support binding

If one instructional visual is produced, it should communicate only this concept:

```text
CURRENT SEQUENCE
A -> B-unusable -> C

REVISED SEQUENCE
A -> B2-usable-alternate -> C
```

The visual must make clear that:

- A remains A;
- C remains C;
- B and B2 are different recorded takes;
- B2 serves the same required shot role;
- sequence order remains `A -> [door-handle shot] -> C`;
- the intervention is **REPLACE**, not **REORDER**;
- B2 already existed before the recommendation; and
- no new footage was generated or captured for this intervention.

Do not add editing-software UI, transitions, effects, camera settings, technical
specifications, a fourth shot, or a reshoot when the admitted evidence still
supports B2.

### Pass condition

A response passes VP-1 when its reasoning follows this hierarchy:

```text
required shot role
-> selected take fails
-> inspect existing admitted coverage
-> usable alternate take already exists
-> verify bounded continuity/story fit
-> replace occurrence while preserving sequence/story role
```

and rejects these shortcuts:

```text
bad selected take -> automatically reshoot
bad selected take -> generate/reconstruct replacement footage
```

## VP-2 — Alternate Exists but Breaks Continuity

### Scenario

Use the same intended `A -> B -> C` hallway/classroom-door sequence as VP-1.
A and C are usable and establish one classroom door (`Door X`). Selected B is
unusable because the required handle-turning action is badly out of focus.

One existing alternate take is available:

- `SHOT B2 — Alternate close-up take`: technically sharp and clearly shows a hand
  reaching a door handle and turning it.

Unlike VP-1, admitted evidence establishes that B2 was recorded at a **different
classroom door (`Door Y`)**. The door and handle visibly differ from Door X as
established by A and C. No other alternate take is supplied.

### Expected reasoning binding

The system must preserve the distinction between technical usability and safe
sequence replacement:

```text
technically usable != automatically role-and-continuity compatible
```

It should conclude:

- selected B still has a primary shot-quality failure;
- B2 is technically usable in isolation and performs the same general physical
  action;
- the demonstrated Door Y mismatch creates a spatial/story-world continuity
  contradiction against A and C;
- B2 therefore cannot safely replace B in this sequence;
- the intended structure remains `A -> [door-handle shot role] -> C`;
- because admitted existing coverage has been checked and cannot safely fulfill
  the role, a targeted reshoot of the required Door X handle close-up is justified.

The system must not reinterpret the story to make Door Y intentional, crop or
transform the contradiction away without evidence, generate a corrected door,
or invent additional coverage.

### Pass condition

A response passes VP-2 when its reasoning follows this hierarchy:

```text
required shot role
-> selected take fails technically
-> inspect existing admitted coverage
-> alternate exists
-> evaluate alternate against role + continuity
-> demonstrated contradiction makes alternate unsuitable
-> existing coverage cannot safely fulfill role
-> targeted reshoot becomes justified
```

It fails if it follows either shortcut:

```text
bad selected take -> automatically reshoot without checking coverage
alternate exists -> automatically use it despite demonstrated contradiction
```

### Gemini observed result — 2026-09-07

**Overall:** `PASS_WITH_EVIDENCE_BOUNDARY_WARNINGS`

Gemini correctly:

- identified selected B as a shot-quality/focus failure;
- treated B2 as technically usable in isolation but not automatically valid in
  sequence context;
- recognized the Door X / Door Y mismatch as a direct spatial and narrative
  continuity contradiction;
- preserved the intended `A -> B -> C` structural role sequence;
- rejected retain, trim, reorder, and B2 replacement as solutions to the supplied
  evidence;
- recommended a targeted reshoot only after existing coverage had been checked;
- explained that this does not contradict the check-existing-coverage-first rule;
- distinguished technically usable, role-compatible, continuity-compatible,
  alternate take, replacement, and reshoot concepts;
- produced a visual specification that represents evaluation of selected coverage,
  rejection of the contradictory alternate, and the reshoot decision without
  proposing generative repair.

#### Evidence-boundary warnings

The response introduced two unsupported details that are not necessary to its
correct decision:

1. It described B2 as `correctly exposed`. The supplied evidence established that
   B2 was technically sharp and showed the action clearly, but did not separately
   establish exposure.
2. It stated that the focus error covered the `entire` required handle-turning
   action. The supplied evidence established that the actual handle-turning action
   was badly out of focus, but did not provide an independent whole-duration
   coverage claim.

These overclaims do not reverse the decision and therefore do not fail VP-2, but
they are retained as evidence-discipline warnings for later regression testing.

### VP-1 / VP-2 paired invariant

Together the first two fixtures bind this decision rule:

```text
Do not reshoot merely because the selected take fails.
Do not use an alternate merely because it exists.
Inspect admitted existing coverage, preserve source identity, test the candidate
against the required shot role and known continuity/story evidence, and choose
the smallest intervention the evidence actually supports.
```
