# Assessment QA and Evidence Review Standard

## Purpose
Define the provider-neutral QA contract that evaluates one current #838 Assessment Blueprint Core, its #1192 lifecycle evidence, and the corresponding #839 sequencing/student-experience result. This standard verifies educational validity and instructional usefulness without generating assessments, redefining upstream semantics, or authorizing classroom use.

## Upstream Boundary
Inputs must bind the same blueprint identity/version across the blueprint, lifecycle, and sequencing evidence. The blueprint must be current and valid; lifecycle evidence must not be stale or ambiguous; the sequencing result must be current and not blocked. Missing, stale, blocked, invalid, conflicting, or identity-mismatched upstream evidence fails closed.

#841 consumes #837 target/claim/evidence/method meaning, #838 blueprint structure, #1192 currentness/change-impact behavior, and #839 sequencing/student-experience findings by reference. It must not create a second sequencing, lifecycle, grading, approval, or readiness model.

## Independent QA Categories
Evaluate each category independently so one finding cannot hide another:
- alignment: approved target, claim, task, evidence, and scoring/observation remain aligned;
- evidence: observable evidence is sufficient, interpretable, and authentic when #837 requires direct performance/process evidence;
- method/task quality: method limitations, wording, ambiguity, cognitive demand, and response demands do not invalidate the construct;
- survey/mastery separation: confidence, interest, preference, experience, and readiness-survey responses remain `survey_only` and never become mastery evidence;
- sequencing: consume #839 dependency, cognitive-flow, fatigue, language, time, workload, accessibility, and engagement findings without recomputing sequence order;
- accessibility and construct relevance: construct-irrelevant reading, motor, sensory, technology, response-format, time, navigation, or background-knowledge demands do not distort interpretation;
- fairness: opportunity to learn, bias risk, cultural assumptions, irrelevant background knowledge, and unequal construct-irrelevant demands are reviewed explicitly;
- AI policy: when applicable, the assessment matches the canonical assignment-specific AI policy, disclosure/citation/prompt-submission rules, and allowed/prohibited uses;
- teacher workload: observation/scoring burden permits reliable evidence collection and interpretation;
- instructional usefulness: evidence supports at least one bounded instructional interpretation such as misconception detection, reteaching, support, revision, or next-step planning rather than producing score-only output.

## Evidence Rules
A procedural, technical-workflow, performance, critique, revision, or creative-production claim cannot be validated from selected response or recall evidence alone when #837 requires authentic evidence. A product alone does not automatically establish process, authorship, collaboration, revision, or decision quality.

Untaught targets, content, or assessment-eligible vocabulary fail closed. Vocabulary may be assessed only when the upstream evidence proves explicit instruction or practice and assessment eligibility.

Missing scoring or observation guidance is a QA defect when interpretation depends on criteria. Survey-only evidence is never scored as mastery.

## Accessibility and Fairness Review
Accessibility and fairness are separate findings. The contract may identify barriers, evidence limitations, or possible equivalent-expression needs but never creates or changes accommodations.

Use `manual_review` when the record is structurally complete but a bounded professional judgment is genuinely unresolved, including cultural-context ambiguity, uncertain opportunity-to-learn evidence, accessibility equivalence that cannot be determined from supplied evidence, or uncertain construct relevance. Manual review is not a softer form of `valid`.

## Deterministic Dispositions
Return exactly one overall disposition using this precedence:
1. `blocked`
2. `manual_review`
3. `revision_required`
4. `valid`

`blocked` applies when upstream evidence is missing/stale/invalid; identities conflict; authority is invalid; required observable/authentic evidence is absent; survey contaminates mastery; untaught content or vocabulary is required; or an unresolved policy/accessibility conflict prevents valid interpretation.

`manual_review` applies when deterministic checks are complete but a bounded professional judgment remains unresolved in fairness, cultural context, opportunity to learn, accessibility equivalence, construct relevance, or another explicitly recorded review item.

`revision_required` applies when the assessment is viable but bounded repair is needed in wording, ambiguity, evidence mix, scoring/observation guidance, instructional usefulness, teacher workload, or a nonblocking #839 finding.

`valid` requires current identity-bound upstream evidence, all required categories passing, no blocker, no manual-review item, no required revision, and intact fixed authority.

## Assessment QA Report
Every report includes `qa_contract_version`, stable `qa_report_id`, blueprint/lifecycle/sequencing identities and versions, `overall_disposition`, category findings, `blockers`, `required_revisions`, `manual_review_items`, `remaining_risks`, `next_owner`, and fixed authority.

Category findings use finite states `pass`, `fail`, `manual_review`, or `not_applicable`, plus evidence and an optional required action. Alignment and evidence must always be separate category findings.

The report should name actionable instructional implications when evidence supports them. It must not invent remediation beyond supplied targets, criteria, policy, or teacher authority.

## Unit 0 Synthetic Fixtures
Unit 0-shaped fixtures are synthetic regression evidence only and are never canonical classroom content. Positive coverage includes survey/mastery separation, file-organization performance, equipment-inspection observation, evidence-based critique, assignment-specific AI judgment, and vocabulary application after instruction/practice.

Negative coverage includes confidence-as-mastery, missing observable evidence, procedural skill assessed only through selected response, creative/critique evidence reduced to recall, untaught content/vocabulary, excessive construct-irrelevant reading demand, inaccessible or ambiguous wording, poor sequencing supplied by #839, invalid/repetitive evidence mix, AI-policy conflict, missing scoring/observation guidance, score-only output with no instructional usefulness, and any authority elevation attempt.

## Downstream Handoff
#842 may consume valid or explicitly non-valid QA reports as synthetic Unit 0 pilot evidence. #843 may consume QA warnings for dashboard presentation, and #846 may consume portable QA semantics and regression evidence. These handoffs do not authorize those downstream behaviors or redefine their contracts.

## Authority and Non-Goals
Every result is report-only. `execution_authorized`, `classroom_use_authorized`, `grading_authorized`, `readiness_authorized`, `production_authorized`, `publication_authorized`, `external_write_authorized`, and `source_of_truth_write_authorized` are always false. Missing or true prohibited authority fields are invalid.

No assessment generation, item writer, dashboard UI, recommendation engine, persistence, accommodation/AI/rubric policy change, grading/readiness mutation, production effect, external write, workflow/protected-setting change, credential change, or standalone Assessment Agent.

## Version
0.1.0
