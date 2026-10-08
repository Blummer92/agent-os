# Confirmed Bug Evidence Capture

## Purpose

Preserve concrete bug evidence in canonical GitHub state without requiring a second ritual command solely to log evidence the repository owner already supplied.

## Contract

When a user supplies concrete, actionable Agent OS bug evidence:

1. search live GitHub for the canonical owning issue;
2. if exactly one issue clearly owns the defect, append only materially new bounded evidence there;
3. before concluding that no suitable owner exists, complete a bounded candidate-owner review over the live open population/search evidence and inspect plausible candidates deeply enough to compare objective, causal seam/root cause, acceptance criteria, and ownership/scope boundary; exact-title, one-label, or semantic similarity alone is never sufficient;
4. if one inspected current-open owner matches, route the recurrence/duplicate there; if ownership is ambiguous, candidate enumeration is incomplete, or the evidence dimensions above are missing, investigate read-only and do not guess;
5. create one focused bug/investigation issue only after the pre-create admission establishes a genuinely distinct causal mechanism; the admission requires a per-candidate comparison outcome (distinct/recurrence/duplicate/partial-overlap/unresolved), and distinct creation is admitted only when every inspected open candidate carries outcome=distinct;
6. report the exact issue destination after capture.

Observed reproduction evidence must remain distinguishable from diagnosis or inference. Preserve exact issue/PR/SHA/check identities when available from canonical GitHub reads.

## Idempotency

Equivalent evidence already present on the canonical issue must not be posted again. Repeated mention of the same reproduction in one workflow must converge to zero duplicate writes.

## Authorization boundary

Evidence capture is not implementation authority. It must not mark readiness, create an implementation branch or PR, merge, close, modify workflows/protected settings, change credentials/IAM, mutate production, or write to external classroom systems.

## Regression fixture

The #1646 reproduction is canonical: once the user reported that the implementation PR was not visible and the defect was confirmed, the evidence should have been persisted without requiring a second `log it` instruction.

## Version

0.2.1


## Changelog

- 0.2.1 binds the #2660 pre-create admission to per-candidate comparison outcomes: NEW_DISTINCT_BUG is admitted only when every inspected open candidate is recorded as distinct; RECURRENCE_EXISTING_OWNER and DUPLICATE_EXISTING_OWNER require the inspected-open canonical candidate's outcome to agree; FOCUSED_SUCCESSOR additionally requires no contradicting open-candidate outcome; any unresolved outcome fails closed to manual review.
- 0.2.0 hardens #2660 pre-create admission: candidate-owner enumeration and objective/causal-seam/acceptance/boundary comparison precede distinct issue creation; incomplete or ambiguous evidence fails closed without adding a second tracker or classifier.
