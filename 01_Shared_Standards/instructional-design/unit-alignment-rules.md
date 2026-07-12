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
- route to

Required checks:
- standards
- learning objectives
- assessments
- instructional strategies
- horizontal alignment
- vertical alignment

Allowed outputs:
- alignment verification
- status: `PASS` or `BLOCKED`
- blockers
- next owner
- handoff artifacts
- revision suggestions

Blocker behavior: if any required input is missing, incomplete, or misaligned,
stop immediately, name the blocker, and route to the owner in `route to`. Do not
create a partial verification or advance to Teacher Modeling.

Handoff target: Teacher Modeling Coach when all six alignment checks pass AND all
12 essential questions (Tier 2) score ≥3.

## Six Alignment Checks

### standards

The selected standards must be specific, measurable, and appropriate for the unit.
Use the approved standards map before creating new equivalents.

### learning objectives

Objectives must be measurable, student-centered, standards-derived, and specific
to one skill or concept.

### assessments

Assessments must include formative and summative evidence, directly measure the
learning objectives, and include clear scoring criteria.

### instructional strategies

Strategies must actively teach the learning objectives, prepare students for the
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
- Do not advance to Teacher Modeling until all six checks pass.

## Tier 2: 12 Essential Questions

After the six canonical alignment checks PASS, verify the 12 essential questions
in `unit-alignment-essential-questions.md`. These ensure units are rigorous,
relevant, accessible, equitable, and student-centered.

All 12 must score ≥3 before marking ready-for-modeling.

## Version

0.2.0