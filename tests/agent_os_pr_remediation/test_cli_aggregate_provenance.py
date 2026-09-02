from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent_os_pr_remediation.cli import evaluate, render_text
from scripts.agent_os_pr_remediation.models import AUTHORITY_FIELDS, EvidenceValidationError

FIXTURE_PATH = Path(__file__).parents[1] / "fixtures" / "agent_os_pr_remediation" / "e2e.json"
HEAD = "2" * 40
MAIN = "1" * 40


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _provenance(**overrides: object) -> dict:
    payload = {
        "tested_sha": HEAD,
        "main_sha": MAIN,
        "failure_fingerprint": "pytest:tests/package_b/test_contract.py::test_shared_contract",
        "same_failure_on_current_main": True,
        "environment_or_bootstrap_failure": False,
        "required_repository_invariant": False,
        "changed_contract_reaches_failure": False,
        "synthetic_merge_only_failure": False,
    }
    payload.update(overrides)
    return payload


def _assert_authority_false(value: object) -> None:
    if type(value) is dict:
        for field in AUTHORITY_FIELDS:
            if field in value:
                assert value[field] is False
        for item in value.values():
            _assert_authority_false(item)
    elif type(value) in {list, tuple}:
        for item in value:
            _assert_authority_false(item)


def test_shared_baseline_provenance_is_operator_visible_and_non_blocking():
    payload = _fixture()
    payload["aggregate_failure_provenance"] = _provenance()

    report = evaluate(payload)
    aggregate = report["aggregate_failure_provenance"]

    assert aggregate["provenance"] == "shared-baseline"
    assert aggregate["blocking_pr_failure"] is False
    assert aggregate["requires_manual_review"] is False
    assert "same-failure-on-current-main" in aggregate["reason_codes"]
    assert "aggregate provenance: shared-baseline (PR-blocking=false, manual-review=false)" in render_text(report)
    _assert_authority_false(report)


def test_pr_attributable_provenance_remains_explicitly_blocking():
    payload = _fixture()
    payload["aggregate_failure_provenance"] = _provenance(
        same_failure_on_current_main=False,
        changed_contract_reaches_failure=True,
    )

    report = evaluate(payload)
    aggregate = report["aggregate_failure_provenance"]

    assert aggregate["provenance"] == "pr-attributable"
    assert aggregate["blocking_pr_failure"] is True
    assert aggregate["requires_manual_review"] is False
    assert "changed-contract-reaches-failure" in aggregate["reason_codes"]
    _assert_authority_false(report)


def test_ambiguous_provenance_fails_closed_to_manual_review():
    payload = _fixture()
    payload["aggregate_failure_provenance"] = _provenance(
        same_failure_on_current_main=False,
        failure_fingerprint=None,
    )

    report = evaluate(payload)
    aggregate = report["aggregate_failure_provenance"]

    assert aggregate["provenance"] == "ambiguous"
    assert aggregate["blocking_pr_failure"] is False
    assert aggregate["requires_manual_review"] is True
    assert "aggregate-failure-attribution-unproven" in aggregate["reason_codes"]
    _assert_authority_false(report)


def test_stale_aggregate_tested_sha_is_operator_visible_as_ambiguous():
    payload = _fixture()
    payload["aggregate_failure_provenance"] = _provenance(tested_sha="3" * 40)

    report = evaluate(payload)
    aggregate = report["aggregate_failure_provenance"]

    assert aggregate["provenance"] == "ambiguous"
    assert aggregate["requires_manual_review"] is True
    assert "aggregate-tested-sha-not-current-head" in aggregate["reason_codes"]


def test_malformed_aggregate_provenance_fails_closed():
    payload = _fixture()
    payload["aggregate_failure_provenance"] = {"tested_sha": HEAD}

    with pytest.raises(EvidenceValidationError, match="missing aggregate provenance fields"):
        evaluate(payload)
