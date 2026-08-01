# LP Pacing Handoff Contract
This standard defines the owner boundaries, evidence intake, packet shape, and authority separation for using evidence-calibrated lesson pacing inside the existing curriculum pipeline.
`04_Registry/lp-pacing-handoff-contract.yaml` owns serialized field names, ordering, bounds, and stable references; this file and `lp-pacing-handoff-adaptation.md` own normative meaning.
LP1, LP2, LP5, LP9, LP10, LP11, LP12, and LP14 are consumed by reference; this contract never restates their policy.
`01_Shared_Standards/instructional-design/lp-authority-state-registry.md` owns advisory, routing, lifecycle, gate, compatibility, and non-authority vocabulary.
No conforming packet authorizes execution, artifacts, readiness, grading, learner placement, route assignment, production, publication, or an external write.
No new Lesson Pacing, Assessment, Student Evidence, or OCR agent role exists; every responsibility below belongs to an already-registered agent.
### owner-unit-alignment
Unit Alignment Agent owns evidence sufficiency, the supplied time budget, the advisory pacing outcome, the routing recommendation, the six-dimension diagnosis, and the non-authorizing handoff candidate.
### owner-unit-alignment-excluded
Unit Alignment does not own recognition of raw work, the minute-by-minute lesson flow, objective or success-criteria changes made to fit time, grading, readiness, route assignment, permanent learner profiles, or student-facing artifacts.
### owner-teacher-modeling
Teacher Modeling Coach owns the realistic lesson sequence, the modeling/rehearsal/application/check/feedback/revision/retrieval/synthesis structure, LP1-compliant adaptation choices, its own modeling-handoff gate, and route-back when the learning cycle cannot be represented responsibly.
### owner-instructional-materials
Instructional Materials Coach owns fitting artifacts to the approved lesson flow, reducing extraneous language and avoidable production complexity, preserving accessibility and safety, and reporting when an artifact cannot fit without changing the instructional contract.
### owner-instructional-materials-excluded
Instructional Materials does not own pacing feasibility, evidence validity, extraction confidence, alignment or modeling gates, success-criteria level, learner assignment, or readiness.
### owner-qa-test
QA / Test Agent owns later synthetic validation for schema conformance, hostile inputs, sparse and conflicting evidence, owner-state independence, route-back behavior, and non-authority guarantees.
### intake-teacher-summary
A teacher-entered class-level evidence summary is a first-class intake path and never requires scanning, OCR, or an installed runtime.
### intake-eia1-normalized
Scan-derived evidence enters only as a normalized EIA1 `instructional_evidence_intake` summary; the evidence chain is preserved rather than flattened into one confidence value or one direct-evidence flag.
### intake-admission-checks
An EIA1 summary is admitted only with a compatible contract version, a current runtime fingerprint when extraction was used, an eligible privacy state, and an explicit teacher-review state.
### intake-rejected-summary
`not-reviewed`, stale, suspended, privacy-blocked, wrong-runtime, and incompatible summaries are rejected; a blank review state is never treated as accepted.
### intake-disposition-use
Direct evidence applies only to the named matched component, context evidence applies only to operational, tool, and routine estimates, and partial, not-comparable, and uncertain dimensions are excluded from stronger learning conclusions.
### intake-preserved-limits
`what_supported` and `what_remains_unmeasured` are carried into the packet so an unmeasured demand keeps its modeling requirement.
### intake-prohibited-operations
This contract never opens images or PDFs, invokes an OCR engine or model, retains raw worksheets, infers correctness from extraction confidence, or treats completion, speed, handwriting, topic words, or one similarity score as mastery.
### intake-independent-teacher-decision
The teacher's own pacing decision is recorded separately from any advisory recommendation and is never overwritten by it.
### intake-fallback-availability
Teacher-summary mode stays available whenever the extraction lane is absent, delayed, rejected, unavailable, suspended, too burdensome, or outside its validated envelope.
### packet-provider-neutral
The pacing packet names no workspace, database, property, file, vendor, or model; destination-specific representation belongs to LP7.
### packet-versioned-identity
Every packet carries `contract_version` and a positive `record_revision` under LP9 identity and compatibility policy.
### packet-bounded-evidence
The packet may reference an EIA1 summary but never embeds raw recognized responses, page images, student identifiers, handwriting samples, transcripts, or unbounded notes.
### packet-fail-closed-defaults
An unpopulated packet defaults to `insufficient-evidence`, `hold`, `low` confidence, `evidence_uncertainty: high`, and `manual_review_required: true`.
### packet-non-authority-flags
`report_only` is true and every `*_authorized` flag is false; these flags are immutable evidence and no consumer may raise them.
### authority-pacing-assessment
The pacing assessment is advisory evidence owned by Unit Alignment and is not a gate result.
### authority-alignment-gate
The alignment gate is owned by Unit Alignment and is evaluated independently of pacing feasibility.
### authority-modeling-handoff-gate
The modeling-handoff gate is owned by Teacher Modeling and is evaluated independently of the pacing assessment and the alignment gate.
### authority-production-authorization
Production authorization is owned by Production Control and is never derived from pacing, alignment, or modeling state.
### authority-independence
Pacing feasibility may coexist with a blocked alignment gate; `NOT_EVALUATED`, `BLOCKED`, and `NOT_AUTHORIZED` remain distinct and are never collapsed.
### authority-no-inheritance
A missing owner decision resolves only to `NOT_EVALUATED`; it is never copied from a prior gate, inferred from pacing, or defaulted from history.
### authority-reviewer-override
An owning human reviewer may reject an advisory recommendation without changing the recorded evidence.
### authority-routing-is-not-permission
`handoff_candidate` and `review_recommended` are routing recommendations only; no downstream owner may read `insufficient-evidence`, `manual-review`, `not-feasible`, stale evidence, privacy rejection, observation unusability, or EIA uncertainty as permission to proceed.
### diagnosis-instructional-demand
Novelty, interacting concepts and procedures, strategy selection, and prerequisite structure required by the task itself.
### diagnosis-learner-relative-familiarity
Temporary, task-specific prior opportunity and familiarity; never a durable learner trait, label, or ranking.
### diagnosis-language-and-representation-load
Vocabulary, implicit information, and load introduced by changing representations.
### diagnosis-material-induced-load
Load caused by unclear, redundant, inaccessible, fragmented, or overburdened materials rather than by the objective.
### diagnosis-operational-load
Setup, devices, equipment, movement, gates, queues, transfer, upload, and cleanup time.
### diagnosis-evidence-uncertainty
Sparse, stale, conflicting, privacy-ineligible, observation-unusable, non-comparable, or extraction-uncertain evidence.
### diagnosis-separation
The six dimensions are reported separately; they are never summed, averaged, ranked, or collapsed into one difficulty label for a task, class, or learner.
