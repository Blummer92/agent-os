# LP Pacing Handoff Illustrative Case And Fixture Index
This file is illustrative and non-normative. Normative meaning lives in `lp-pacing-handoff-contract.md` and `lp-pacing-handoff-adaptation.md`.
`04_Registry/lp-pacing-handoff-contract.yaml` lists the same case and fixture references; each anchor below is one stable reference.
The case is one worked example, not a universal schedule, minute formula, slide count, or confidence threshold.
Every fixture is synthetic. No real student work, name, identifier, scan, or classroom artifact appears here or in any conforming fixture.
### case-production-cycles-55-minute
One 55-minute Production Cycles lesson: 4 min setup and materials, 6 min one video move demonstration, 7 min partner planning, 4 min Ready-to-Shoot Gate queue, 10 min filming, 5 min transfer and upload, 8 min return watch-and-check, 4 min one corrective action or named next fix, 3 min exit evidence, 4 min cleanup and transitions. Instructional demand is moderate because the video move interacts with an unfamiliar framing decision. Material-induced load is low because the filming card is single-page and already accessible. Operational load is the dominant time driver because the gate queue, transfer, and cleanup together consume 13 minutes. Alternative participation includes storyboarding or directing rather than operating the camera, and the exit evidence accepts spoken, written, or recorded explanation. Prior worksheet evidence covers framing vocabulary recognition only, so it is partial evidence for filming performance and never direct evidence; modeling for the filming demand is preserved and the packet records `what_remains_unmeasured` as on-camera execution.
### fixture-pacing-feasible-alignment-blocked
Pacing is `feasible` while the alignment gate is `BLOCKED`; both states are recorded and neither changes the other.
### fixture-pacing-infeasible-alignment-cleared
Pacing is `not-feasible` while unit alignment is `CLEARED`; the cleared gate is not revoked and the pacing result is not upgraded.
### fixture-pacing-stale-modeling-current
The pacing assessment is stale while the modeling gate is current; staleness routes to review and does not invalidate the modeling owner's decision.
### fixture-conflicting-owner-outputs
Two owners report contradictory conclusions; both are preserved, neither is suppressed, and routing is `manual-review`.
### fixture-missing-modeling-gate-not-evaluated
No modeling decision exists; the gate resolves to `NOT_EVALUATED` and never to `CLEARED` or `BLOCKED`.
### fixture-reviewer-rejects-advisory
The owning human reviewer rejects the advisory recommendation; the recommendation remains recorded as evidence and the reviewer's decision governs.
### fixture-teacher-summary-without-ocr
A complete pacing assessment is produced from a teacher-entered class summary with no extraction lane present.
### fixture-eia-direct-evidence-bounded
EIA1 direct evidence is accepted only for the named matched component and does not extend to any other dimension.
### fixture-eia-partial-evidence-preserves-modeling
EIA1 partial evidence keeps the modeling requirement for the demand it did not measure.
### fixture-eia-context-evidence-operational-only
EIA1 context evidence changes operational and routine time estimates only.
### fixture-eia-uncertain-or-privacy-ineligible-excluded
Uncertain or privacy-ineligible EIA1 dimensions are excluded from the assessment and recorded as evidence uncertainty.
### fixture-extraction-confidence-without-correctness
High extraction confidence with no correctness evidence is ignored for pacing and never becomes mastery, quality, or approval.
### fixture-three-routes-common-synthesis
Supported, core, and compacted advanced routes carry independent timing ranges and one common synthesis; no learner is assigned.
### fixture-vocabulary-evidence-misused-for-performance
Direct vocabulary evidence offered as permission to shorten performance modeling is rejected and routed to manual review.
### fixture-context-evidence-misused-as-mastery
Context evidence offered as mastery is rejected; the disposition is preserved unchanged.
### fixture-accepted-but-not-inspected-review
A teacher-review state of accepted without inspection is treated as `not-reviewed` and the summary is rejected.
### fixture-stale-runtime-fingerprint
An EIA1 summary carrying a stale runtime fingerprint is rejected while the teacher-summary path stays available.
### fixture-summary-joined-to-learner-or-subgroup
An EIA1 summary joined to a learner or a small subgroup is rejected as a privacy and non-authority violation.
### fixture-usable-for-pacing-mapped-to-gate
A caller attempting to map `usable_for_pacing` to `ready-for-modeling` is rejected; the modeling gate stays `NOT_EVALUATED`.
### fixture-suspended-extraction-lane-fallback
With the extraction lane suspended, the teacher-summary path completes the same assessment without degradation.
