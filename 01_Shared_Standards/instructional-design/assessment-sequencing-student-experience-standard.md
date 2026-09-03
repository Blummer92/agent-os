# Assessment Sequencing and Student Experience Standard

## Purpose
Define the provider-neutral sequencing and student-experience contract that consumes a current, valid #838 Assessment Blueprint Core plus #1192 lifecycle evidence. This standard orders assessment sections, validates dependencies, student directions, cognitive flow, accessibility patterns, engagement, time, workload, and downstream handoffs without redefining assessment-design, blueprint, lifecycle, QA, grading, or classroom-use authority.

## Upstream Boundary
Inputs must identify the blueprint and lifecycle versions, current validation state, approved targets, claims, observable evidence, methods, scoring/observation requirements, survey/mastery classifications, accessibility record, AI conditions, student-time estimate, blockers, uncertainties, and fixed authority. Missing, blocked, stale, invalid, ambiguous, or conflicting upstream evidence fails closed.

#839 consumes #837 assessment-design meaning, #838 blueprint structure, and #1192 change-impact/stale-validation/bounded-invalidation behavior. It must not create a second lifecycle model or reinterpret purpose, targets, claims, evidence, method eligibility, scoring policy, accommodations, AI policy, provenance, or authority.

## Section Contract
Each section has a stable ID and version, purpose and type, target/claim/evidence/method references, survey/mastery status, prerequisite and dependency IDs, required/optional status, optional branch condition, student directions, approved vocabulary references, materials/tools, reading/setup/response/transition/submission time estimates, scoring/observation implications, cognitive burden, accessibility findings, engagement rationale, AI-direction requirements, blockers, uncertainties, and fixed authority.

Stable section IDs are preserved across revisions unless a section is intentionally replaced.

## Deterministic Sequencing
Order sections by actual prerequisites and evidence dependencies rather than a universal lesson ladder. When applicable, prefer orientation/access information before setup; prerequisites before dependent application; foundational evidence before authentic performance; artifact/performance creation before critique; feedback before revision; evidence/experience before reflection; and closure/submission confirmation last.

Surveys remain separate from mastery. Orientation and practice never silently become mastery evidence. Assessment order is not automatically instructional lesson order.

## Dependencies and Branching
Recognize hard prerequisite, soft prerequisite, evidence dependency, resource dependency, policy dependency, optional enrichment, conditional remediation, conditional extension, teacher-selected, and accessibility-equivalent branches.

Every branch preserves target alignment, evidence sufficiency, scoring interpretation, survey/mastery separation, accessibility, AI policy, and fixed authority. Branches may not introduce new targets or policy.

## Reorder and Removal
Reordering is valid only when prerequisites, evidence dependencies, tool availability, survey/mastery boundaries, time/workload feasibility, accessibility, and affected downstream handoffs remain valid.

Removing a section requires review of target and claim coverage, evidence sufficiency, scoring, total time, teacher workload, downstream dependencies, and lifecycle stale state. Preserve unrelated valid sections; do not globally invalidate after a bounded local change.

## Cognitive Flow
Track difficulty, conceptual and procedural complexity, novelty, reading/writing load, motor/sensory load, technology load, task switching, decision density, time pressure, fatigue, and working-memory demand. Section burden is `low`, `moderate`, `high`, or `unresolved`.

Require revision when high-burden sections cluster without purpose, task switching is excessive, instructions/tools/sources appear after use, hidden conditions overload memory, construct-irrelevant reading/navigation burden is excessive, or total duration risks fatigue. Repairs may reorder, split, shorten, checklist, surface resources earlier, reduce switching, separate setup from mastery, add a bounded example, divide across sessions, or remove redundant evidence without scaffolding away the construct.

## Student Language and Vocabulary
Directions state what to do, use, create/select, submit, explain, revise, how completion is determined, what is scored/observed, applicable AI rules, and where materials/sources are located. Use direct actionable language, expose multi-step order, distinguish required/optional, saving/submitting, and draft/final, and avoid internal blueprint terminology and hidden requirements.

Vocabulary used for mastery must be approved, explicitly taught or practiced, assessment-eligible, and source-traceable. Construct-relevant technical language stays distinct from instruction-only language, unnecessary academic language, ambiguous/culturally dependent wording, idioms, and terms needing glossary/visual support. Vocabulary recall must not replace application, critique, judgment, revision, or performance evidence.

