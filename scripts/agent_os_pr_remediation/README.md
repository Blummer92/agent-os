# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation, risk-triggered review selection, bounded review evidence, deterministic Review Attack Plans, evidence-backed review findings, truthful review/merge-evidence summaries, and CI evidence recovery. It evaluates supplied evidence only and performs no provider invocation, source edit, validation execution, merge, or external write.

## Risk-triggered code review

`scripts/agent_os_pr_remediation/review_evidence.py` owns CRH1 review depth and the bounded `ReviewEvidencePacket`. Review depths remain `no-ai-review-required`, `normal-review-required`, `adversarial-review-required`, and `manual-decision-required`. `review_invalidation_scope(...)` remains the proportional currentness owner; CRH5/CRH6 do not create another risk classifier, evidence packet, test selector, provenance model, or currentness engine.

## Deterministic Review Attack Plans

`scripts/agent_os_pr_remediation/review_attack_plan.py` consumes an existing CRH1 `ReviewEvidencePacket` and projects adversarial risk classes into a finite provider-neutral set of defect-class attacks. Normal/no-AI review is not inflated into a generic adversarial checklist.

Every `RequiredAttack` carries an invariant, exact reviewed head, affected surfaces, evidence requirements, reason codes, and stable content-addressed `attack_id`. Provider wording, model identity, and output order are not canonical attack semantics.

## Evidence-backed review findings

`scripts/agent_os_pr_remediation/review_findings.py` owns CRH6 substantive finding meaning and lifecycle. `EvidenceBackedReviewFinding` requires a threatened invariant, concrete failure scenario, exact affected path (plus optional symbol/contract reference), finite severity (`low`, `medium`, `high`, `critical`), bounded supporting evidence, a machine-readable clearing evidence class/identity, exact reviewed head, and the applicable CRH5 `attack_id` when one exists.

`ReviewSuggestion` is structurally separate and always non-blocking. Strong provider wording cannot promote a preference into the substantive unresolved-finding set.

Clearing evidence classes are bounded to regression test, exact-head validation, bounded invariant proof, current-diff absence, and explicitly superseded contract. A prose assertion such as `reviewer says fixed` cannot satisfy a clearing condition that names deterministic test or validation evidence. Finding identity is content-addressed from the defect claim and reviewed-head semantics; lifecycle updates preserve that identity.

`reevaluate_finding(...)` deliberately consumes CRH1-computed invalidated paths rather than deriving currentness itself. A head change affecting the finding path makes prior evidence stale; compatible resolved evidence can survive an unrelated head change only when CRH1 says the affected surface was not invalidated. CRH1 full-review invalidators therefore remain the broad-currentness authority.

Finding statuses are finite: `open`, `resolved-current`, `stale`, `superseded`, and `manual-review`. Severity and finding evidence create no release authority. All authority fields remain false.

## Truthful review and merge evidence

`scripts/agent_os_pr_remediation/merge_evidence_summary.py` projects already-owned validation, acceptance, and review evidence into one bounded provider-neutral summary for the current PR lineage. Source head, base, synthetic merge SHA, merge commit, tested SHAs, reviewed SHA, and metadata fingerprint remain distinct identities; stale evidence cannot silently satisfy exact-head claims.

## PR Review Remediation CLI

```bash
python -m scripts.agent_os_pr_remediation.cli --input tests/fixtures/agent_os_pr_remediation/e2e.json --format json
```

The CLI remains non-authorizing and composes existing remediation evidence only.

## CI Evidence Recovery Contract

`scripts/agent_os_pr_remediation/ci_evidence_recovery.py` plans bounded recovery of actionable GitHub Actions failure evidence without assuming `gh` or Cloud Shell. It performs no network, CLI, retry, repository, or external-system operation itself.

## GitHub Write Handoff

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, workflow change, or external operation remains owned by the appropriate Agent OS owner. Review planning/finding evidence grants none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_review_evidence.py tests/agent_os_pr_remediation/test_review_attack_plan.py tests/agent_os_pr_remediation/test_review_findings.py
python -m pytest tests/agent_os_pr_remediation/test_merge_evidence_summary.py
python -m pytest tests/agent_os_pr_remediation/test_ci_evidence_recovery.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
