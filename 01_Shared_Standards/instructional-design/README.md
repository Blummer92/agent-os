# Instructional Design Standards

Shared standards for agents that design, verify, or build classroom units,
modeling demonstrations, and student-facing instructional materials.

## Scope

These standards apply when an agent aligns units to standards, creates teacher
modeling, generates classroom slides/worksheets, or routes curriculum work.

## The Curriculum Pipeline

1. **Unit Alignment Agent** — Verifies units align to standards (unit-alignment-rules.md)
2. **Teacher Modeling Coach** — Creates modeling demos (teacher-modeling-standards.md)
3. **Instructional Materials Coach** — Generates slides/worksheets (learning-science-rules.md)

Each agent hands off to the next only when all gates pass.

## Files

- `unit-alignment-rules.md` — 5-component alignment verification
- `teacher-modeling-standards.md` — 5-component modeling verification
- `learning-science-rules.md` — classroom design rules for materials
- `production-gates-and-compute.md` — hard-stop gates and efficiency rules
- `material-quality-rubric.md` — QA contract for slides and worksheets

## Core Rule

Agents must not advance a unit or create materials until required gates pass.
When a gate fails, route the work instead of drafting a partial product.

## Version

0.2.0
