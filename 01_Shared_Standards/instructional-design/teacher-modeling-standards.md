# Teacher Modeling Standards

Canonical rules for creating Teacher Modeling after Unit Alignment passes and
before Instructional Materials work begins.

## Canonical Schema

Required input fields:
- learning objective
- think-aloud method
- component breakdown
- visual anchors
- error analysis
- modeling status
- next_owner

Required checks:
- learning objective
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
- files_changed
- tests_run

Blocker behavior: if any required input is missing, incomplete, or blocked, stop
immediately, name the blocker, set `status: BLOCKED`, and route to `next_owner`.
Do not draft partial modeling or advance to Instructional Materials.

Handoff target: Instructional Materials Coach when all five modeling checks pass.

## Five Modeling Checks

### learning objective

The modeling must target exactly one specific skill or standard, be measurable
and observable, match the approved unit objective, and avoid bundled skills.

### think-aloud method

Teacher narration must make invisible thinking visible, explain why choices are
made, name strategies and decision points, and use student-accessible language.

### component breakdown

Complex skills must be split into small sequential steps, ordered from simplest
to most complex, taught in practice order, and labeled for student reference.

### visual anchors

Modeling must identify charts, organizers, props, tools, symbols, or visual
hierarchy that support student understanding.

### error analysis

Modeling must include a common mistake, show how to recognize it, demonstrate
self-correction, and explain how to avoid the mistake in future work.

## Execution Rules

- Create one modeling session per learning objective.
- Read only approved fields for the current lesson or unit.
- Reuse approved think-aloud templates and visual anchor patterns before creating
  new ones.
- Do not re-check Unit Alignment gates already verified by Unit Alignment Agent.
- Do not advance to Instructional Materials until all five checks pass.

## Version

0.1.0
