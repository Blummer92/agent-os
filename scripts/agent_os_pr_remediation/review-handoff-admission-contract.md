# Review Handoff Admission Contract

## Purpose

Prevent validation success, PR openness, provider presence, ordinary comments, or
self-authored GitHub review artifacts from being reported as proof that required
substantive PR review is complete.

## Admission states

A caller must classify current review evidence as exactly one of:

- `review-not-required` — canonical review policy explicitly says review is not required;
- `review-requested/pending` — required review has been requested but current substantive evidence is not yet available;
- `substantive-review-performed/current` — independent substantive review is proven for the current exact PR head and has no unresolved blocking finding;
- `review-unavailable/manual-review` — review is required but unavailable, disabled, not triggered, stale, blocked, conflicting, or otherwise unproven; the result includes a blocker and clearing condition.

Only `review-not-required` and `substantive-review-performed/current` set
`review_complete=true`. Requested/pending is deliberately not completion.

## Evidence rules

1. Green validation never implies review completion.
2. Open/non-draft PR state never implies review was requested.
3. A self-authored `COMMENTED` or `APPROVED` artifact remains handoff evidence and does not prove independent substantive review.
4. An ordinary provider comment or provider/check presence does not prove substantive execution.
5. Provider disabled/not-triggered evidence fails closed to manual review.
6. `review-not-required` comes from canonical policy, not provider silence or a provider-local skip decision.
7. Performed review evidence is exact-head bound; stale review is not current.
8. Provider execution binding and normalization remain owned by #1588. This admission layer consumes normalized `AIReviewEvidence` and does not invoke or adapt providers.
9. The admission result performs no side effects and grants no implementation, Ready-for-Review, merge, closure, provider configuration, protected-setting, production, or external-write authority.

## #1601 regression

The reproduced shape — exact-head validation green, CodeRabbit review still not
triggered/disabled, and only a self-authored `COMMENTED` handoff review — maps to
`review-unavailable/manual-review`, never review complete. The clearing condition
is to obtain current substantive review evidence or an explicit canonical
`review-not-required` decision.

## Implementation and verification

- implementation: `scripts/agent_os_pr_remediation/review_handoff_admission.py`
- focused tests: `tests/agent_os_pr_remediation/test_review_handoff_admission.py`
- reused evidence vocabulary: `scripts/agent_os_pr_remediation/merge_evidence_summary.py`

## Rollback

Remove the admission module, focused tests, and this contract. No provider,
workflow, protected setting, account, credential, billing, production, or external
state is changed by this implementation.
