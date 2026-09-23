from __future__ import annotations

from scripts.agent_os_pr_remediation.aggregate_failure_provenance import (
    AggregateFailureProvenance,
    classify_aggregate_failure,
)

HEAD = "a" * 40
MAIN = "b" * 40
MERGE = "c" * 40
FINGERPRINT = "pytest:tests/package_b/test_contract.py::test_shared_contract"


def classify(**overrides):
    payload = {
        "tested_sha": HEAD,
        "current_head_sha": HEAD,
        "main_sha": MAIN,
        "failure_fingerprint": FINGERPRINT,
        "same_failure_on_current_main": False,
        "environment_or_bootstrap_failure": False,
        "required_repository_invariant": False,
        "changed_contract_reaches_failure": False,
        "synthetic_merge_only_failure": False,
    }
    payload.update(overrides)
    return classify_aggregate_failure(**payload)


def test_failure_reached_from_changed_contract_is_pr_attributable_despite_path_distance() -> None:
    result = classify(changed_contract_reaches_failure=True)
    assert result.provenance is AggregateFailureProvenance.PR_ATTRIBUTABLE
    assert result.blocking_pr_failure is True
    assert result.requires_manual_review is False


def test_identical_current_main_failure_is_shared_baseline_not_pr_defect() -> None:
    result = classify(same_failure_on_current_main=True)
    assert result.provenance is AggregateFailureProvenance.SHARED_BASELINE
    assert result.blocking_pr_failure is False
    assert "same-failure-on-current-main" in result.reason_codes


def test_bootstrap_failure_is_distinct_from_code_failure() -> None:
    result = classify(environment_or_bootstrap_failure=True, same_failure_on_current_main=True)
    assert result.provenance is AggregateFailureProvenance.ENVIRONMENT
    assert result.blocking_pr_failure is False


def test_environment_failure_without_baseline_reproduction_fails_closed() -> None:
    result = classify(environment_or_bootstrap_failure=True)
    assert result.provenance is AggregateFailureProvenance.ENVIRONMENT
    assert result.requires_manual_review is True


def test_required_repository_invariant_remains_blocking_even_when_main_also_fails() -> None:
    result = classify(required_repository_invariant=True, same_failure_on_current_main=True)
    assert result.provenance is AggregateFailureProvenance.PR_ATTRIBUTABLE
    assert result.blocking_pr_failure is True


def test_synthetic_merge_failure_remains_distinct_and_blocking() -> None:
    result = classify(tested_sha=MERGE, synthetic_merge_only_failure=True)
    assert result.provenance is AggregateFailureProvenance.MERGE_CONTEXT
    assert result.blocking_pr_failure is True


def test_shared_failure_requires_current_main_identity_and_fingerprint() -> None:
    result = classify(same_failure_on_current_main=True, main_sha=None)
    assert result.provenance is AggregateFailureProvenance.AMBIGUOUS
    assert result.requires_manual_review is True


def test_failure_no_longer_on_main_is_re_evaluated_not_inherited_as_shared() -> None:
    result = classify(same_failure_on_current_main=False)
    assert result.provenance is AggregateFailureProvenance.AMBIGUOUS
    assert result.requires_manual_review is True


def test_stale_non_merge_tested_sha_cannot_be_attributed_to_current_head() -> None:
    result = classify(tested_sha=MAIN)
    assert result.provenance is AggregateFailureProvenance.AMBIGUOUS
    assert result.requires_manual_review is True
    assert "aggregate-tested-sha-not-current-head" in result.reason_codes


def test_classifier_never_grants_authority_or_performs_side_effects() -> None:
    result = classify(changed_contract_reaches_failure=True)
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.closure_authorized is False
    assert result.production_authorized is False
    assert result.external_write_authorized is False
    assert result.side_effects_performed is False
