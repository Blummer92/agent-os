# Assessment Dashboard Workspace Standard

## Purpose
Define the provider-neutral teacher-workspace contract for assessment planning. The workspace consumes current assessment evidence and presents it through a dashboard overview, focused section editor, contextual guided assistance, and optional technical detail without creating a production UI or authorizing classroom use.

## Upstream Boundary
The workspace consumes #837 assessment-design semantics, #838 blueprint structure, #1192 lifecycle/change-impact/stale-validation evidence, #839 sequencing/student-experience findings, and #841 QA findings by reference. It also consumes Teacher Decision Studio for bounded teacher decisions and Artifact-First Response for artifact/usable-content-first presentation.

It does not create a second lifecycle, sequencing, QA, grading, readiness, approval, recommendation-engine, accommodation, AI-policy, or authority model. #840 is retired and is not an active implementation dependency.

## Canonical Interaction Pattern
Use:

`dashboard overview -> focused section editor -> contextual guided assistance -> optional technical details`

A mandatory linear wizard is not the default shell. Teachers may open sections in any order unless supplied dependency evidence proves an ordering requirement.

## Dashboard Summary
The overview represents at least:
- assessment title, purpose, and type;
- estimated total student time;
- evidence mix;
- approved target coverage summary;
- section count and completion state;
- unresolved blockers;
- major QA warnings;
- planning-only overall status;
- one primary next action when current evidence supports one.

The overview must not expose every question, rubric row, blueprint field, or QA detail.

## Section Contract
Each section record includes a stable section identity/version, name, short purpose, student action summary, evidence type, survey/mastery classification, estimated time, target references, planning-only status, warnings/blockers, permitted actions, alignment reference, QA reference, and revalidation reference when applicable.

Supported actions are descriptive capabilities, not authority grants. They may include open, edit, replace, remove when permitted, duplicate when permitted, request guided help, view alignment, view QA, and return to the dashboard.

## Planning-Only Statuses
Use exactly:
- `not_started`
- `draft`
- `needs_teacher_decision`
- `needs_revision`
- `blocked`
- `approved_section_draft`
- `revalidation_required`

`approved_section_draft` means only that the teacher accepts the section's current planning draft. No status may imply classroom approval, grading authority, readiness, production, publication, execution, source-of-truth write, or external-write authority.

## Nonlinear Editing and Preservation
A bounded section change preserves unrelated valid sections and supplied validations. Revalidation scope is consumed from #1192; this standard does not infer or recompute lifecycle impact.

When a section change affects time, evidence mix, target coverage, sequencing, or QA evidence, the dashboard updates only the affected summaries and exposes the supplied stale/revalidation state. Global reset is invalid unless upstream evidence identifies a shared semantic-root change.

## Contextual Guided Assistance
Guidance is optional and local to the current section or blocker. It must:
1. use known approved context before asking a question;
2. state the detected gap;
3. present one bounded recommended repair first;
4. ask only decisions requiring teacher judgment;
5. preserve unrelated work;
6. expose affected revalidation state; and
7. return to dashboard context after resolution.

Guidance must not silently change targets, grading, rubrics, accommodations, AI policy, or authority fields.

## Warning-to-Repair Contract
Every warning includes:
- stable warning identity;
- problem summary;
- why it matters;
- affected section reference;
- one bounded repair action or direct repair route;
- severity;
- revalidation reference when applicable.

Warnings without a repair route are incomplete. Warning counts alone are not a usable coaching surface.

## Progressive Disclosure
Usable section content and primary actions precede technical audit detail. Full blueprint fields, sequence rationale, source references, accessibility audit, and full QA evidence remain optional detail views.

Technical detail may be accessible but cannot be required before the teacher can identify the section, its purpose, current state, and next action.

## Evidence and Target Summaries
Evidence balance and target coverage are represented as categorical summaries and references, not one universal quality score. Survey evidence and mastery evidence remain visibly and semantically distinct.

A dashboard must not hide a failed category behind an aggregate percentage or score.

## Structured Workspace Result
The machine-checkable result binds:
- `workspace_contract_version` and stable `workspace_id`;
- upstream blueprint, lifecycle, sequencing, and QA identities;
- dashboard summary;
- section records;
- evidence mix;
- target coverage summary;
- warnings;
- blockers and uncertainties;
- preserved section references;
- revalidation references;
- fixed authority.

Identity mismatch, missing required upstream identity, missing fixed authority, or authority elevation fails validation.

## Synthetic Fixtures
Fixtures for this contract are synthetic and noncanonical. They may resemble Unit 0 patterns for regression purposes but are not approved Unit 0 targets, assessments, or classroom materials. #842 is the downstream owner of integrated Unit 0 reference validation after exact approved sources/targets are available.

Positive fixtures prove dashboard overview, direct section access, survey/mastery distinction, bounded preservation after local edits, local guided help, warning-to-repair linkage, summary updates, and optional technical detail.

Negative fixtures prove failure for arbitrary forced linear completion, overview detail dumping, unrelated-section reset, survey/mastery conflation, hidden time/target gaps, authority-confusing status, warning without repair, QA detail before usable content, guidance that restarts unrelated work, authority elevation, and aggregate-score masking.

## Authority and Non-Goals
Every workspace result is planning/report-only. `execution_authorized`, `classroom_use_authorized`, `grading_authorized`, `readiness_authorized`, `production_authorized`, `publication_authorized`, `external_write_authorized`, and `source_of_truth_write_authorized` are always false.

No production UI, frontend framework selection, persistence layer, external-system write, classroom artifact generation, final assessment generation, live teacher pilot, workflow/protected-setting change, credential change, or standalone Assessment Agent is authorized by this contract.

## Version
0.1.0
