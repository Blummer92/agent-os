# Instructional Design Standards

Shared standards for agents that design, verify, or build classroom units,
teacher modeling, assessments, and student-facing instructional materials.

## Curriculum Pipeline

Read this table before loading deeper standards.

| Stage | Agent | Required input | Gate | Output | Next owner |
|---|---|---|---|---|---|
| Orchestration | Agent Orchestrator | teacher request; available prior outputs; write intent; compute budget | owner, mode, context, and reuse decision selected | task route; mode; context packet; stop/continue decision | Unit Alignment Agent, Teacher Modeling Coach, Instructional Materials Coach, QA / Test Agent, or Workspace Automation Builder |
| Unit Alignment | Unit Alignment Agent | standards; learning objectives; assessments; instructional strategies; horizontal alignment; vertical alignment; alignment status; next_owner | Tier 1: Six alignment checks pass (ready for Teacher Modeling); Tier 2: All 12 essential questions score ≥3 (full certification, production, or explicit request) | alignment verification; status; blockers; checks_passed; checks_failed; handoff_artifacts | Teacher Modeling Coach |
| Teacher Modeling | Teacher Modeling Coach | learning objective; think-aloud method; component breakdown; visual anchors; error analysis; modeling status; next_owner | Five modeling checks pass | modeling documentation; status; blockers; checks_passed; checks_failed; handoff_artifacts | Instructional Materials Coach |
| Instructional Materials | Instructional Materials Coach | approved Teacher Modeling handoff; student-language artifacts; content spec; evidence target; approved template; target folder | Materials QA and write-surface checks pass | generated materials; sources used; approved assets used; remaining rubric risks | QA / unit owner |

Agent Orchestrator routes work into the fixed curriculum sequence: Unit
Alignment → Teacher Modeling → Instructional Materials. Exploratory unit onboarding may use the bounded pre-verification modeling-feasibility advisory defined in `unit-creation-conversational-contract.md`; that advisory creates no gate status and cannot start formal Teacher Modeling before Unit Alignment PASS. When any canonical gate fails, stop, name the blocker, and route to `next_owner` instead of drafting a partial product.

## Scope

These standards apply when an agent aligns units to standards, creates teacher
modeling, designs assessment evidence, generates classroom slides/worksheets, or
routes curriculum work.

## Canonical Checks

Unit Alignment uses exactly six alignment checks: standards, learning objectives,
assessments, instructional strategies, horizontal alignment, and vertical
alignment.

Teacher Modeling uses exactly five modeling checks: learning objective,
think-aloud method, component breakdown, visual anchors, and error analysis.

Assessment design uses the target-first contract in
`assessment-design-standard.md` before item or task generation. Blueprint core
planning then packages that approved design through
`assessment-blueprint-core-standard.md` without redefining its semantics. Both
are report-only and do not authorize grading, readiness, classroom use,
production, or writes.

## Files

- `unit-alignment-rules.md` — canonical Unit Alignment schema and six checks
- `teacher-modeling-standards.md` — canonical Teacher Modeling schema and checks
- `orchestration-rules.md` — canonical owner, mode, context, reuse, and stop rules
- `unit-creation-conversational-contract.md` — exploratory unit-planning presentation, teacher-choice, confirmation, Unit Sketch, bounded advisory semantics, and cross-owner integration boundary
- `assessment-design-standard.md` — target → claim → evidence → method contract and survey/mastery boundary
- `assessment-blueprint-core-standard.md` — #837-preserving blueprint schema and fail-closed core validation; lifecycle/staleness remains #1192
- `student-language-standard.md` — reusable student-facing language artifacts
- `learning-science-rules.md` — classroom design rules for materials
- `production-gates-and-compute.md` — hard-stop gates and efficiency rules
- `material-quality-rubric.md` — QA contract for slides and worksheets
- `artifact-first-response-standard.md` — response ordering for classroom-material requests
- `teacher-decision-studio-standard.md` — table-first rubric/assessment consultation protocol
- `teacher-decision-studio-previews-standard.md` — per-option worksheet and PDF preview rules

## Core Rule

Standards files are the source of truth for execution rules. Overlays define
agent ownership and write boundaries. Prompt templates only load the right role,
fields, standards, and output keys.

## Version

0.11.0
