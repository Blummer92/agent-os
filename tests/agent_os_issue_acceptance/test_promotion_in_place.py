from __future__ import annotations

import pytest

from scripts.agent_os_issue_acceptance.promotion_in_place import (
    IssueScopeSnapshot,
    PromotionDecision,
    evaluate_promotion_in_place,
)


def _snapshot(**overrides: object) -> IssueScopeSnapshot:
    base: dict[str, object] = {
        "objective": "Add bounded lifecycle contract",
        "owner": "integration-manager",
        "bounded_scope": ("01_Shared_Standards/instructional-design/",),
        "source_of_truth": "GitHub",
        "risk_tier": 1,
    }
    base.update(overrides)
    return IssueScopeSnapshot(**base)  # type: ignore[arg-type]


def test_unchanged_planning_objective_promotes_in_place() -> None:
    result = evaluate_promotion_in_place(_snapshot(), _snapshot())
    assert result.decision is PromotionDecision.PROMOTE_IN_PLACE
    assert result.changed_fields == ()


def test_reordered_bounded_scope_is_not_a_material_change() -> None:
    before = _snapshot(bounded_scope=("a/", "b/"))
    after = _snapshot(bounded_scope=("b/", "a/"))
    result = evaluate_promotion_in_place(before, after)
    assert result.decision is PromotionDecision.PROMOTE_IN_PLACE


@pytest.mark.parametrize(
    "overrides",
    [
        {"objective": "Different objective"},
        {"owner": "qa-test-agent"},
        {"bounded_scope": ("different/path/",)},
        {"source_of_truth": "Notion"},
        {"risk_tier": 2},
    ],
)
def test_material_identity_change_requires_successor(overrides: dict[str, object]) -> None:
    result = evaluate_promotion_in_place(_snapshot(), _snapshot(**overrides))
    assert result.decision is PromotionDecision.SUCCESSOR_REQUIRED
    assert result.changed_fields


@pytest.mark.parametrize(
    "flag",
    [
        "architecture_touched",
        "compatibility_break",
        "external_effect",
        "protected_surface_touched",
    ],
)
def test_material_risk_flag_requires_successor(flag: str) -> None:
    result = evaluate_promotion_in_place(_snapshot(), _snapshot(**{flag: True}))
    assert result.decision is PromotionDecision.SUCCESSOR_REQUIRED
    assert flag in result.changed_fields


def test_bounded_scope_must_be_non_empty_and_unique() -> None:
    with pytest.raises(ValueError):
        _snapshot(bounded_scope=())
    with pytest.raises(ValueError):
        _snapshot(bounded_scope=("a/", "a/"))


def test_risk_tier_must_be_zero_one_or_two() -> None:
    with pytest.raises(ValueError):
        _snapshot(risk_tier=3)


def test_inputs_must_be_snapshots() -> None:
    with pytest.raises(TypeError):
        evaluate_promotion_in_place(_snapshot(), object())  # type: ignore[arg-type]
