# Confirmed Bug Evidence Capture

## Purpose

Preserve concrete bug evidence in canonical GitHub state without requiring a second ritual command solely to log evidence the repository owner already supplied.

## Contract

When a user supplies concrete, actionable Agent OS bug evidence:

1. search live GitHub for the canonical owning issue;
2. if exactly one issue clearly owns the defect, append only materially new bounded evidence there;
3. if no suitable owner exists, create one focused bug/investigation issue;
4. if ownership is ambiguous, investigate read-only and do not guess;
5. report the exact issue destination after capture.

Observed reproduction evidence must remain distinguishable from diagnosis or inference. Preserve exact issue/PR/SHA/check identities when available from canonical GitHub reads.

## Idempotency

Equivalent evidence already present on the canonical issue must not be posted again. Repeated mention of the same reproduction in one workflow must converge to zero duplicate writes.

## Authorization boundary

Evidence capture is not implementation authority. It must not mark readiness, create an implementation branch or PR, merge, close, modify workflows/protected settings, change credentials/IAM, mutate production, or write to external classroom systems.

## Regression fixture

The #1646 reproduction is canonical: once the user reported that the implementation PR was not visible and the defect was confirmed, the evidence should have been persisted without requiring a second `log it` instruction.

## Version

0.1.0
