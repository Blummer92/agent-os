"""Canonical ``agent_os_continuation`` payload contract for the MCP facade (#3485 R1).

Every continuation-named facade function must return the canonical payload
projected by ``continuation_driver.continuation_payload`` /
``completion_continuation_payload``: exactly eight keys, all authority flags
fixed False. Before R1, ``classify_agent_os_continuation`` returned only the
post-selection schema and ``plan_agent_os_continuation`` returned no payload
at all, so consumers written against the canonical shape (the Stop seam's
``action``/``terminal``/``blocked``/``stalled`` reader) could not consume
either tool's result.
"""

from __future__ import annotations

from agent_os_execution_service.mcp_facade import (
    admit_agent_os_failed_repair,
    classify_agent_os_continuation,
    classify_agent_os_mission_completion,
    plan_agent_os_continuation,
)

CANONICAL_CONTINUATION_KEYS = {
    "action",
    "terminal",
    "blocked",
    "stalled",
    "reason_codes",
    "execution_authorized",
    "github_writes_authorized",
    "side_effects_performed",
}

# The exact top-level keys classify_agent_os_continuation returned before R1
# (the asdict of the #1237 ContinuationDecision, with the facade's own
# classification/reason_codes/obligations/lineage projections). R1 is additive:
# no key may be removed or renamed, and exactly one key is added.
CLASSIFY_PRE_R1_KEYS = {
    "schema_name",
    "schema_version",
    "decision_id",
    "operation_id",
    "lineage",
    "classification",
    "reason_codes",
    "obligations",
    "continue_automatically",
    "mutation_permitted",
    "alternative_capability",
    "delegated_owner",
    "blocker",
    "clearing_condition",
    "capability_limitation_is_mission_blocker",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "issue_closure_authorized",
    "external_writes_authorized",
    "lease_acquired",
    "scheduler_invoked",
    "competing_lineage_created",
    "side_effects_performed",
}


def _assert_canonical(payload: object) -> dict[str, object]:
    assert type(payload) is dict
    assert set(payload) == CANONICAL_CONTINUATION_KEYS
    assert type(payload["action"]) is str
    for flag in ("terminal", "blocked", "stalled"):
        assert type(payload[flag]) is bool
    assert type(payload["reason_codes"]) is list
    assert payload["execution_authorized"] is False
    assert payload["github_writes_authorized"] is False
    assert payload["side_effects_performed"] is False
    return payload


def _classify(**overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = {
        "repository": "Blummer92/agent-os",
        "issue_number": 1213,
        "operation_id": "replace-exact-changelog",
        "surface_outcome": "selected-surface-unavailable",
        "approved_alternative_capability": "github-exact-blob-read",
        "target_identity_reacquired": True,
    }
    kwargs.update(overrides)
    return classify_agent_os_continuation(**kwargs)  # type: ignore[arg-type]


def test_classify_continuation_projects_canonical_payload_for_alternative() -> None:
    result = _classify()
    assert result["classification"] == "capability-alternative-available"
    assert result["continue_automatically"] is True
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["terminal"] is False
    assert payload["blocked"] is False
    assert payload["stalled"] is False
    assert payload["action"] == "continue-with-approved-alternative"
    assert payload["reason_codes"] == result["reason_codes"]


def test_classify_continuation_is_schema_backwards_compatible() -> None:
    result = _classify()
    assert set(result) == CLASSIFY_PRE_R1_KEYS | {"agent_os_continuation"}


def test_classify_continuation_blocked_only_when_decision_records_blocker() -> None:
    result = _classify(approved_alternative_capability=None)
    assert result["classification"] == "no-capable-authorized-route"
    assert result["blocker"] is not None
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["terminal"] is False
    assert payload["blocked"] is True
    assert payload["action"] == "halt-no-capable-authorized-route"


def test_classify_continuation_repeated_transition_is_blocked_not_terminal() -> None:
    result = _classify(equivalent_transition_repeated=True, target_identity_reacquired=False)
    assert result["classification"] == "no-capable-authorized-route"
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["blocked"] is True
    assert payload["terminal"] is False


def test_classify_continuation_reconciliation_is_neither_blocked_nor_terminal() -> None:
    result = _classify(prior_effect="ambiguous")
    assert result["classification"] == "partial-effect-reconciliation-required"
    assert result["blocker"] is None
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["terminal"] is False
    assert payload["blocked"] is False
    assert payload["action"] == "discharge-continuation-obligations"


def test_classify_continuation_currentness_unproven_is_neither_blocked_nor_terminal() -> None:
    result = _classify(target_identity_reacquired=False)
    assert result["classification"] == "currentness-or-identity-unproven"
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["terminal"] is False
    assert payload["blocked"] is False
    assert payload["action"] == "discharge-continuation-obligations"


def test_plan_without_handoff_attaches_nonterminal_discovery_payload() -> None:
    result = plan_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233)
    pre_existing = {key: value for key, value in result.items() if key != "agent_os_continuation"}
    assert pre_existing == {
        "status": "agent-os-route",
        "repository": "Blummer92/agent-os",
        "issue_number": 1233,
        "next_operation": "discover-current-handoff",
        "handoff_id": None,
        "ingress": None,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["action"] == "discover-current-handoff"
    assert payload["terminal"] is False
    assert payload["blocked"] is False
    assert payload["reason_codes"] == []


def test_plan_with_handoff_attaches_resume_payload_and_preserves_fields() -> None:
    handoff = "executor-handoff:" + "a" * 64
    result = plan_agent_os_continuation(repository="Blummer92/agent-os", issue_number=1233, canonical_handoff_id=handoff)
    pre_existing = {key: value for key, value in result.items() if key != "agent_os_continuation"}
    assert pre_existing == {
        "status": "agent-os-route",
        "repository": "Blummer92/agent-os",
        "issue_number": 1233,
        "next_operation": "resume-existing-handoff",
        "handoff_id": handoff,
        "ingress": f"/agent-os resume {handoff}",
        "execution_authorized": False,
        "github_writes_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }
    payload = _assert_canonical(result["agent_os_continuation"])
    assert payload["action"] == "resume-existing-handoff"
    assert payload["terminal"] is False
    assert payload["blocked"] is False


def test_continuation_named_facade_functions_share_the_canonical_payload() -> None:
    results = {
        "plan_agent_os_continuation": plan_agent_os_continuation(
            repository="Blummer92/agent-os", issue_number=1233
        ),
        "classify_agent_os_continuation": _classify(),
        "classify_agent_os_mission_completion": classify_agent_os_mission_completion(
            repository="Blummer92/agent-os",
            issue_number=2189,
            branch_exists=True,
            implementation_commit_count=1,
            draft_pr_exists=False,
            canonical_pr_readback_verified=False,
            capable_route_available=True,
            subordinate_writes_only=False,
        ),
        "admit_agent_os_failed_repair": admit_agent_os_failed_repair(
            activation_result={
                "attempt_id": "attempt-1",
                "retry_reentry_outcome": "consumed",
                "selected_lesson_ids": ["63"],
                "mutation_admissible": True,
            },
            check_state="red",
            required_check_configuration_state="current",
            review_state="clear",
            branch_freshness="current",
            mergeability="mergeable",
        ),
    }
    for name, result in results.items():
        assert "agent_os_continuation" in result, name
        _assert_canonical(result["agent_os_continuation"])
