# Instructional Design Standards

Shared standards for agents that design, verify, or build classroom units,
teacher modeling, and student-facing instructional materials.

## Curriculum Pipeline

Read this table before loading deeper standards.

| Stage | Agent | Required input | Gate | Output | Next owner |
|---|---|---|---|---|---|
| Orchestration | Agent Orchestrator | teacher request; available prior outputs; write intent; compute budget | owner, mode, context, and reuse decision selected | task route; mode; context packet; stop/continue decision | Unit Alignment Agent, Teacher Modeling Coach, Instructional Materials Coach, QA / Test Agent, or Workspace Automation Builder |
| Unit Alignment | Unit Alignment Agent | standards; learning objectives; assessments; instructional strategies; horizontal alignment; vertical alignment; alignment status; next_owner | Six alignment checks and 12 essential questions pass | alignment verification; status; blockers; checks_passed; checks_failed; handoff_artifacts | Teacher Modeling Coach |
| Teacher Modeling | Teacher Modeling Coach | learning objective; think-aloud method; component breakdown; visual anchors; error analysis; modeling status; next_owner | Five modeling checks pass | modeling documentation; status; blockers; checks_passed; checks_failed; handoff_artifacts | Instructional Materials Coach |
| Instructional Materials | Instructional Materials Coach | approved Teacher Modeling handoff; student-language artifacts; content spec; evidence target; approved template; target folder | Materials QA and write-surface checks pass | generated materials; sources used; approved assets used; remaining rubric risks | QA / unit owner |

Agent Orchestrator routes work into the fixed curriculum sequence: Unit
Alignment → Teacher Modeling → Instructional Materials. When any gate fails,
stop, name the blocker, and route to `next_owner` instead of drafting a partial
product.

## Scope

These standards apply when an agent aligns units to standards, creates teacher
modeling, generates classroom slides/worksheets, or routes curriculum work.

## Canonical Checks

Unit Alignment uses exactly six alignment checks: standards, learning objectives,
assessments, instructional strategies, horizontal alignment, and vertical
alignment.

Teacher Modeling uses exactly five modeling checks: learning objective,
think-aloud method, component breakdown, visual anchors, and error analysis.

## Files

- `unit-alignment-rules.md` — canonical Unit Alignment schema and six checks
- `teacher-modeling-standards.md` — canonical Teacher Modeling schema and checks
- `orchestration-rules.md` — canonical owner, mode, context, reuse, and stop rules
- `student-language-standard.md` — reusable student-facing language artifacts
- `learning-science-rules.md` — classroom design rules for materials
- `production-gates-and-compute.md` — hard-stop gates and efficiency rules
- `material-quality-rubric.md` — QA contract for slides and worksheets

## Core Rule

Standards files are the source of truth for execution rules. Overlays define
agent ownership and write boundaries. Prompt templates only load the right role,
fields, standards, and output keys.

## Version

0.5.0
