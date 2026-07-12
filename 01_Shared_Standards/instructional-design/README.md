# Instructional Design Standards

Shared standards for agents that design, verify, or build classroom units,
teacher modeling, and student-facing instructional materials.

## Curriculum Pipeline

| Stage | Agent | Required input | Gate | Output | Next owner |
|---|---|---|---|---|---|
| Unit Alignment | Unit Alignment Agent | standards; learning objectives; assessments; instructional strategies; horizontal alignment; vertical alignment | Six alignment checks pass | Alignment verification and ready-for-modeling status | Teacher Modeling Coach |
| Teacher Modeling | Teacher Modeling Coach | learning objective; think-aloud method; component breakdown; visual anchors; error analysis | Five modeling checks pass | Modeling documentation and ready-for-materials status | Instructional Materials Coach |
| Instructional Materials | Instructional Materials Coach | approved modeling documentation; content spec; approved template; target folder | Materials QA and write-surface checks pass | Slides, worksheets, and generated-file links | QA / unit owner |

Agents advance only through this sequence: Unit Alignment → Teacher Modeling →
Instructional Materials. When any gate fails, stop, name the blocker, and route
instead of drafting a partial product.

## Scope

These standards apply when an agent aligns units to standards, creates teacher
modeling, generates classroom slides/worksheets, or routes curriculum work.

## Canonical Checks

Unit Alignment uses exactly six alignment checks:
standards, learning objectives, assessments, instructional strategies,
horizontal alignment, and vertical alignment.

Teacher Modeling uses exactly five modeling checks:
learning objective, think-aloud method, component breakdown, visual anchors,
and error analysis.

## Files

- `unit-alignment-rules.md` — canonical Unit Alignment schema and six checks
- `teacher-modeling-standards.md` — canonical Teacher Modeling schema and checks
- `learning-science-rules.md` — classroom design rules for materials
- `production-gates-and-compute.md` — hard-stop gates and efficiency rules
- `material-quality-rubric.md` — QA contract for slides and worksheets

## Core Rule

Standards files are the source of truth for execution rules. Overlays define
agent ownership and write boundaries. Prompt templates only load the right role,
fields, standards, and output keys.

## Version

0.2.0