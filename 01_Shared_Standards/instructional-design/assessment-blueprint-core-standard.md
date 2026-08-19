# Assessment Blueprint Core Standard
## Purpose
Define the provider-neutral planning contract that consumes an approved #837 Assessment Design Record and packages it for downstream assessment planning without redefining assessment-design semantics.

## Ownership Boundary
The #837 Assessment Design Standard owns purpose, target, claim, evidence, classification, method, survey/mastery, scoring-or-observation meaning, authenticity, misconceptions, instructional responses, provenance, blockers, uncertainties, routing, and authority semantics. This blueprint preserves those inputs by reference and structure only. It does not create an Assessment Agent.

## Required Input
Every blueprint consumes one complete `assessment_design_record` containing every field required by `assessment-design-record.v1.schema.json`. Missing, contradictory, unresolved, or invalid upstream content fails closed; the blueprint must not infer replacement semantics.

## Blueprint Core
Every blueprint contains stable `blueprint_id` and `blueprint_version`, the upstream design-record identity, source-version alignment, optional course/unit/lesson context, structured planning objects, validation evidence, blockers, uncertainties, next owner, and authority.

Required structured objects are: `provenance`, `task_format`, `student_time`, `complexity`, `scoring`, `accessibility`, `ai_conditions`, and `validation`. These objects may add planning metadata but may not change the upstream target, claim, evidence, method, policy, accommodation, rubric, or authority meaning.

## Core Validation Outcomes
Use exactly `blocked`, `needs_teacher_decision`, `revision_required`, or `valid`.

`blocked` applies to missing/invalid upstream design input, unresolved provenance, target/claim/evidence/method contradictions, survey-as-mastery contamination, missing authentic evidence, unresolved accessibility or AI-policy conflicts, or authority violations.

`needs_teacher_decision` applies only to a material decision within teacher authority, such as purpose, intended use, available time, scoring/observation approach, authentic-task feasibility, or bounded assignment conditions. Known approved context must not be requested again.

`revision_required` applies when the blueprint is structurally complete but bounded planning metadata is incomplete or inconsistent, such as hidden method limitations, unreasonable time, construct-irrelevant task-format demand, scoring misalignment, or incomplete required downstream data.

`valid` requires a complete upstream record, complete core objects, preserved survey/mastery separation, resolved provenance, no material teacher decision, no required revision, and intact authority fields. `valid` never means classroom-ready, grading-authorized, production-authorized, publishable, or externally writable.

## Provenance
Record source type, identifier, version, approval state, owner/authority, and conflict state for the upstream design record and any rubric, AI-policy, or accommodation reference used by the blueprint. Missing or conflicting required provenance fails closed.

## Scoring
State whether scoring applies, evidence classification, scoring method or observation method, rubric/criteria reference when applicable, success criteria, interpretation limits, survey-only handling, and `grading_authorized: false`. Possible future grade contribution never creates grading authority.

## Accessibility
Represent construct boundary, language, motor/sensory, technology, response-format, background-knowledge, time, and unrelated-reading demands. The blueprint may identify barriers or equivalent-expression possibilities but must not create or change accommodations.

## AI Conditions
When AI policy applies, preserve the canonical policy/assignment reference, allowed/prohibited uses, required disclosure/citation/prompt-submission behavior, and conflict state. The blueprint must not broaden or authorize AI use.

## Authority
Every blueprint is report-only and must keep `execution_authorized`, `classroom_use_authorized`, `grading_authorized`, `readiness_authorized`, `production_authorized`, `publication_authorized`, `external_write_authorized`, and `source_of_truth_write_authorized` false. Missing or true fixed-false fields fail closed.

## Downstream Boundary
The core may emit bounded typed handoff data for sequencing, QA, dashboard, pilot, and portability consumers. It must not implement their sequencing, teacher interaction, dashboard, recommendation, QA, or portability behavior. Change-impact, stale-validation, and bounded invalidation semantics are owned by #1192, not this standard.

## Synthetic Fixtures
Fixtures must be synthetic and noncanonical. They may exercise Unit 0-shaped scenarios but must not become classroom content or universal subject rules.

## Version
0.1.0
