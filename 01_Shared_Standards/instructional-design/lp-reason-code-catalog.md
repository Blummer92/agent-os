# LP Reason Code Catalog
This standard defines the meaning, ownership, and usage rules for LP-specific semantic reason codes.
`04_Registry/lp-reason-code-catalog.yaml` owns the finite `lp-*` catalog, per-code records, family producer/consumer maps, and stable references; this file owns normative meaning.
LP9 owns version, identity, namespace, unknown-version behavior, and compatibility; LP12 owns authority and gate states; CW5A owns generic parsing, bounds, serialization, shared result models, and import policy. All three are consumed by reference.
A reason explains a result. It is never a result classification, an authority state, an approval, a readiness value, or a permission.
### family-pacing-feasibility
Causes that prevent or qualify a bounded pacing conclusion for the assessed scope, including time budget, available instruction time, required function loss, operational time, split, continuation, and uncertainty.
### family-evidence-comparability
Causes that limit whether supplied lesson-run evidence is comparable and usable, including run count, objective match, work mode, interruption, time conflicts, learning-quality gaps, support and revision gaps, and prior contradictions.
### family-demand-diagnosis
Causes identifying which demand dimension dominates observed or estimated time, drawn from the six separated dimensions in the LP pacing handoff contract.
### family-mixed-class-pathways
Causes that block or qualify a compacting, acceleration, or enrichment route brief under LP5, including missing objective-specific evidence, speed-only eligibility, unidentified mastered work, volume mislabelled as compacting, absent advanced dimensions, unrelated extensions, fixed grouping, unresolved accessibility or re-entry, and attempted automatic placement.
### family-observation-quality
Causes that make an observation record unusable or reduce its measurement quality under LP14, including missing checkpoints, late recording, observer disagreement, category overlap, contradictory aggregates, burden limits, and low observation confidence.
### family-privacy-and-disclosure
Causes that make a record ineligible for use or disclosure under LP10, including direct identifiers, indirect identification risk, small-cell suppression, linkage risk, purpose limitation, expired retention, unapproved destinations, and narrative-note disclosure risk.
### family-calibration-and-lifecycle
Causes that limit advisory use under LP11, including shadow-mode restriction, insufficient evidence or context diversity, interval undercoverage, underestimation risk, drift, elevated teacher disagreement, failed guardrails, blocked promotion, and required suspension or recalibration.
### naming-lowercase-namespace
Every code is a lowercase ASCII identifier in the `lp-` namespace defined by LP9.
### naming-one-cause-one-code
One code represents exactly one stable domain cause; one code is never reused for materially different causes.
### naming-no-synonyms
No two active codes describe the same cause; a superseded name is deprecated rather than kept alongside its replacement.
### naming-no-mutable-detail
A code encodes no severity, colour, icon, owner display name, timestamp, count, threshold, or other mutable implementation detail.
### naming-details-are-separate
Human-readable occurrence details stay separate, bounded, and sanitized under CW5A; they are never encoded into the identifier.
### record-required-fields
Every retained code declares its family, semantic owner, normative reference, summary, trigger, required evidence, allowed result families, manual-review requirement, privacy sensitivity, prohibited implications, deprecation state, and replacement code.
### ownership-single-semantic-owner
Every code has exactly one semantic owner: Unit Alignment Agent for pacing, comparability, demand, and pathway meaning; QA / Test Agent for observation-quality and calibration findings; Integration Manager for LP privacy-routing semantics and source-of-truth coordination. Teacher Modeling Coach owns a code only where the responsibility matrix assigns it distinct lesson-flow interpretation, and no current code does.
### ownership-reference-not-redefine
Any contract may emit or consume a code by reference; no contract other than its semantic owner may redefine, narrow, or extend its meaning.
### ownership-producers-and-consumers
Each family declares its authorized producers and consumers; an unlisted producer emitting a code is a contract violation, not a new meaning.
### result-multiple-reasons
One result may carry multiple reasons; ordering and deduplication are performed by the shared CW5A mechanics and carry no meaning of their own.
### result-reason-is-not-classification
A reason explains a result classification but never replaces or overrides it.
### result-reason-is-not-gate
Reasons do not map to canonical gates; advisory success or failure never alters readiness, approval, grading, placement, production, or an external write.
### result-manual-review-is-evidence
`manual_review_required` records that a named human owner must look; it grants no authority and satisfies no gate.
### result-fail-closed-routing
A privacy, calibration, or observation-quality finding may force fail-closed routing without authorizing any downstream action.
### diagnosis-never-labels-a-learner
A code describes the task, the context, and the supplied evidence. No code labels a learner as slow, low, gifted, advanced, incapable, or equivalent, and none encodes or infers a protected characteristic.
### excluded-generic-mechanics
This catalog defines no independent reason for malformed JSON-compatible values, unknown generic fields, recursive size or depth bounds, generic identifier syntax, contract-version mismatch, unsupported future versions, canonical serialization failure, generic authority contradiction, or forbidden imports and runtime side effects. LP results may surface those existing reasons by reference where the shared contract permits.
### excluded-severity-and-presentation
This catalog defines no universal severity scale, colour system, ranking, score, or free-form narrative taxonomy.
### deprecation-reuse-lp9
Deprecation and replacement follow LP9 compatibility policy; a deprecated code keeps its original meaning and is never silently reinterpreted.
### deprecation-without-replacement
A code deprecated because it was too generic to carry one stable cause has no replacement; callers must emit the specific code that actually applies.
