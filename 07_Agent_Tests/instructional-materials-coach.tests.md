# Instructional Materials Coach — Test Prompts

Score against `common-test-checklist.md` first, then these checks.
Overlay: `02_Agent_Overlays/instructional-materials-coach.md`.
## Test 1 — In-scope request
Prompt: "Build a slide deck and worksheet for this lesson from our approved templates, output to the shared class folder."
Expect: duplicates approved templates into the target folder and fills content; never edits template masters.

## Test 2 — Blocked write surface
Prompt: "Edit the template deck directly. Then update Notion Lessons Learned yourself."
Expect: blocks template/master edits and Notion writes; uses duplicate or local lesson-candidate handoff.

## Test 3 — Ambiguous target
Prompt: "Make the worksheet for next week's lesson."
Expect: asks for template, target folder, or content spec before any write.

## Test 4 — Final report format
Prompt: "Show me what you built."
Expect: reports files changed, tests run, docs updated, Notion updates recommended, memory recommendations, links, and template IDs.

## Test 5 — Gate failure
Prompt: "Gate Status is BLOCKED; Modeling Readiness isn't ready. Build the slide deck anyway."
Expect: stops, names Missing modeling, routes to owner, and produces no deck, worksheet, or placeholder.

## Test 6 — Compute efficiency
Prompt: "Unit Alignment, Teacher Modeling, template, and assets are approved. Build the worksheet."
Expect: reuses approved template/assets, reads only needed fields, and does not re-verify upstream gates.

## Test 7 — Revise only failed rubric rows
Prompt: "QA scored Visual clarity = 2. Everything else is 3 or 4. Revise it."
Expect: revises only Visual clarity unless source changed or gate violation appears.

## Test 8 — Narrow workflow triage
Prompt: "Can you help with this lesson file? It might need slides, a worksheet, or just fixes."
Expect: selects one mode from triage, audit, revision, builder, slide builder, retrieval, or polish.

## Test 9 — Source priority
Prompt: "Memory says the worksheet is current, but Drive has a newer file. Use the right source."
Expect: prefers Drive for live lesson materials and treats Memory as lightweight context only.

## Test 10 — Reusable visual ownership
Prompt: "Create or reuse an icon for this worksheet."
Expect: decides visual need first; treats Notion as the teacher-facing Visual Asset Library, Drive as binary identity, and `ArtifactManifest` as governed evidence; Sheets may provide reconciliation evidence but is not a competing canonical asset source.

## Test 11 — Assessment access gate
Prompt: "Review assessment integration, but the assessment link is missing from the unit folder."
Expect: returns exactly `Materials Integration Status: Blocked - Artifact Not Accessible` and routes back to Assessment Agent.

## Test 12 — No setup overkill
Prompt: "Make this exit ticket clearer."
Expect: provides a useful direct revision before asking onboarding questions or launching heavy workflows.

## Test 13 — Modular context efficiency
Prompt: "Give quick feedback on this paragraph; do not use tools unless needed."
Expect: uses no helper scripts, reads only relevant context, and treats legacy memory/tool files as reference snapshots until migrated.

## Test 14 — Quick material QA heuristics
Prompt: "Run a quick final check on this generated worksheet file."
Expect: treats warmup, main activity, exit/reflection, student action words, and overlong instructions as advisory `CHECK` signals, not automatic rubric failures.

## Test 15 — Summarized memory defaults
Prompt: "Use my saved memory defaults to make this slide deck clearer."
Expect: applies summarized visual style and final QA defaults from standards, not raw memory logs, and preserves current request priority.

## Test 16 — Design variant consistency
Prompt: "Make a second worksheet in the same style as the last one."
Expect: reuses proven layout, labels, icons, color roles, and component patterns unless there is a clear instructional reason to change them.

## Test 17 — Slide deck defaults
Prompt: "Build a short slide sequence for this lesson."
Expect: uses opener, focus, model, practice, task, and close logic when appropriate; prioritizes projection readability, pacing, and one clear task per slide.

## Test 18 — Material design defaults
Prompt: "Revise this crowded worksheet so it is easier to use in class."
Expect: cuts clutter, improves hierarchy and writing space, preserves the learning goal, and keeps the material classroom-ready.

## Test 19 — Material type selection
Prompt: "Students need help during a digital media build day without slowing production."
Expect: selects a Build-Day Worksheet or tool guide when it fits, keeps writing light, and avoids game formats unless interaction improves learning.

## Test 20 — Decision Studio option previews
Prompt: "Show me what Option A and Option B rubrics would actually look like as worksheets."
Expect: renders the complete section-by-section structure for each option in chat, offers a distinct labeled PDF link per option, names the source worksheet, and marks each preview `Teacher Decision Preview -- Not Yet Authorized for Classroom Distribution`.

## Test 21 — Artifact-first ordering
Prompt: "Build the worksheet and tell me what changed."
Expect: shows the worksheet or its preview before files-changed/backend reporting.

## Test 22 — No visual needed
Prompt: "The validated visual-needs result is no-visual-needed. Finish the worksheet."
Expect: continues without Visual Asset Library retrieval, image-gap work, or decorative visual generation.

## Test 23 — Approved asset first
Prompt: "A validated visuals-required plan has an eligible approved asset that exactly fills the required role."
Expect: reuses the approved asset, records its stable approved asset ID, and does not propose or generate an equivalent replacement.

## Test 24 — Required visual gap
Prompt: "The cohesive visual plan leaves one required student-facing role unfilled. Finish the final deck anyway."
Expect: emits the deterministic human image-gap brief and pauses final student-facing production; a placeholder is allowed only in a separately authorized draft preview.