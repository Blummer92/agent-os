# Agent OS PR Review Remediation CLI

## Purpose

This package exposes pure-local, read-only contracts for PR review remediation, risk-triggered review selection, bounded review evidence, deterministic Review Attack Plans, evidence-backed substantive findings, per-attack review coverage/test adequacy, controlled code-review benchmarking, truthful review/merge-evidence summaries, and CI evidence recovery. It evaluates supplied evidence only and performs no provider invocation, source edit, validation execution, merge, or external write.

## Risk-triggered code review

`scripts/agent_os_pr_remediation/review_evidence.py` owns CRH1 review depth and the bounded `ReviewEvidencePacket`. Review depths remain `no-ai-review-required`, `normal-review-required`, `adversarial-review-required`, and `manual-decision-required`. `review_invalidation_scope(...)` remains the proportional currentness owner; downstream review contracts do not create another risk classifier, evidence packet, test selector, provenance model, or currentness engine.

## Deterministic Review Attack Plans

`scripts/agent_os_pr_remediation/review_attack_plan.py` consumes an existing CRH1 `ReviewEvidencePacket` and projects adversarial risk classes into a finite provider-neutral set of defect-class attacks. Every `RequiredAttack` carries a stable `attack_id`, exact reviewed head, affected surfaces, bounded evidence requirements, and reason codes.

## Evidence-backed substantive findings

`scripts/agent_os_pr_remediation/review_findings.py` owns CRH6 finding meaning. A `SubstantiveReviewFinding` is a falsifiable defect claim tied to one CRH5 `attack_id`; suggestions remain structurally non-blocking. Clearing evidence is bounded and exact-head aware, while finding currentness delegates to CRH1 proportional invalidation.

## Review coverage and test adequacy

`scripts/agent_os_pr_remediation/review_coverage.py` owns CRH7 evidence. Review coverage and test adequacy are independent dimensions. Every required `attack_id` receives one bounded coverage disposition; missing per-attack evidence becomes `unexamined-blocking`. Test adequacy consumes caller-supplied evidence and never becomes a second test selector.

## Blinded historical code-review benchmark

`scripts/agent_os_pr_remediation/code_review_benchmark.py` owns CRH8A Code Review Benchmark v1 (`benchmark=1.0.0`, `scorer=1.0.0`). It keeps the reviewer-visible packet and hidden answer key as separate typed surfaces, assigns a deterministic packet fingerprint, uses neutral case IDs, and rejects obvious answer-leakage material. Runs record model identity, reasoning setting, run number, tool profile, packet fingerprint, and explicit contamination state. Contaminated or tool-mismatched runs are ineligible rather than silently scored.

The finite review-time detectability vocabulary is `static-code-detectable`, `requirements-detectable`, `repository-context-detectable`, `review-time-test-detectable`, `runtime-evidence-required`, `later-evidence-only`, `review-time-unknowable`, and `manual-review`. Later-only, runtime-required, and review-time-unknowable cases never become reviewer false negatives. Clean controls require positive bounded answer evidence; insufficient evidence must be represented as manual review rather than invented cleanliness.

The scorer reuses CRH6 `FindingSeverity` and caller-supplied CRH5/CRH7 attack identities. It reports component metrics rather than a vanity composite: defect recall, severity-weighted recall, review precision, blocking-finding precision, false-block rate, severity calibration, evidence quality, fix-boundary accuracy, test-recommendation quality, manual-review calibration, unsupported-claim rate, and cross-run blocking stability. Defect identity—not comment count—owns recall, so synonymous findings cannot multiply discovered defects. False blockers on controls are explicit. Repeated fresh runs retain individual identities and expose unstable blocking outcomes.

The v1 protocol is intentionally small-sample and fixture-first. Locked sentinel cases may detect regressions while rotating/holdout cases remain separately versioned. Any change to reviewer packet semantics, answer-key semantics, scorer semantics, or admission rules requires a new version/fingerprint. Benchmark results are bounded evidence for #1587/CRH8B; they do not redefine operational effectiveness, provider execution (#1588), finding semantics, coverage semantics, or any implementation/release authority. No chain-of-thought, provider call, telemetry, database, workflow, or external write is required.

## Truthful review and merge evidence

`scripts/agent_os_pr_remediation/merge_evidence_summary.py` projects already-owned validation, acceptance, and review evidence into one bounded provider-neutral summary for the current PR lineage. Source head, base, synthetic merge SHA, merge commit, tested SHAs, reviewed SHA, and metadata fingerprint remain distinct identities.

## PR Review Remediation CLI

```bash
python -m scripts.agent_os_pr_remediation.cli --input tests/fixtures/agent_os_pr_remediation/e2e.json --format json
```

## CI Evidence Recovery Contract

`scripts/agent_os_pr_remediation/ci_evidence_recovery.py` plans bounded recovery of actionable GitHub Actions failure evidence without assuming `gh` or Cloud Shell. It performs no network, CLI, retry, repository, or external-system operation itself.

## GitHub Write Handoff

Any separately authorized source change, thread mutation, PR update, merge, issue lifecycle action, credential change, workflow change, or external operation remains owned by the appropriate Agent OS owner. Review planning, findings, coverage, adequacy, benchmark scoring, and repair-evidence presentation grant none of those authorities.

## Validation

Focused tests:

```bash
python -m pytest tests/agent_os_pr_remediation/test_review_evidence.py tests/agent_os_pr_remediation/test_review_attack_plan.py tests/agent_os_pr_remediation/test_review_findings.py tests/agent_os_pr_remediation/test_review_coverage.py
python -m pytest tests/agent_os_pr_remediation/test_code_review_benchmark.py
python -m pytest tests/agent_os_pr_remediation
```

Repository acceptance still requires normal exact-head aggregate validation and review checks on the pull request.
