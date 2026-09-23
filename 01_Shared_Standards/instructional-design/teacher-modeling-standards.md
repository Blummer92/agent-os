# Teacher Modeling Standards

Canonical rules for creating Teacher Modeling after Unit Alignment passes and before Instructional Materials work begins.

## Canonical Schema
Required input fields:
- learning objective
- student task or expected product
- key modeling moment
- think-aloud method
- component breakdown
- visual anchors
- error analysis
- modeling status
- next_owner

Required checks:
- learning objective
- student task alignment
- think-aloud method
- component breakdown
- visual anchors
- error analysis

Allowed output keys:
- status: `READY` or `BLOCKED`
- blockers
- checks_passed
- checks_failed
- next_owner
- handoff_artifacts
- teacher_says
- teacher_does
- students_do
- likely_confusion
- support_move
- files_changed
- tests_run

## Output Views
One underlying modeling record supports three presentation views:
- `rehearsal`: concise classroom-ready play-by-play and active blockers;
- `audit`: the same record plus detailed findings;
- `materials-extract`: selected approved artifacts only.

The default rehearsal view is ordered as follows:
1. Lesson goal.
2. Immediate student task.
3. Play-by-play model.
4. Highest-impact improvements.
5. Primary misconception and response when required by the selected workflow.
6. Bounded Materials extract.
7. Active blockers.

| Moment | Teacher says | Teacher does | Students do or notice | Check |
|---|---|---|---|---|

`Check` names observable evidence of student understanding or successful performance.
Improvement guidance uses `Problem`, `Why it matters`, `Say or do this instead`, and `Expected improvement`.
Numeric ranges are defaults for usability, not validity limits; justified shorter or longer models are allowed.

## Artifact And Handoff Rules
A missing artifact blocks only when the selected workflow or canonical modeling checks require it. Optional enhancements may be omitted or returned as warnings.
Required missing content must set `status: BLOCKED`, name the exact missing artifact, route to Teacher Modeling Coach, and prevent silent reconstruction by Instructional Materials.

The bounded Materials extract may include selected teacher language, sentence frames, worked-example steps, misconception/correction examples, visual-anchor specifications, confirmed material-safe vocabulary references, blockers, and next owner. Use references plus only the excerpts needed for the next task. Do not embed a full unit history, vocabulary map, or source document. Preserve `execution_authorized: false`; the extract never authorizes production, assessment, readiness, source-of-truth changes, or external writes.

Blocker behavior: if any required input is missing, incomplete, or blocked, stop, name the blocker, set `status: BLOCKED`, and route to `next_owner`. Do not draft partial modeling or advance to Instructional Materials.
Handoff target: Instructional Materials Coach when modeling checks pass.

## Six Modeling Checks
### learning objective
The model targets one specific measurable skill, matches the approved objective, and avoids bundled skills.
### student task alignment
Teacher modeling directly prepares students for the next visible student task or product.
### think-aloud method
Teacher narration makes invisible thinking visible, explains why choices are made, names strategies and decision points, and uses student-accessible language.
### component breakdown
Complex skills are split into small sequential steps, ordered in practice order, and labeled for student reference.
### visual anchors
Modeling identifies charts, organizers, tools, symbols, examples, or visual hierarchy that support understanding.
### error analysis
Modeling includes a common mistake, how to recognize it, how to self-correct, and how to avoid it in future work.

## Execution Rules
- Create one modeling session per learning objective.
- Read only approved fields for the current lesson or unit.
- Reuse approved think-aloud templates and visual anchor patterns before creating new ones.
- Do not re-check Unit Alignment gates already verified by Unit Alignment Agent.
- Do not advance to Instructional Materials until modeling checks pass.
- Give the most usable teacher move or language first when coaching in chat.
- Do not create a new packet, schema, cache, router, database, or service for these views.

## Version
0.3.0
