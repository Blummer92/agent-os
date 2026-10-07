"""Focused tests for the #3336 provider-neutral task reasoning profile contract.

Fixtures cover the issue-required cases: trivial/no-model work,
low-complexity work, high-reasoning work, architecture work,
ambiguous/conflicting evidence, manual-decision-required work, unsupported
capability/effort evidence, and stale/tampered evidence identity.
"""
from __future__ import annotations

import pytest

from agent_os_execution_service.coding_worker_contract import CodingWorkerOperation
from agent_os_execution_service.reasoning_profile import (
    REASONING_PROFILE_SCHEMA_VERSION,
    ReasoningCapability,
    ReasoningContextRequirement,
    ReasoningEffort,
    RiskLevel,
    TaskClass,
    TaskReasoningProfile,
    project_pr_compute_route,
    serialize_task_reasoning_profile,
    task_reasoning_profile_id,
    validate_task_reasoning_profile,
)

PROFILED_AT = "2026-10-07T19:30:00Z"


def profile(**overrides: object) -> TaskReasoningProfile:
    values: dict[str, object] = {
        "schema_version": REASONING_PROFILE_SCHEMA_VERSION,
        "task_identity": "issue:3336",
        "task_class": TaskClass.CLASSIFY,
        "work_operation_or_none": None,
        "reasoning_effort": ReasoningEffort.LOW,
        "semantic_ambiguity": False,
        "risk": RiskLevel.LOW,
        "capability_requirements": (ReasoningCapability.SINGLE_STEP_INFERENCE,),
        "context_requirements": (ReasoningContextRequirement.TASK_EVIDENCE,),
        "manual_review_required": False,
        "manual_review_reason_or_none": None,
        "reasons": ("bounded vocabulary assignment over supplied inputs",),
        "evidence_refs": ("issue:3336-body",),
        "profiled_at": PROFILED_AT,
    }
    values.update(overrides)
    return TaskReasoningProfile(**values)


def test_trivial_no_model_work() -> None:
    p = profile(
        task_identity="task:mechanical-rename",
        task_class=TaskClass.IMPLEMENT,
        work_operation_or_none=CodingWorkerOperation.REFACTOR,
        reasoning_effort=ReasoningEffort.NONE,
        capability_requirements=(),
        context_requirements=(ReasoningContextRequirement.TASK_EVIDENCE,),
        reasons=("deterministic mechanical transformation; no inference required",),
    )
    assert p.reasoning_effort is ReasoningEffort.NONE
    assert p.capability_requirements == ()
    assert p.manual_review_required is False
    assert p.execution_authorized is False
    assert p.merge_authorized is False
    assert p.closure_authorized is False
    assert p.external_writes_authorized is False


def test_low_complexity_work() -> None:
    p = profile()
    assert p.reasoning_effort is ReasoningEffort.LOW
    assert p.task_class is TaskClass.CLASSIFY


def test_high_reasoning_work() -> None:
    p = profile(
        task_identity="task:conflicting-review-threads",
        task_class=TaskClass.TRIAGE,
        reasoning_effort=ReasoningEffort.HIGH,
        semantic_ambiguity=True,
        risk=RiskLevel.HIGH,
        capability_requirements=(
            ReasoningCapability.MULTI_STEP_INFERENCE,
            ReasoningCapability.AMBIGUITY_RESOLUTION,
        ),
        context_requirements=(
            ReasoningContextRequirement.TASK_EVIDENCE,
            ReasoningContextRequirement.HISTORICAL_PRECEDENT,
        ),
        reasons=("review threads disagree on the defect cause",),
    )
    assert p.semantic_ambiguity is True
    assert ReasoningCapability.AMBIGUITY_RESOLUTION in p.capability_requirements


def test_architecture_work() -> None:
    p = profile(
        task_identity="task:redesign-admission-boundary",
        task_class=TaskClass.ARCHITECTURE,
        work_operation_or_none=CodingWorkerOperation.IMPLEMENT,
        reasoning_effort=ReasoningEffort.MAXIMUM,
        risk=RiskLevel.HIGH,
        capability_requirements=(
            ReasoningCapability.ARCHITECTURAL_DESIGN,
            ReasoningCapability.TRADEOFF_SYNTHESIS,
        ),
        context_requirements=(ReasoningContextRequirement.REPOSITORY_CONTEXT,),
        reasons=("structure a new admission boundary under competing constraints",),
    )
    assert p.reasoning_effort is ReasoningEffort.MAXIMUM
    assert p.task_class is TaskClass.ARCHITECTURE


def test_ambiguous_evidence_cannot_claim_no_effort() -> None:
    with pytest.raises(ValueError, match="semantic_ambiguity"):
        profile(semantic_ambiguity=True, reasoning_effort=ReasoningEffort.NONE)


