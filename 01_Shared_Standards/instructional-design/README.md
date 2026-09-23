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
`assessment-blueprint-core-standard.md` without redefining its semantics.
Lifecycle version transitions, change impact, stale validation, bounded
invalidation, and revalidation scope then use
`assessment-blueprint-lifecycle-standard.md`. A current validated blueprint then
uses `assessment-sequencing-student-experience-standard.md` for section order,
dependencies, student language, cognitive flow, accessibility, engagement, time,
and teacher workload. QA then uses `assessment-qa-evidence-review-standard.md`
to evaluate alignment, evidence, method/task quality, sequencing findings,
accessibility, fairness, AI-policy alignment, workload, and instructional
usefulness. Teacher workspace presentation then uses
`assessment-dashboard-workspace-standard.md` for dashboard overview, focused
section editing, contextual guided assistance, warning-to-repair behavior, and
progressive disclosure while consuming lifecycle, sequencing, and QA evidence by
reference. Synthetic Unit 0 integration validation then uses
`unit0-assessment-reference-validation-standard.md` to verify that these contracts
compose without turning fixture identities into canonical curriculum content.
Cross-unit portability validation then uses
`assessment-cross-unit-validation-standard.md` to verify that the same architecture
generalizes across Photography, Typography, Graphic Design, Branding, Video
Production, and AI Media without domain-name defaults or cross-domain rule leakage.
All remain report/planning/test-only and do not authorize grading, readiness,
classroom use, production, publication, or writes.

## Files

- `unit-alignment-rules.md` — canonical Unit Alignment schema and six checks
- `teacher-modeling-standards.md` — canonical Teacher Modeling schema and checks
- `orchestration-rules.md` — canonical owner, mode, context, reuse, and stop rules
- `unit-creation-conversational-contract.md` — exploratory unit-planning presentation, teacher-choice, confirmation, Unit Sketch, bounded advisory semantics, and cross-owner integration boundary
- `assessment-design-standard.md` — target → claim → evidence → method contract and survey/mastery boundary
- `assessment-blueprint-core-standard.md` — #837-preserving blueprint schema and fail-closed core validation
- `assessment-blueprint-lifecycle-standard.md` — #1192 lifecycle, stale-state, change-impact, bounded-invalidation, and revalidation contract
- `assessment-sequencing-student-experience-standard.md` — #839 section sequencing, dependencies, student language, cognitive flow, accessibility, engagement, time, and workload contract
- `assessment-qa-evidence-review-standard.md` — #841 QA categories, evidence validity, fairness/accessibility review, finite dispositions, and non-authorizing QA report contract
- `assessment-dashboard-workspace-standard.md` — #843 dashboard-first workspace, focused section editor, contextual guidance, warning-to-repair, progressive-disclosure, and planning-only status contract
- `unit0-assessment-reference-validation-standard.md` — #842 synthetic/noncanonical Unit 0 integration and regression contract over the existing assessment stack
- `assessment-cross-unit-validation-standard.md` — #846 synthetic cross-unit portability/regression contract that rejects domain-name defaults and cross-domain assessment-rule leakage
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

0.17.0
