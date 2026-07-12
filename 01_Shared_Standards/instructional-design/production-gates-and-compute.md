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

## Agent Compute Profiles

Pipeline: Unit Alignment → Teacher Modeling → Instructional Materials.

### Unit Alignment Agent

- Read only: standards, learning objectives, assessments, instructional strategies, horizontal alignment, vertical alignment, 12 essential questions.
- Reuse: prior standards maps, approved unit structure, previously verified alignment if source fields did not change.
- Skip: Teacher Modeling, Instructional Materials, student-facing artifact generation.
- Cache/memoize: standards lookup, standards-to-objective map, six-check result, 12-question score.
- Never re-check: a gate already verified by another trusted agent with unchanged source fields.

### Teacher Modeling Coach

- Read only: approved Unit Alignment handoff, learning objective, think-aloud method, component breakdown, visual anchors, error analysis, student-language standard.
- Reuse: approved think-aloud patterns, visual anchor patterns, common-error examples, student sentence frames.
- Skip: Unit Alignment re-verification, materials generation, full unit history.
- Cache/memoize: modeling pattern, common error library, sentence-frame set, visual-anchor pattern.
- Never re-check: Unit Alignment's six checks or 12 essential questions.

### Instructional Materials Coach

- Read only: approved Teacher Modeling handoff, student-language artifacts, content spec, evidence target, approved template, target folder, material-quality rubric.
- Reuse: approved templates, approved assets, modeling outputs, sentence frames, rubric language.
- Skip: Unit Alignment re-verification, Teacher Modeling re-verification, unrelated lessons, archived notes.
- Cache/memoize: template map, asset library, approved language snippets, failed rubric rows.
- Never re-check: Unit Alignment or Teacher Modeling gates once approved and handed off.

## Version

0.2.0

## Changelog

- 0.2.0 added Agent Compute Profiles (read only, reuse, skip, cache/memoize,
  never re-check) per pipeline agent.
- 0.1.0 initial gates and compute rules.
