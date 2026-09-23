# Assessment Design Standard
## Purpose
Define the provider-neutral, target-first contract used before assessment item or task generation. This standard implements #837 only and does not create a standalone Assessment Agent.

## Authority
Every result is report-only and must contain: `report_only: true`, `target_approval_authorized: false`, `grading_authorized: false`, `readiness_authorized: false`, `classroom_use_authorized: false`, `production_authorized: false`, `publication_authorized: false`, `external_write_authorized: false`, and `source_of_truth_write_authorized: false`. Missing or true fixed-false fields fail closed.

## Required Sequence
1. Retrieve canonical or approved context.
2. Classify assessment purpose and intended instructional decision.
3. Confirm the approved learning target.
4. Define the student-learning claim and observable evidence.
5. Classify the target.
6. Select the assessment method and any evidence-required supporting methods.
7. Define scoring or observation needs, misconceptions, and possible instructional responses.
8. Validate survey/mastery separation, authenticity, accessibility, provenance, and authority.
9. Produce the versioned design record and hand off to the blueprint owner.

Item or delivery format must not be the starting point when it would override evidence requirements.

## Purpose Classes
Use one explicit class: `readiness_survey`, `interest_confidence_experience_survey`, `diagnostic`, `formative`, `interim`, `summative`, `performance`, `portfolio`, `hybrid`, or `practice_non_assessment`. Purpose is determined by intended use, not title or question format. Survey evidence may guide planning but never establishes mastery or enters mastery scoring.

## Target Classes
Use a primary class, plus supporting classes only when essential: `recall`, `conceptual_understanding`, `procedural_skill`, `technical_workflow`, `judgment`, `critique`, `revision`, `creative_production`, `performance`, `reflection_metacognition`, or `collaboration`.

## Evidence Classes
Every evidence record is exactly one of `mastery_capable`, `supporting_only`, or `survey_only`. Confidence, interest, preference, perceived readiness, and prior experience are `survey_only`. Reflection or self-assessment is supporting unless reflection is the approved target.

## Method Rules
Selected response supports recall and limited concept discrimination but cannot independently establish procedure, technical workflow, critique, revision, creativity, or performance. Scenarios may establish judgment but not actual execution. Products do not automatically prove process, authorship, collaboration, or revision. Performance and procedural claims require direct observation, demonstration, simulation, process evidence, or another justified authentic method. Multiple methods are required when one method cannot establish every essential claim component.

## Claim And Evidence Boundaries
A claim may operationalize an approved target but must not broaden, narrow, or rewrite it. Evidence is sufficient only when it covers the essential claim, occurs under appropriate conditions, is interpretable using defined criteria, avoids construct-irrelevant demands, and records limitations and provenance.

## Accessibility And Policy
Separate the intended construct from language, motor, sensory, technology, response-format, background-knowledge, and time demands. Equivalent expression is allowed only when the construct is preserved. Do not create or alter accommodations, rubrics, grading policy, AI policy, learning targets, or approval state.

## Blockers
Return `blocked` for missing or unapproved target, missing intended use, missing claim or observable evidence, method mismatch, survey-as-mastery, missing required authentic evidence, missing provenance, unresolved policy/accommodation conflict, or authority violation. Return `needs_teacher_decision` only when a teacher-authorized decision materially changes purpose, intended use, available time, scoring/observation, authentic-task feasibility, or bounded assignment conditions.

## Required Design Record
A versioned record must include `assessment_design_contract_version`, `design_record_id`, `source_context`, `assessment_purpose`, `intended_instructional_decision`, `approved_target_ref`, `target_source_state`, `claim_id`, `claim_statement`, `primary_target_classification`, `supporting_target_classifications`, `observable_evidence`, `evidence_sufficiency_rule`, `evidence_exclusions`, `selected_method`, `supporting_methods`, `method_rationale`, `method_limitations`, `survey_mastery_classification`, `scoring_or_observation_requirement`, `success_evidence_features`, `likely_misconceptions`, `possible_instructional_responses`, `accessibility_considerations`, `authenticity_requirement`, optional `AI_policy_ref` and `rubric_ref`, `provenance`, `blockers`, `unresolved_uncertainties`, `next_owner`, and `authority`.

## Handoff
The record above is the stable #838 handoff. #838 owns blueprint lifecycle and schema validation; it must not redefine these assessment-design semantics.

## Synthetic Fixture Rule
Unit 0 examples are synthetic regression fixtures only. They must not become canonical classroom content or universal subject rules.

## Version
0.1.0
