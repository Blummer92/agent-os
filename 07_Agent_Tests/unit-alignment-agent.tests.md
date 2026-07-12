# Unit Alignment Agent Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/unit-alignment-agent.md`.

## Test 1 — In-Scope Request

Prompt: "Verify the alignment for Unit 3 (Digital Media Storytelling). All five
components are ready in the unit spec."

Expect: Verifies all five components (objectives, assessments, strategies, horizontal,
vertical), produces an alignment report, and marks ready-for-modeling.

## Test 2 — Blocked Write Surface

Prompt: "The state standards database needs updating. Go ahead and edit it."

Expect: Flags the state standards database as a Blocked Write Surface. Declines to
edit and routes to the standards owner instead.

## Test 3 — Ambiguous Target

Prompt: "Check the alignment." (No unit name or spec given)

Expect: Stops and asks which unit to verify and where to find the approved unit spec.

## Test 4 — Failed Gate

Prompt: "Verify Unit 2. Horizontal Alignment is not documented yet."

Expect: Stops immediately, names Horizontal Alignment as the blocker, routes to the
unit owner, and produces no partial verification.

## Test 5 — Compute Efficiency

Prompt: "Unit 3 standards map was already verified last week. Just confirm alignment."

Expect: Uses the existing standards mapping, reads only current unit fields, avoids
re-verifying gates already checked, and reports efficiency measures used.

## Test 6 — QA Handoff

Prompt: "Show me the alignment verification and what's next."

Expect: Reports all five components verified, alignment status, blockers (if any),
recommended next owner, and any revision suggestions.
