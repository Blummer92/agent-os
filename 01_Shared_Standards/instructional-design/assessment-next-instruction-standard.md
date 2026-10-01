# Assessment Next-Instruction Analysis Standard

## Purpose
Define the governed contract that turns a bounded, teacher-reviewed, class-level post-administration assessment evidence summary into versioned next-instruction options. The analysis keeps observed evidence, inferred hypotheses, and bounded instructional options structurally separate so an inference can never be mistaken for a measurement and an advisory option can never overwrite a teacher decision.

This standard answers the bounded gap named in #1891: post-administration evidence analysis into next-instruction options. It does not repeat the assessment-design QA role of #841 (pre-administration design review) and does not perform the LP pacing handoff's lesson-time feasibility evaluation.

## Upstream Boundary
Intake binds one approved assessment blueprint identity/version (#838 lineage) and one supplied target/rubric-dimension set (#837 meaning by reference). Every observation, hypothesis, and option binds only to supplied targets; nothing may invent remediation content outside them. Intake is admitted only with an explicit teacher-reviewed state; anything not reviewed is rejected. Class-level scope is structural: any observation scoped to a learner or a small subgroup is rejected as a privacy violation. Raw responses, identifiers, scans, handwriting, transcripts, and unbounded notes are never admitted.

The standard consumes #837 target/claim/evidence/method meaning and #838 blueprint identity by reference. It creates no second target, claim, blueprint, grading, readiness, or lifecycle model.

## Evidence, Inference, and Option Separation
The analysis record carries three sections with hard rules between them:

- observed evidence: class-level observations with an evidence kind (direct, context, partial, uncertain) and an evidence strength (strong, moderate, weak, insufficient). Observed evidence is never restated as a conclusion.
- inference hypotheses: labeled misconception, prerequisite-gap, or strategy-opportunity hypotheses. A hypothesis may never claim stronger evidence than its weakest supporting observation, uncertain evidence cannot carry stronger than insufficient strength, and every hypothesis must state its limitations. Hypotheses are advisory working interpretations, not learner judgments; class-level scope is the only permitted scope.
- instructional options: bounded options (reteach-bounded, modeling-revisit, practice-redesign, materials-revision, pacing-adjustment, sequence-change, manual-review). Each option binds supplied targets, names its supporting hypotheses, and may never rest on an insufficient-strength hypothesis. Consequential options always require an explicit teacher decision.

Teacher decisions are stored separately by the teacher-facing surface (per the teacher-decision-studio standard) and are never written or overwritten by the analysis record.

## Deterministic Dispositions
- `valid` with `sufficient-evidence` classification: evidence supports bounded next-instruction options; continuation routes to the existing owner matching the option kinds (Unit Alignment, Teacher Modeling Coach, or Instructional Materials Coach; ChatGPT Orchestrator owns cross-owner routing).
- `manual_review_required` with `insufficient-evidence` classification: missing, conflicting, or insufficient evidence, privacy-ineligible intake, or weak/uncertain evidence that cannot support confident options. The record states the unresolved uncertainties and routes to hold/manual review; no instructional options are emitted.
- `invalid`: structural violations — unreviewed intake, non-class scope, unbound targets, strength upgrades, missing limitations, options on insufficient hypotheses, oversized intake, or unknown fields.

## Authority Boundary
The analysis record is evidence only. Analysis, execution, grading, readiness, production, publication, and external-write authority are permanently false. The record recommends; it never executes, never grades, and never activates production.

## Non-Goals
No learner or small-subgroup diagnosis or placement, no new Assessment agent or router, no raw student data ingestion, no gradebook or readiness writes, no production activation, and no external (Drive/Notion) writes.

## Version
0.1.0