## Survey, AI, and Scoring Language
Survey wording remains neutral and non-mastery, separates confidence/interest/experience/preference, supports optional/sensitive/skip behavior, and never converts perception into demonstrated readiness.

AI directions consume only canonical assignment-specific AI policy and may state allowed/prohibited uses, disclosure, citation, prompt-submission, existing consequences, and clarification path. Missing or conflicting policy fails closed.

Scoring language matches approved rubric/success criteria and distinguishes scored, observed, completion-only, survey-only, and ungraded practice while preserving `grading_authorized: false`.

## Accessibility, Engagement, Time, and Workload
Review reading, language, motor, sensory, technology, response format, timing, navigation, layout, color dependence, media controls, interaction, source access, tools, and unrelated background knowledge. Equivalent expression modes are allowed only when construct and evidence remain intact; this standard never creates or changes accommodations.

Engagement means meaningful participation supporting valid evidence. Authentic context, bounded choice, scenarios, media, meaningful final tasks, and response-format variation are allowed only when they preserve comparability, evidence, accessibility, time, scoring, and policy. Reject decorative gamification or novelty that adds burden without evidentiary value.

Time estimates include applicable reading, setup, transition, tool access, response/performance, revision, upload/submission, teacher directions, and troubleshooting. Use approved local constraints rather than universal limits.

Teacher workload tracks scoring, rubric complexity, observation, simultaneous observation count, conferences, setup/reset, artifact review, feedback, and reassessment. Recommend the smallest valid repair when workload threatens reliable evidence; do not replace required evidence automatically.

## Validation Outcomes
Return exactly one sequence state: `blocked`, `needs_teacher_decision`, `revision_required`, or `valid`.

- `blocked`: upstream blueprint/lifecycle is missing, invalid, blocked, stale, or ambiguous; prerequisites are absent; required coverage/evidence would be lost; survey contaminates mastery; vocabulary is ineligible; accessibility invalidates evidence; AI/scoring policy conflicts; or authority is missing/invalid.
- `needs_teacher_decision`: a teacher-owned choice materially changes section order, total time, multi-session use, bounded student choice, workload feasibility, or optional-section inclusion.
- `revision_required`: the sequence is valid in principle but directions, time, workload, task switching, burden grouping, engagement, downstream handoff completeness, or lifecycle state requires repair.
- `valid`: upstream evidence is current/valid, dependencies hold, language/accessibility/time/workload are feasible, survey/mastery separation is intact, AI/scoring language matches canonical sources, handoffs are complete, and fixed authority remains valid.

A valid sequence authorizes no classroom use, grading, readiness, production, publication, or external write.

## Change Impact and Multi-Session Behavior
Use #1192 lifecycle classifications rather than redefining them. Section reorder/insertion/removal, dependency, time, obligation-changing directions, response mode, accessibility, AI/scoring language, workload, or branch changes require the corresponding lifecycle revalidation and affected downstream invalidation. Preserve unrelated valid sections.

Multi-session sequences require explicit session boundaries, stable section IDs, dependency/artifact continuity, restart directions, policy consistency, scoring consistency, and renewed total-time/fatigue validation.

## Structured Output and Handoff
A sequencing result includes contract/result versions and IDs, blueprint/lifecycle references, sequence state, ordered section IDs, section records, prerequisites/dependencies/branches, student/vocabulary/survey/AI/scoring language findings, time/workload, cognitive/accessibility/engagement findings, blockers/uncertainties, lifecycle/change-impact evidence, preserved sections, downstream handoffs, and fixed authority.

#841 consumes QA-relevant findings; #843 consumes section/order/status/time/workload/warning inputs; #846 consumes portable sequencing semantics and regression evidence. These handoffs do not define QA, dashboard, or cross-unit policy.

## Authority and Non-Goals
Fixed authority is inherited from #838: report-only true; execution, classroom-use, grading, readiness, production, publication, external-write, and source-of-truth-write authorization false. Any missing or true prohibited authority field is invalid.

No assessment generation, production student artifact, QA engine, dashboard UI, recommendation engine, accommodation/AI/rubric policy change, Notion/Drive write, grading/readiness mutation, new Assessment Agent, workflow/protected-setting change, credential change, production effect, or external write.

## Version
0.1.0
