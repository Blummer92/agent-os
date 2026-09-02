# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation, risk-triggered review selection, bounded review evidence, deterministic Review Attack Plans, evidence-backed substantive findings, truthful review/merge-evidence summaries, and CI evidence recovery. It evaluates supplied evidence only and performs no provider invocation, source edit, validation execution, merge, or external write.

## Risk-triggered code review

`scripts/agent_os_pr_remediation/review_evidence.py` owns CRH1 review depth and the bounded `ReviewEvidencePacket`. Review depths remain `no-ai-review-required`, `normal-review-required`, `adversarial-review-required`, and `manual-decision-required`. `review_invalidation_scope(...)` remains the proportional currentness owner; downstream review contracts do not create another risk classifier, evidence packet, test selector, provenance model, or currentness engine.

## Deterministic Review Attack Plans

`scripts/agent_os_pr_remediation/review_attack_plan.py` consumes an existing CRH1 `ReviewEvidencePacket` and projects adversarial risk classes into a finite provider-neutral set of defect-class attacks. Normal/no-AI review is not inflated into a generic adversarial checklist.

Attack families are bounded to parser/resolver/selector, authorization/permissions/security, state/retry/reconciliation, persistence/migration, concurrency/lease/fencing, workflow/CI validation authority, cross-system/external API semantics, and architecture/ownership/interfaces. Closely related CRH1 risk classes map into these families; unknown, ambiguous, conflicting, or unmapped risk evidence fails closed to manual review rather than silently reducing the plan.

Every `RequiredAttack` carries an `attack_family`, invariant, exact `reviewed_head_sha`, CRH1-supplied affected-surface references, bounded evidence requirements, and finite reason codes. `attack_id` is content-addressed from those canonical semantics, so it is independent of provider prompt wording, model name, output order, or prose formatting. The plan itself has a deterministic `plan_id` and preserves CRH1 activated references.

## Evidence-backed substantive findings

`scripts/agent_os_pr_remediation/review_findings.py` owns CRH6 finding meaning. A `SubstantiveReviewFinding` is a falsifiable defect claim tied to one existing CRH5 `RequiredAttack.attack_id`. It carries the reviewed exact-head SHA, the attack invariant, a bounded affected surface, a concrete failure scenario, finite severity (`low`, `medium`, `high`, `critical`), bounded supporting evidence references, and a deterministic clearing condition. The stable `finding_id` is content-addressed from those defect semantics rather than provider prose length, confidence, comment ordering, or lifecycle state.

A substantive finding cannot be built without a concrete failure scenario, supporting evidence, or clearing evidence. Its invariant must match the originating CRH5 attack and its affected surface must stay within that attack's CRH1-derived surface. Suggestions use the separate `ReviewSuggestion` model; they are non-blocking, do not satisfy required attacks, do not count as discovered defects, and create no authority.

Clearing conditions use a finite evidence-class vocabulary: `regression-test`, `exact-head-validation`, `invariant-proof`, `surface-absent`, or `superseded-contract`. Resolution requires the named evidence class, all required bounded evidence references, and evidence bound to the finding's reviewed exact head. A prose assertion such as “reviewer says fixed” cannot substitute for a required regression test or exact-head result.

Finding currentness deliberately delegates to CRH1 `review_invalidation_scope(...)`. A changed affected surface becomes `stale`; an unrelated later change may preserve compatible resolved evidence; CRH1 full invalidators such as public-interface, architecture/ownership, authorization/security, dependency, workflow, or issue-scope changes invalidate the full reviewed finding surface. CRH6 does not introduce a second currentness or invalidation engine.

Finding lifecycle vocabulary is `current`, `resolved`, `stale`, `superseded`, and `manual-review`. All finding authority fields remain explicitly false. Findings and clearing evidence grant no execution, readiness, merge, closure, protected-setting, production, or external-write authority and perform no side effects.

CRH7 (#1586) may later use `attack_id` plus current finding state to prove review coverage/test adequacy; CRH8 (#1587) may later benchmark review effectiveness from substantive outcomes. Neither coverage scoring nor benchmark answer keys belong in CRH6.

Historical regression fixtures cover parser first-match ambiguity, transport success versus semantic failure, wrong-issue/cross-identity evidence consumption, authorization evidence mistaken for authority, and state/reconciliation failure without embedding product-specific repair logic.

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

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, workflow change, or external operation remains owned by the appropriate Agent OS owner. Review planning and findings themselves grant none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_review_evidence.py tests/agent_os_pr_remediation/test_review_attack_plan.py tests/agent_os_pr_remediation/test_review_findings.py
python -m pytest tests/agent_os_pr_remediation/test_merge_evidence_summary.py
python -m pytest tests/agent_os_pr_remediation/test_ci_evidence_recovery.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
