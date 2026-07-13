# Teacher Modeling Standards

Canonical rules for creating Teacher Modeling after Unit Alignment passes and
before Instructional Materials work begins.

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

Blocker behavior: if any required input is missing, incomplete, or blocked, stop,
name the blocker, set `status: BLOCKED`, and route to `next_owner`. Do not draft
partial modeling or advance to Instructional Materials.

Handoff target: Instructional Materials Coach when modeling checks pass.

## Six Modeling Checks

### learning objective

The model targets one specific measurable skill, matches the approved objective,
and avoids bundled skills.

### student task alignment

Teacher modeling must directly prepare students for the next visible student task
or product.

### think-aloud method

Teacher narration makes invisible thinking visible, explains why choices are
made, names strategies and decision points, and uses student-accessible language.

### component breakdown

Complex skills are split into small sequential steps, ordered in practice order,
and labeled for student reference.

### visual anchors

Modeling identifies charts, organizers, tools, symbols, examples, or visual
hierarchy that support understanding.

### error analysis

Modeling includes a common mistake, how to recognize it, how to self-correct,
and how to avoid it in future work.

## Execution Rules

- Create one modeling session per learning objective.
- Read only approved fields for the current lesson or unit.
- Reuse approved think-aloud templates and visual anchor patterns before creating new ones.
- Do not re-check Unit Alignment gates already verified by Unit Alignment Agent.
- Do not advance to Instructional Materials until modeling checks pass.
- Give the most usable teacher move or language first when coaching in chat.

## Version

0.2.0