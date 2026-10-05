"""Test-60: narration can never satisfy mission completion.

Mirrors the Tests 29-35 pattern: the premature-completion failure class at the
repo-enforceable seam. ``evaluate_mission_completion_admission`` projects
``completion_admissible`` from caller-supplied booleans on trust; Test-60 pins
the narration backstop -- a bare asserted True with no evidence binding fails
closed, and prose (including this projector's own ``next_action`` output) is
never evidence.
"""

import pytest

from scripts.agent_os_execution_interface.mission_completion_admission import (
    LIVE_CONSUMER_OBSERVATION,
    evaluate_mission_completion_admission,
)


def _green_kwargs(**overrides):
    values = {
        "repository": "Blummer92/agent-os",
        "issue_number": 1985,
        "branch_exists": True,
        "implementation_commit_count": 1,
        "draft_pr_exists": True,
        "canonical_pr_readback_verified": True,
        "capable_route_available": True,
        "subordinate_writes_only": False,
        "live_consumer_required": False,
        "canonical_pr_readback_binding": "readback-digest:canonical-pr:1985",
    }
    values.update(overrides)
    return evaluate_mission_completion_admission(**values)


def _live_kwargs(**overrides):
    values = {
        "live_consumer_required": True,
        "live_consumer_requirement_source": "issue-contract:#2765",
        "live_consumer_reachability_proven": True,
        "live_consumer_identity": "agent-os:exact-live-consumer",
        "live_consumer_evidence_source": "canonical-host-observation:current",
        "live_consumer_evidence_current": True,
        "live_consumer_evidence_kind": LIVE_CONSUMER_OBSERVATION,
        "live_consumer_observation_binding": (
            "observation-digest:live-consumer:agent-os:exact-live-consumer"
        ),
    }
    values.update(overrides)
    return _green_kwargs(**values)


def test_60_bare_asserted_readback_without_binding_fails_closed():
    """A bare True for canonical_pr_readback_verified with no binding is
    narration, not evidence: completion is refused."""
    result = _green_kwargs(canonical_pr_readback_binding=None)
    assert result.completion_admissible is False
    assert "canonical-pr-readback-not-proven" in result.reason_codes


def test_60_bare_asserted_live_reachability_without_binding_fails_closed():
    """A bare True for live_consumer_reachability_proven with no binding is
    narration, not evidence: completion is refused even when every other
    live-consumer field is populated."""
    result = _live_kwargs(live_consumer_observation_binding=None)
    assert result.completion_admissible is False
    assert "required-live-consumer-reachability-not-proven" in result.reason_codes


def test_60_bound_readback_admits():
    """Control: the same True claim with a binding admits (no behavior change
    for callers that bind their evidence)."""
    result = _green_kwargs()
    assert result.completion_admissible is True
    assert result.canonical_pr_readback_binding == "readback-digest:canonical-pr:1985"


def test_60_bound_live_observation_admits():
    """Control: the same live claim with a binding admits."""
    result = _live_kwargs()
    assert result.completion_admissible is True
    assert "required-live-consumer-current-observation-proven" in result.reason_codes


def test_60_empty_binding_rejected():
    """An empty binding string is not a binding."""
    with pytest.raises(ValueError, match="canonical_pr_readback_binding"):
        _green_kwargs(canonical_pr_readback_binding="")


def test_60_whitespace_binding_rejected():
    """A whitespace-only binding string is not a binding."""
    with pytest.raises(ValueError, match="live_consumer_observation_binding"):
        _live_kwargs(live_consumer_observation_binding="   ")


def test_60_prose_in_readback_boolean_slot_raises_type_error():
    """Feeding next_action prose into the readback boolean slot is rejected:
    prose is never coerced to True."""
    refused = _green_kwargs(canonical_pr_readback_binding=None)
    with pytest.raises(TypeError):
        _green_kwargs(
            canonical_pr_readback_verified=refused.next_action,
            canonical_pr_readback_binding="readback-digest:canonical-pr:1985",
        )


def test_60_prose_in_live_boolean_slot_raises_type_error():
    """Feeding next_action prose into the live-reachability boolean slot is
    rejected: prose is never coerced to True."""
    refused = _live_kwargs(live_consumer_observation_binding=None)
    with pytest.raises(TypeError):
        _live_kwargs(live_consumer_reachability_proven=refused.next_action)


def test_60_next_action_prose_as_binding_alone_does_not_admit():
    """next_action prose supplied as the binding without the boolean claim
    admits nothing: a digest string carries no authority by itself."""
    refused = _green_kwargs(canonical_pr_readback_binding=None)
    result = _green_kwargs(
        canonical_pr_readback_verified=False,
        canonical_pr_readback_binding=refused.next_action,
        draft_pr_exists=False,
    )
    assert result.completion_admissible is False


def test_60_prose_stuffed_text_fields_do_not_bypass_binding():
    """Stuffing next_action prose into every free-text evidence field does not
    satisfy the binding requirement: prose is not evidence."""
    refused = _live_kwargs(live_consumer_observation_binding=None)
    prose = refused.next_action
    result = _live_kwargs(
        live_consumer_requirement_source=prose,
        live_consumer_identity=prose,
        live_consumer_evidence_source=prose,
        live_consumer_observation_binding=None,
    )
    assert result.completion_admissible is False
    assert "required-live-consumer-reachability-not-proven" in result.reason_codes
