# LP Pacing Handoff Adaptation And Route-Back
This standard defines the ordered adaptation hierarchy, protected instructional functions, route-back targets, mixed-class coordination, destination boundary, and retired vocabulary for the LP pacing handoff.
It is the second normative half of `lp-pacing-handoff-contract.md`; `04_Registry/lp-pacing-handoff-contract.yaml` owns the serialized ordering and stable references.
Adaptation is considered in the stated order; a later step is never taken to avoid an earlier one, and no step lowers the objective, the success criteria, or accessibility.
### compression-protected-functions
Modeling, accessibility support, safety, formative evidence, actionable feedback, correction, and revision are never the first reductions and are never removed to fit a period.
### compression-operational-friction
Remove avoidable operational friction first: setup, device handling, movement, queues, transfer, upload, and cleanup.
### compression-extraneous-material
Remove extraneous material, unclear directions, and content that does not serve the objective.
### compression-consolidate-transitions
Consolidate transitions and duplicate prompts without removing an instructional function.
### compression-reduce-repetitions
Reduce examples or repetitions only while the instructional function they serve is preserved.
### compression-change-evidence-format
Change the evidence format only while the objective, success criteria, and accessibility are preserved.
### compression-defer-optional-polish
Defer optional polish, showcase, or enrichment work.
### compression-continuation-or-split
Define an explicit continuation or split plan with a named split point rather than silently truncating the lesson.
### compression-route-to-curriculum-owner
Route to the curriculum owner when the objective or the assessment contract itself must change.
### function-preservation-record
The handoff records preserved functions, compressed instances, changed formats, deferred functions, and the split plan so a later owner can see exactly what changed.
### route-back-unit-alignment
Route back to Unit Alignment when evidence sufficiency, objective alignment, privacy eligibility, comparability, or pacing feasibility is unresolved.
### route-back-teacher-modeling
Route back to Teacher Modeling when the sequence or a required instructional function is incomplete.
### route-back-instructional-materials
Route back to Instructional Materials when material-induced or artifact-format load remains the blocker.
### route-back-is-not-failure
Route-back is a routing recommendation under LP12 vocabulary; it does not revoke a gate, lower a success criterion, or record a negative judgment about a teacher or a class.
### pathway-reference-lp5
Mixed-class routes reference LP5 compacting and advanced-pathway policy; this contract never restates eligibility, replacement, or re-entry rules.
### pathway-carried-references
The handoff may carry supported, core, and compacted advanced route references, route-specific timing ranges, exact work removed or reduced, advanced replacement references, teacher checkpoints, temporary grouping, re-entry, and common synthesis.
### pathway-no-placement
No result determines mastery, assigns a learner to a route, creates a permanent label, or infers a protected characteristic; `automatic_placement_authorized` and `student_classification_authorized` are fixed false.
### boundary-notion-lp7
LP7 owns every destination field, relation, view, form, permission, retention, and display decision; this contract contains no workspace identifier, property name, or destination-specific readiness policy.
### boundary-implementation
A conforming runtime evaluator is authorized separately under LP4; this standard defines meaning and shape only and grants no implementation, model, or classroom-data permission.
### retired-pass-blocked-compatible
`PASS/BLOCKED-compatible` is retired as a pacing result because it implies the pacing assessment is itself a gate outcome.
### retired-pacing-derived-ready-for-modeling
`ready-for-modeling` derived from pacing is retired; the modeling-handoff gate has one owner and is evaluated independently.
### retired-historical-fits-mapping
Automatic mapping from historical `fits` or `feasible` labels to a handoff gate is retired; such literals stay display-only history under the LP authority and state registry.
### retired-inherited-gate-default
Any default that copies the previous owner's state when the current owner has not evaluated is retired.
### retired-combined-readiness-status
A combined curriculum-readiness value or a single dominant LP status is retired; owner states are always shown separately.
### retired-opaque-similarity-score
One opaque worksheet or assignment similarity percentage is retired as evidence for pacing, comparability, or mastery.
