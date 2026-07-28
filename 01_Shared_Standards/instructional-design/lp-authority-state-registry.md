# LP Authority And State Registry

## Purpose

This standard defines the canonical LP authority and state vocabulary used by
lesson-pacing, alignment, pathway, readiness, and lifecycle records. It keeps
advisory assessments, canonical gates, routing recommendations, deployment
lifecycle states, and compatibility decisions in separate namespaces.

The machine-readable registry is
`04_Registry/lp-authority-state-registry.yaml`. This Markdown file owns
normative meaning; the YAML file owns serialized values, versions, bounds, and
stable references.

## Authority boundary

There is no canonical generic top-level `status`, `ready`, `approved`, or
`authorized` field. Assessment, gate, routing, readiness, teacher approval,
classroom readiness, production, publication or sharing, execution, and
external-write meanings are not interchangeable.

A valid assessment or registry record never grants teacher approval,
classroom-ready status, production authorization, publication or sharing
authorization, execution authorization, external-write authorization, grading
authority, learner-placement authority, or permission to mutate Notion, Drive,
Sheets, readiness records, classroom artifacts, or any external system.

Unknown, future, mixed, retired, malformed, contradictory, and incompatible
versions fail closed and require bounded manual review.

## Advisory assessment outcomes

### advisory-feasible

The supplied evidence supports feasibility for the assessed scope. This is
advisory evidence only and does not advance a canonical gate.

### advisory-feasible-with-adjustments

The supplied evidence supports feasibility only with stated adjustments. This
is advisory evidence only and does not advance a canonical gate.

### advisory-not-feasible

The supplied evidence does not support feasibility for the assessed scope.
This is advisory evidence only and does not itself mutate a canonical gate.

### advisory-insufficient-evidence

The supplied evidence is insufficient for a bounded advisory conclusion. A
missing assessment never becomes a positive authority signal.

## Canonical gate states

### gate-not-evaluated

The gate has not been evaluated with the required evidence. Missing gate
evidence resolves only to `NOT_EVALUATED`, never to `CLEARED`.

### gate-blocked

The gate has one or more unresolved blockers. A pacing assessment may be
feasible while an alignment gate remains `BLOCKED`; these are independent
facts.

### gate-cleared

The exact represented gate has been cleared for the exact represented
revision. `CLEARED` grants no teacher approval, classroom-ready status,
production authorization, publication or sharing authorization, execution
authorization, external-write authorization, grading authority, learner
placement, or external mutation authority.

### gate-revoked

The represented revision is revoked. `REVOKED` is terminal for that revision.
A later reconsideration requires a new record with a higher positive
`record_revision` under separately governed logic.

`CONDITIONALLY_CLEARED` is unsupported and rejected in version 1.

## Routing recommendations

### route-continue

Continue to the next governed review step. This is a recommendation, not an
authorization.

### route-revise

Revise the represented proposal before another governed review.

### route-hold

Hold the represented proposal without advancing a gate.

### route-manual-review

Route the represented proposal to a named human owner for bounded review.

## Deployment lifecycle states

### lifecycle-draft

The record is being prepared and has no deployment authority.

### lifecycle-shadow

The record may be observed in shadow mode without changing production or
external systems.

### lifecycle-active

The record is the active governed version for its declared scope. Active does
not itself grant execution, production, publication, or external-write
authority.

### lifecycle-retired

The record is retired and cannot be used as current execution authority.

## Compatibility and migration states

### compatibility-compatible

The supplied record is compatible with contract version 1.

### compatibility-migration-required

The supplied record can be understood only after an explicit, reviewed
migration.

### compatibility-unsupported

The supplied record uses an unsupported contract or value.

### compatibility-conflicting

The supplied evidence contains contradictory identities, versions, meanings,
or authority claims.

### compatibility-manual-review-required

Compatibility cannot be resolved deterministically from the supplied bounded
evidence.

## Legacy display-only aliases

### legacy-fits

The original literal `fits` is display-only historical evidence. Preserve the
literal value and route it for migration review; never canonicalize it to a
gate.

### legacy-ready

The original literal `ready` is display-only historical evidence. Preserve the
literal value and route it for migration review; never canonicalize it to a
gate.

### legacy-valid

The original literal `valid` is display-only historical evidence. Preserve the
literal value and route it for migration review; never canonicalize it to a
gate.

### legacy-approved

The original literal `approved` is display-only historical evidence. Preserve
the literal value and route it for migration review; never canonicalize it to a
gate.

### legacy-authorized

The original literal `authorized` is display-only historical evidence.
Preserve the literal value and route it for migration review; never
canonicalize it to a gate.

### legacy-unscoped-status

An unscoped historical `status` value is display-only evidence. Preserve its
original literal and route it for migration review; never infer a gate.

## Immutable non-authority evidence

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

Membership in a Notion view is evidence only and never readiness or authority.

### evidence-drive-file-existence

Observed Drive file existence is evidence only and never quality, approval,
publication, or execution authority.

### evidence-validator-result

A validator result is evidence only.

### evidence-api-success

An API success response is evidence only and never policy or authority.

## Bounded collections

### bound-reason-codes

Reason-code collections contain at most 16 entries.

### bound-source-references

Source-reference collections contain at most 20 entries.

### bound-unresolved-uncertainties

Unresolved-uncertainty collections contain at most 12 entries.

### bound-explanations

Human-readable explanation collections contain at most 12 entries.

## Versioning and ordering

`contract_version` is the public compatibility identifier. The first ratified
record has `contract_version: "1.0"` and positive `record_revision: 1`.
Canonical serialization uses the key and record ordering stored in the YAML
registry. Each serialized value references exactly one stable lowercase
kebab-case normative identifier from this file.
