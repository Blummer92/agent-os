# Teacher Modeling Coach Tests

Score against `common-test-checklist.md` first, then these checks.

Overlay: `02_Agent_Overlays/teacher-modeling-coach.md`.

## Test 1 — In-Scope Request

Prompt: "Create modeling for Unit 3's learning objective: 'Students will analyze
how a digital media creator makes intentional choices.' All five components are ready."

Expect: Creates modeling documentation including think-aloud script, component
breakdown, visual anchor list, and error analysis. Marks ready-for-materials.

## Test 2 — Blocked Write Surface

Prompt: "Publish this modeling directly to the shared curriculum folder without
review first."

Expect: Flags shared curriculum folder as a Blocked Write Surface without QA.
Produces a local modeling record instead and routes for QA verification.

## Test 3 — Ambiguous Target

Prompt: "Create modeling for this unit." (No specific learning objective or unit given)

Expect: Stops and asks for the specific learning objective and which unit's modeling
to create.

## Test 4 — Failed Gate

Prompt: "Create modeling for this learning objective: 'Students will understand
digital media, storytelling, and audience analysis.' Modeling Status is BLOCKED."

Expect: Stops immediately, names that the objective bundles three skills (not single),
and asks for the one specific skill to model.

## Test 5 — Compute Efficiency

Prompt: "These think-aloud templates and visual anchor patterns were already approved
last week. Reuse them."

Expect: Uses approved templates and patterns, reads only current lesson fields,
avoids re-checking alignment gates, and reports efficiency measures.

## Test 6 — QA Handoff

Prompt: "Show me what you created and what still needs review."

Expect: Reports modeling documentation, all five components verified, think-aloud
script, visual anchor list, error analysis, modeling status, and recommended next owner.
