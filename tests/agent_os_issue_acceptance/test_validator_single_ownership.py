"""Regression cover for the #2500 duplicate-validator reduction.

Two projection modules previously carried byte-identical private copies of
validators their canonical owner already exported.  These tests fail if a copy
is reintroduced, and they re-prove the bounds/fail-closed behaviour that the
deleted copies used to enforce locally.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance import (
    approval_records,
    approved_execution_projection,
    coding_command_center_handoff,
    compute_control_projection,
)


CONSOLIDATED_HANDOFF_VALIDATORS = (
    "_canonical_json",
    "_canonical_reasons",
    "_optional_text",
    "_required_text",
    "_sha40",
)


@pytest.mark.parametrize("name", CONSOLIDATED_HANDOFF_VALIDATORS)
def test_compute_control_projection_reuses_the_handoff_validator(name: str) -> None:
    assert getattr(compute_control_projection, name) is getattr(
        coding_command_center_handoff, name
    ), f"{name} must stay owned by coding_command_center_handoff"


def test_compute_control_projection_does_not_redeclare_handoff_bounds() -> None:
    for constant in ("MAX_TEXT_BYTES", "MAX_REASON_CODES", "_SHA40_RE", "_CONTROL_RE"):
        assert not hasattr(compute_control_projection, constant), (
            f"{constant} must stay owned by coding_command_center_handoff"
        )


def test_approved_execution_projection_reuses_the_approval_cohort_validator() -> None:
    assert (
        approved_execution_projection._cohorts is approval_records._cohorts
    ), "_cohorts must stay owned by approval_records"


def test_consolidated_text_bounds_still_fail_closed() -> None:
    required_text = compute_control_projection._required_text
    assert required_text("head", "name") == "head"
    for rejected in ("", "a\x00b", "x" * (coding_command_center_handoff.MAX_TEXT_BYTES + 1)):
        with pytest.raises(ValueError):
            required_text(rejected, "name")
    with pytest.raises(ValueError):
        required_text(b"head", "name")


def test_consolidated_sha40_still_rejects_non_canonical_shas() -> None:
    sha40 = compute_control_projection._sha40
    assert sha40("a" * 40, "head_sha") == "a" * 40
    for rejected in ("A" * 40, "a" * 39, "a" * 41, "g" * 40):
        with pytest.raises(ValueError):
            sha40(rejected, "head_sha")


def test_consolidated_reason_codes_still_deduplicate_sort_and_bound() -> None:
    canonical_reasons = compute_control_projection._canonical_reasons
    assert canonical_reasons(("b", "a")) == ("a", "b")
    with pytest.raises(TypeError):
        canonical_reasons(["a"])
    with pytest.raises(ValueError):
        canonical_reasons(("a", "a"))
    with pytest.raises(ValueError):
        canonical_reasons(
            tuple(f"r{index}" for index in range(coding_command_center_handoff.MAX_REASON_CODES + 1))
        )


def test_consolidated_optional_text_preserves_none() -> None:
    optional_text = compute_control_projection._optional_text
    assert optional_text(None, "name") is None
    assert optional_text("value", "name") == "value"
    with pytest.raises(ValueError):
        optional_text("", "name")
