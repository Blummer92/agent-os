# Production Gates and Compute Rules

These rules prevent unnecessary generation, repeated review, and wasted model
calls while protecting classroom-material quality.

## Hard Stop Gates

Generation is allowed only when all conditions are true:

1. `Source Confidence` is approved.
2. `Unit Readiness` is ready.
3. `Modeling Readiness` is ready for slides or ready for materials.
4. `Evidence Target` is populated for worksheets or assessments.
5. `Blockers` is none.

If any condition fails, the agent must stop, name the blocker, and route to the
owning dashboard. It must not create a partial slide deck, worksheet, rubric,
packet, or placeholder product.

## Blocker Taxonomy

Use one of these blocker labels:

- Missing target
- Missing modeling
- Missing evidence
- Missing pacing
- Missing unit structure
- Low source confidence
- Active blocker
- Ownership conflict
- Human review needed

## Anti-Duplication Rule

Do not re-check a condition already verified by the owning gate unless the
source field changed after the last verification timestamp.

## Smallest Context Rule

Agents should read only the approved fields needed for the current lesson and
material type. Do not load full unit history, unrelated lessons, or archived
notes unless the gate explicitly requires them.

## Reuse Rule

Use approved modeling language, task frames, directions, visuals, templates,
and rubric language before generating new equivalents.

## Pipeline Rule

Use the fixed sequence:

1. Gate check.
2. Generate only if ready.
3. QA against the shared rubric.
4. Revise only the flagged rubric rows.

Agents must not self-orchestrate extra reviewers or repeat checks that belong
to another owner.

## Version

0.1.0
