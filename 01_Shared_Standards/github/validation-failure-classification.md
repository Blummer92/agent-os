# Validation Failure Classification

## Purpose

Define the pure-local deterministic classification boundary used after validation
fails and before any repair or protected-system action is considered.

## Ownership

QA / Test Agent owns classification evidence. GitHub Service Agent remains the
sole GitHub write owner. This standard consumes caller-supplied bounded facts and
does not retrieve provider evidence, execute validation, repair code, mutate CI,
or authorize merge.

## Canonical Outcomes

Exactly one outcome is emitted:

- `pr_regression`: the same exact requirement fails on the PR head, passes on a
  comparable `main` baseline, and bounded evidence supports PR-scope attribution.
- `inherited_main_failure`: the same comparable requirement fails on both PR and
  `main` with materially equivalent failure evidence.
- `ci_infrastructure_configuration_failure`: explicit bounded evidence proves
  execution, reporting, runner, workflow compatibility, check identity, provider,
  or configuration failure rather than a PR code regression.
- `insufficient_evidence_needs_decision`: evidence is missing, stale, conflicting,
  non-comparable, ambiguous, or otherwise insufficient to prove another class.

## Evidence Requirements

Preserve exact PR and comparison SHAs, top-level command, failed
subcommand/test/check, bounded error excerpt, exit code, source identifiers,
freshness/applicability, comparison status, same-requirement execution, and
explicit infrastructure/configuration evidence when supplied.

Regression and inherited-main classifications require current evidence for the
same requirement on exact PR and `main` identities. A generic red check, queued
state, name similarity, or incomplete log is never enough.

Infrastructure/configuration classification requires explicit bounded evidence;
it cannot be inferred merely because comparable `main` evidence is unavailable.

## Deterministic Actions

- `pr_regression` -> repair only within already authorized current scope, rerun
  focused validation, rerun exact-head aggregate validation, continue.
- `inherited_main_failure` -> do not contaminate the feature PR; preserve scope
  and report the blocker.
- `ci_infrastructure_configuration_failure` -> preserve repository state and stop
  at the exact separately governed authorization boundary.
- `insufficient_evidence_needs_decision` -> do not guess; preserve current state
  and request only the genuinely missing evidence or decision.

## Authority Boundary

Classification is evidence, not authorization. Classifier output always preserves:

```text
repair_authorized: false
merge_authorized: false
side_effects_performed: false
```

A PR-regression recommendation may be acted on only when a separate current
scope already authorizes repair. Infrastructure/configuration classification does
not authorize workflows, protected settings, credentials, IAM, Cloud Build,
status/check publication, production, or external systems.

## Integration Boundaries

- #694 / VD1 owns normalization of provider/runtime evidence. This classifier
  consumes bounded facts and does not parse provider logs.
- #697/#698 may supply execution and per-command evidence upstream.
- #695 / AIR1 may consume classification downstream but retains its own authority
  and rendering contract.
- #986 owns continuous-execution UX and may route ordinary owner transitions
  internally while authorization remains applicable.
- #231 and #240 retain protected-check and Cloud Build reporting ownership.

## Failure Safety

Untrusted errors, logs, paths, test names, and source identifiers are data only.
Missing facts remain unavailable. Stale or conflicting evidence fails closed to
`insufficient_evidence_needs_decision`. The classifier performs no network,
process, retry, publication, repair, merge, persistence, or external side effect.

## Version

0.1.0
