# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation, risk-triggered review selection, bounded review evidence, deterministic Review Attack Plans, truthful review/merge-evidence summaries, and CI evidence recovery. It evaluates supplied evidence only and performs no provider invocation, source edit, validation execution, merge, or external write.

## Risk-triggered code review

`scripts/agent_os_pr_remediation/review_evidence.py` owns CRH1 review depth and the bounded `ReviewEvidencePacket`. Review depths remain `no-ai-review-required`, `normal-review-required`, `adversarial-review-required`, and `manual-decision-required`. `review_invalidation_scope(...)` remains the proportional currentness owner; CRH5 does not create another risk classifier, evidence packet, test selector, provenance model, or currentness engine.

## Deterministic Review Attack Plans

`scripts/agent_os_pr_remediation/review_attack_plan.py` consumes an existing CRH1 `ReviewEvidencePacket` and projects adversarial risk classes into a finite provider-neutral set of defect-class attacks. Normal/no-AI review is not inflated into a generic adversarial checklist.

Attack families are bounded to parser/resolver/selector, authorization/permissions/security, state/retry/reconciliation, persistence/migration, concurrency/lease/fencing, workflow/CI validation authority, cross-system/external API semantics, and architecture/ownership/interfaces. Closely related CRH1 risk classes map into these families; unknown, ambiguous, conflicting, or unmapped risk evidence fails closed to manual review rather than silently reducing the plan.

Every `RequiredAttack` carries an `attack_family`, invariant, exact `reviewed_head_sha`, CRH1-supplied affected-surface references, bounded evidence requirements, and finite reason codes. `attack_id` is content-addressed from those canonical semantics, so it is independent of provider prompt wording, model name, output order, or prose formatting. The plan itself has a deterministic `plan_id` and preserves CRH1 activated references.

The historical defect-oriented attacks include parser first-match ambiguity, authorization evidence mistaken for authority, workflow transport-success versus semantic-success (#1564), wrong exact-head SHA, stale/skipped/cancelled/duplicate/conflicting validation evidence, and state-machine partial-effect/retry/idempotency failures. These are review obligations, not one-model-call-per-attack requirements: one substantive review may cover several attack IDs while downstream #1585 findings and #1586 coverage evidence reference each stable ID independently.

All plan authority fields remain false. A Review Attack Plan grants no execution, readiness, merge, closure, protected-setting, production, or external-write authority and performs no side effects. Provider integration/execution remains outside this contract.

## Truthful review and merge evidence

`scripts/agent_os_pr_remediation/merge_evidence_summary.py` projects already-owned validation, acceptance, and review evidence into one bounded provider-neutral summary for the current PR lineage. Source head, base, synthetic merge SHA, merge commit, tested SHAs, reviewed SHA, and metadata fingerprint remain distinct identities; stale evidence cannot silently satisfy exact-head claims.

## PR Review Remediation CLI

```bash
python -m scripts.agent_os_pr_remediation.cli --input tests/fixtures/agent_os_pr_remediation/e2e.json --format json
```

The CLI remains non-authorizing and composes existing remediation evidence only.

## CI Evidence Recovery Contract

`scripts/agent_os_pr_remediation/ci_evidence_recovery.py` plans bounded recovery of actionable GitHub Actions failure evidence without assuming `gh` or Cloud Shell. It performs no network, CLI, retry, repository, or external-system operation itself. Exact head/run identity, bounded excerpts, fail-closed reason codes, and the separation between attribution evidence and repair authority remain unchanged.

## GitHub Write Handoff

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, workflow change, or external operation remains owned by the appropriate Agent OS owner. Review planning itself grants none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_review_evidence.py tests/agent_os_pr_remediation/test_review_attack_plan.py
python -m pytest tests/agent_os_pr_remediation/test_merge_evidence_summary.py
python -m pytest tests/agent_os_pr_remediation/test_ci_evidence_recovery.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
