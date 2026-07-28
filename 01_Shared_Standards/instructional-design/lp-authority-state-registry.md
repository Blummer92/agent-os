# LP Authority And State Registry
This standard defines canonical LP authority and state vocabulary for lesson-pacing, alignment, pathway, readiness, and lifecycle records.
`04_Registry/lp-authority-state-registry.yaml` owns serialized values, versions, bounds, ordering, and stable references; this file owns normative meaning.
There is no canonical generic top-level `status`, `ready`, `approved`, or `authorized` field. Assessment, gate, routing, readiness, teacher approval, classroom readiness, production, publication or sharing, execution, and external-write meanings are distinct.
No valid record grants teacher approval, classroom-ready status, production, publication, sharing, execution, external-write, grading, learner-placement, or external-system mutation authority.
Unknown, future, mixed, retired, malformed, contradictory, or incompatible versions fail closed to bounded manual review.
Missing gate evidence resolves only to `NOT_EVALUATED`; pacing feasibility may coexist with an alignment gate of `BLOCKED`; `CONDITIONALLY_CLEARED` is unsupported.
Legacy aliases remain display-only historical evidence, preserve original literals, never advance authority, and require migration review.
Non-authority evidence is immutable evidence only and never advances a gate or permission.
### advisory-feasible
Evidence supports feasibility for the assessed scope only; it does not advance a canonical gate.
### advisory-feasible-with-adjustments
Evidence supports feasibility only with stated adjustments; it does not advance a canonical gate.
### advisory-not-feasible
Evidence does not support feasibility for the assessed scope and does not itself mutate a gate.
### advisory-insufficient-evidence
Evidence is insufficient for a bounded advisory conclusion; absence never becomes a positive signal.
### route-continue
Recommend continuing to the next governed review step; this is not authorization.
### route-revise
Recommend revising the represented proposal before another governed review.
### route-hold
Recommend holding the represented proposal without advancing a gate.
### route-manual-review
Route the represented proposal to a named human owner for bounded review.
### lifecycle-draft
The record is being prepared and has no deployment authority.
### lifecycle-shadow
The record may be observed in shadow mode without changing production or external systems.
### lifecycle-active
The record is active for its declared scope but grants no execution, production, publication, or external-write authority.
### lifecycle-retired
The record is retired and cannot serve as current execution authority.
### gate-not-evaluated
The gate lacks required evaluation evidence and resolves to `NOT_EVALUATED`, never `CLEARED`.
### gate-blocked
The gate has unresolved blockers; independent advisory feasibility may still be recorded.
### gate-cleared
The exact gate is cleared only for the exact revision and grants no teacher, classroom, production, publication, execution, external-write, grading, placement, or mutation authority.
### gate-revoked
The revision is revoked and terminal; reconsideration requires a new record with a higher positive `record_revision` under separately governed logic.
### compatibility-compatible
The supplied record is compatible with contract version 1.
### compatibility-migration-required
The record can be understood only after an explicit reviewed migration.
### compatibility-unsupported
The record uses an unsupported contract or value.
### compatibility-conflicting
The evidence contains contradictory identities, versions, meanings, or authority claims.
### compatibility-manual-review-required
Compatibility cannot be resolved deterministically from bounded evidence.
### legacy-fits
Preserve literal `fits` as display-only history and route it for migration review; never infer a gate.
### legacy-ready
Preserve literal `ready` as display-only history and route it for migration review; never infer a gate.
### legacy-valid
Preserve literal `valid` as display-only history and route it for migration review; never infer a gate.
### legacy-approved
Preserve literal `approved` as display-only history and route it for migration review; never infer a gate.
### legacy-authorized
Preserve literal `authorized` as display-only history and route it for migration review; never infer a gate.
### legacy-unscoped-status
Preserve an unscoped historical `status` literal as display-only evidence and route it for migration review; never infer a gate.
### evidence-confidence
A bounded confidence value is evidence only.
### evidence-review-recommendation
A review recommendation is evidence only.
### evidence-blocker-or-reason-code
A blocker or reason code is evidence only.
### evidence-stale-finding
A stale finding is evidence only.
### evidence-compatibility-result
A compatibility result is evidence only.
### evidence-migration-recommendation
A migration recommendation is evidence only.
### evidence-notion-view-membership
Notion view membership is evidence only and never readiness or authority.
### evidence-drive-file-existence
Observed Drive file existence is evidence only and never quality, approval, publication, or execution authority.
### evidence-validator-result
A validator result is evidence only.
### evidence-api-success
An API success response is evidence only and never policy or authority.
### bound-reason-codes
Reason-code collections contain at most 16 entries.
### bound-source-references
Source-reference collections contain at most 20 entries.
### bound-unresolved-uncertainties
Unresolved-uncertainty collections contain at most 12 entries.
### bound-explanations
Human-readable explanation collections contain at most 12 entries.
`contract_version` is the public compatibility identifier; the first ratified record is `1.0` with positive `record_revision: 1`, and canonical serialization follows YAML key and record ordering with one stable lowercase kebab-case reference per value.
