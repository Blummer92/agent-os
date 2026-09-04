# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation, risk-triggered review selection, bounded review evidence, deterministic Review Attack Plans, evidence-backed substantive findings, per-attack review coverage/test adequacy, truthful review/merge-evidence summaries, and CI evidence recovery. It evaluates supplied evidence only and performs no provider invocation, source edit, validation execution, merge, or external write.

## Risk-triggered code review

`scripts/agent_os_pr_remediation/review_evidence.py` owns CRH1 review depth and the bounded `ReviewEvidencePacket`. Review depths remain `no-ai-review-required`, `normal-review-required`, `adversarial-review-required`, and `manual-decision-required`. `review_invalidation_scope(...)` remains the proportional currentness owner; downstream review contracts do not create another risk classifier, evidence packet, test selector, provenance model, or currentness engine.

## Deterministic Review Attack Plans

`scripts/agent_os_pr_remediation/review_attack_plan.py` consumes an existing CRH1 `ReviewEvidencePacket` and projects adversarial risk classes into a finite provider-neutral set of defect-class attacks. Normal/no-AI review is not inflated into a generic adversarial checklist.

Attack families are bounded to parser/resolver/selector, authorization/permissions/security, state/retry/reconciliation, persistence/migration, concurrency/lease/fencing, workflow/CI validation authority, cross-system/external API semantics, and architecture/ownership/interfaces. Every `RequiredAttack` carries a stable `attack_id`, exact reviewed head, affected surfaces, bounded evidence requirements, and reason codes. Unknown or conflicting risk evidence fails closed rather than silently reducing the plan.

## Evidence-backed substantive findings

`scripts/agent_os_pr_remediation/review_findings.py` owns CRH6 finding meaning. A `SubstantiveReviewFinding` is a falsifiable defect claim tied to one CRH5 `attack_id`; suggestions remain structurally non-blocking. Clearing evidence is bounded and exact-head aware, while finding currentness delegates to CRH1 proportional invalidation. Findings and clearing evidence grant no authority.

## Review coverage and test adequacy

`scripts/agent_os_pr_remediation/review_coverage.py` owns CRH7 evidence. Review coverage and test adequacy are independent dimensions: coverage asks whether a required CRH5 defect class was actually examined; adequacy asks whether supplied test evidence materially protects the behavior against the caller-supplied test-relevant subset of that attack's CRH5 evidence obligations. CRH7 never selects tests, invokes a reviewer, or converts provider/check success into attack coverage.

Every required `attack_id` receives one bounded coverage disposition: `examined-clear`, `examined-finding`, `not-applicable`, `unexamined-blocking`, `manual-review`, or `stale`. Missing per-attack evidence becomes `unexamined-blocking`; `examined-clear` and `examined-finding` require bounded per-attack evidence; conflicting observations fail closed; `examined-finding` requires a current CRH6 substantive finding; and `not-applicable` requires bounded evidence plus a reason. Duplicate equivalent observations collapse deterministically.

Coverage currentness reuses CRH1 `review_invalidation_scope(...)`. An old observation becomes stale when CRH1 says its affected surface is invalidated; an unrelated later change may preserve compatible semantic review coverage. CRH7 does not introduce another head/surface invalidation engine.

Test adequacy consumes caller-supplied `TestEvidence` plus an explicit `required_test_obligations` subset drawn from the existing CRH5 `RequiredAttack.bounded_evidence_requirements`. This distinction matters because CRH5 obligations are review-evidence obligations, not automatically unit-test requirements: architecture/API/provider-semantic attacks may appropriately have no required test obligation. For test-relevant attacks, a parser happy-path test cannot satisfy an ambiguity/fail-closed obligation merely because pytest is green. Supplied test-surface identity lets a later test-only change invalidate/recalculate adequacy without automatically invalidating unrelated semantic review coverage; unrelated changes may preserve compatible evidence under CRH1 proportional invalidation.

CRH7 does not require line/branch coverage percentages and does not execute #1554 property/mutation pilots. It may retain only the bounded report-only recommendations `property-test-candidate` or `mutation-test-candidate`; recommendation does not itself create a blocker or authority.

Coverage and adequacy records use deterministic IDs and keep execution, readiness, merge, closure, production/protected-setting, and external-write authority false. They retain bounded structured conclusions only—never chain-of-thought, unrestricted transcripts, or provider logs. #1675/CRH8A may score these deterministic records; #1587/CRH8B may measure operational effectiveness; #1588 remains provider execution/normalization owner.

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

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, workflow change, or external operation remains owned by the appropriate Agent OS owner. Review planning, findings, coverage, and adequacy evidence grant none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_review_evidence.py tests/agent_os_pr_remediation/test_review_attack_plan.py tests/agent_os_pr_remediation/test_review_findings.py tests/agent_os_pr_remediation/test_review_coverage.py
python -m pytest tests/agent_os_pr_remediation/test_merge_evidence_summary.py
python -m pytest tests/agent_os_pr_remediation/test_ci_evidence_recovery.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
