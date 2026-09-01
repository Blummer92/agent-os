# CI / Review Outcome to CKR5 Feedback

Issue: #1560.

`ci_review_learning.py` is the narrow producer seam from already-structured,
high-value CI/review outcomes into the existing CKR5 `FailureObservation`
contract.

It does not ingest unrestricted logs, execute CI, redefine review findings,
classify lesson identity/recurrence, publish Lessons Learned, or create authority.

## Admitted signals

A signal reaches CKR5 only when bounded current evidence already proves a
reusable rule and supplies reusable guidance plus canonical/evidence references.
Examples include escaped regressions, substantive review findings, repeated
repair failures, diagnosed flaky behavior with a durable guardrail, obsolete
validation behavior with reusable guidance, and property counterexamples that
also name a permanent deterministic regression.

## Noise controls

Ordinary passing CI, expected implementation-time test failures, and transient
environment failures are rejected before CKR5. A surviving mutation is test-suite
quality evidence only unless a reusable rule is independently proven. Oversized
structured fields are rejected rather than treated as raw-log input.

The producer also enforces CKR5's downstream text and collection budgets before
constructing `FailureObservation`. If combining future-use hints with affected
paths, or adding a permanent regression reference, would exceed CKR5's bounded
20-item contract, the outcome routes to manual review instead of raising during
observation construction or silently truncating evidence.

Stale or authority-conflicting evidence routes to manual review. Missing bounded
references or reusable guidance is insufficient evidence.

## Existing owners remain authoritative

- CKR5 owns reusable-learning qualification, lesson identity, recurrence, and
  authority-false publication proposals.
- CKR7 owns compatible enrichment/consolidation of existing lessons.
- CRH6/#1585 owns Evidence-Backed Review Finding semantics; this producer only
  consumes an already-substantive outcome.
- Deterministic GitHub tests remain canonical enforcement for regressions.
- #520 owns CI/build compute measurement.
- #1146 owns coding-context/retrieval measurement.

All producer result authority fields are fixed false. No Notion/GitHub write,
validation execution, readiness, merge, closure, production, or external-write
authority is created.