def test_manual_decision_required_stays_human_owned() -> None:
    # Manual review is orthogonal to effort: a low-effort task can still
    # require a human decision regardless of model strength.
    p = profile(
        task_identity="task:merge-admission-call",
        task_class=TaskClass.DECISION_SUPPORT,
        reasoning_effort=ReasoningEffort.LOW,
        manual_review_required=True,
        manual_review_reason_or_none="merge admission is a human-owned decision",
        reasons=("recommendation supports a human merge call; the call stays human",),
    )
    assert p.manual_review_required is True
    assert p.reasoning_effort is ReasoningEffort.LOW


def test_manual_review_requires_reason() -> None:
    with pytest.raises(ValueError, match="manual_review_reason_or_none"):
        profile(manual_review_required=True, manual_review_reason_or_none=None)


def test_manual_review_reason_forbidden_without_flag() -> None:
    with pytest.raises(ValueError, match="manual_review_reason_or_none"):
        profile(manual_review_required=False, manual_review_reason_or_none="stray")


def test_unsupported_effort_evidence_rejected() -> None:
    payload = serialize_task_reasoning_profile(profile())
    payload["reasoning_effort"] = "ultra"
    with pytest.raises(ValueError):
        validate_task_reasoning_profile(payload)


def test_unsupported_capability_evidence_rejected() -> None:
    payload = serialize_task_reasoning_profile(profile())
    payload["capability_requirements"] = ["telepathy"]
    with pytest.raises(ValueError):
        validate_task_reasoning_profile(payload)


def test_model_choice_cannot_enter_wire_format() -> None:
    # Provider dependence cannot enter through the wire format: any model or
    # provider field is an unknown field and fails closed.
    for smuggled in ("model_identity", "model_name", "provider", "reasoning_setting"):
        payload = serialize_task_reasoning_profile(profile())
        payload[smuggled] = "gpt-5.6"
        with pytest.raises(ValueError, match="unknown or missing fields"):
            validate_task_reasoning_profile(payload)


def test_authority_injection_rejected() -> None:
    payload = serialize_task_reasoning_profile(profile())
    payload["execution_authorized"] = True
    with pytest.raises(ValueError, match="must be false"):
        validate_task_reasoning_profile(payload)


def test_tampered_evidence_identity_detected() -> None:
    p = profile()
    payload = serialize_task_reasoning_profile(p)
    payload["evidence_refs"] = ("issue:9999-forged",)
    # profile_id no longer matches the tampered content.
    with pytest.raises(ValueError, match="profile_id does not match"):
        validate_task_reasoning_profile(payload)
    # A fresh profile over different evidence carries a different identity.
    other = profile(evidence_refs=("issue:9999-forged",))
    assert other.profile_id != p.profile_id


def test_deterministic_bounded_output() -> None:
    first = profile()
    second = profile()
    assert first.profile_id == second.profile_id
    assert task_reasoning_profile_id(first) == first.profile_id
    assert serialize_task_reasoning_profile(first) == serialize_task_reasoning_profile(second)


def test_roundtrip_preserves_exact_form() -> None:
    p = profile(
        task_class=TaskClass.ADVERSARIAL_REVIEW,
        work_operation_or_none=CodingWorkerOperation.IMPLEMENT,
        reasoning_effort=ReasoningEffort.HIGH,
        semantic_ambiguity=True,
        risk=RiskLevel.MEDIUM,
        capability_requirements=(ReasoningCapability.ADVERSARIAL_ANALYSIS,),
        manual_review_required=True,
        manual_review_reason_or_none="adversarial findings need human triage",
        reasons=("find flaws the author missed",),
        evidence_refs=("pr:3370-diff", "issue:3336-body"),
    )
    restored = validate_task_reasoning_profile(serialize_task_reasoning_profile(p))
    assert restored == p


def test_pr_compute_route_projection() -> None:
    assert project_pr_compute_route("no-model") == (ReasoningEffort.NONE, False)
    assert project_pr_compute_route("small-model-eligible") == (ReasoningEffort.LOW, False)
    assert project_pr_compute_route("high-reasoning-required") == (ReasoningEffort.HIGH, False)
    # manual-decision-required specifies no machine-side effort: the projection
    # is honest about the gap instead of inventing one.
    assert project_pr_compute_route("manual-decision-required") == (None, True)


def test_pr_compute_route_projection_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown PR compute route"):
        project_pr_compute_route("frontier-model-only")
    with pytest.raises(TypeError):
        project_pr_compute_route(None)  # type: ignore[arg-type]


def test_task_class_vocabulary_is_closed() -> None:
    assert {item.value for item in TaskClass} == {
        "extract",
        "classify",
        "triage",
        "implement",
        "debug",
        "architecture",
        "adversarial-review",
        "decision-support",
    }


def test_effort_vocabulary_is_closed() -> None:
    assert [item.value for item in ReasoningEffort] == [
        "none",
        "low",
        "medium",
        "high",
        "maximum",
    ]


def test_duplicate_requirements_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        profile(
            capability_requirements=(
                ReasoningCapability.SINGLE_STEP_INFERENCE,
                ReasoningCapability.SINGLE_STEP_INFERENCE,
            )
        )


def test_reasons_required() -> None:
    with pytest.raises(ValueError, match="reasons"):
        profile(reasons=())
