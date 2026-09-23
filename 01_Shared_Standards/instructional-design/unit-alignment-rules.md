# Unit Alignment Rules

Canonical rules for verifying Unit Alignment before Teacher Modeling and
Instructional Materials work begins.

## Canonical Schema

Required input fields:
- standards
- learning objectives
- assessments
- instructional strategies
- horizontal alignment
- vertical alignment
- alignment status
- next_owner

Required checks:
- standards
- learning objectives
- assessments
- instructional strategies
- horizontal alignment
- vertical alignment

Allowed output keys:
- status: `PASS` or `BLOCKED`
- blockers
- checks_passed
- checks_failed
- next_owner
- handoff_artifacts
- files_changed
- tests_run

Blocker behavior: if any required input is missing, incomplete, or misaligned,
stop immediately, name the blocker, set `status: BLOCKED`, and route to
`next_owner`. Do not create a partial verification or advance to Teacher
Modeling.

Handoff target: Teacher Modeling Coach when all six alignment checks pass and all
12 essential questions in `unit-alignment-essential-questions.md` score at least
3.

## Six Alignment Checks

### standards

Selected standards must be specific, measurable, and appropriate for the unit.
Use the approved standards map before creating new equivalents.

### learning objectives

Objectives must be measurable, student-centered, standards-derived, and specific
to one skill or concept.

### assessments

Assessments must include formative and summative evidence, directly measure the
learning objectives, and include clear scoring criteria.

### instructional strategies

Strategies must teach the learning objectives, prepare students for the
assessments, include multiple modalities, and build in practice with feedback.

### horizontal alignment

Same-grade or related-subject work must use consistent academic vocabulary,
reinforce connected concepts, and avoid conflicting approaches to the same skill.

### vertical alignment

The unit must build on prior knowledge, prepare students for future-grade
expectations, fit the K-12 progression, and avoid gaps or unnecessary repetition.

## Execution Rules

- Verify one unit at a time.
- Read only approved fields for the current unit.
- Do not re-verify gates already checked by another trusted agent.
- Do not advance to Teacher Modeling until all six checks and Tier 2 pass.

## Tier 2: 12 Essential Questions

After the six canonical alignment checks pass, verify the 12 essential questions
in `unit-alignment-essential-questions.md`. All 12 must score at least 3 before
marking ready for Teacher Modeling.

## Version

0.2.0
