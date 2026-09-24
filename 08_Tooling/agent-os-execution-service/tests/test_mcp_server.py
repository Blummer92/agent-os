from __future__ import annotations

import inspect
import re

from agent_os_execution_service import mcp_server
from agent_os_execution_service.lesson_reader_composition import LESSONS_LEARNED_DATA_SOURCE_ENV

EXPECTED_TOOLS = frozenset(
    {
        "bind_agent_os_request_interpretation_tool",
        "plan_connected_issue_creation_tool",
        "plan_agent_os_continuation_tool",
        "admit_agent_os_primary_pr_creation_tool",
        "admit_agent_os_batch_pr_packaging_tool",
        "activate_agent_os_issue_start_lessons_tool",
        "activate_agent_os_failed_repair_tool",
        "admit_agent_os_failed_repair_tool",
        "classify_agent_os_mission_completion_tool",
        "classify_agent_os_issue_batch_completion_tool",
        "classify_agent_os_investigation_completion_tool",
        "classify_agent_os_continuation_tool",
        "classify_agent_os_bulk_repair_continuation_tool",
    }
)


def test_mcp_server_exposes_only_bounded_agent_os_tools() -> None:
    source = inspect.getsource(mcp_server)
    exposed = set(re.findall(r"@mcp\.tool\(\)\s*\ndef (\w+)", source))
    assert exposed == EXPECTED_TOOLS, (
        "MCP tool surface drifted; "
        f"added={sorted(exposed - EXPECTED_TOOLS)} removed={sorted(EXPECTED_TOOLS - exposed)}"
    )
    assert source.count("@mcp.tool()") == len(EXPECTED_TOOLS)


def test_mcp_server_contains_no_execution_or_store_primitives() -> None:
    source = inspect.getsource(mcp_server)
    forbidden = (
        "subprocess",
        "os.system",
        "checkpoint_store",
        "handoff_store",
        "PyGithub",
        "requests.",
        "run_authorized_validation",
        "activate_first_publication",
        "run_governed",
    )
    for token in forbidden:
        assert token not in source



def _request_interpretation_payload() -> dict[str, object]:
    import hashlib
    raw = "work on #2821"
    return {
        "schema_name": "request-interpretation",
        "contract_version": "request-interpretation-v1",
        "record_revision": 1,
        "observed_at": "2026-09-23T12:00:00Z",
        "interpreter_id": "chatgpt-orchestrator",
        "raw_input_digest": hashlib.sha256(raw.encode()).hexdigest(),
        "instruction_origin": "direct-user",
        "action": "implement",
        "requested_effect": "mutate",
        "continuation_mode": "new",
        "target": {"system": "github", "resource_kind": "issue", "repository": "Blummer92/agent-os", "resource_id": "2821"},
        "requested_outputs": [],
        "constraints": [],
        "reason_codes": [],
        "evidence_references": [],
    }


def test_request_binding_produces_stable_non_authorizing_identity_before_dispatch() -> None:
    first = mcp_server.bind_agent_os_request_interpretation_tool(_request_interpretation_payload())
    second = mcp_server.bind_agent_os_request_interpretation_tool(_request_interpretation_payload())
    assert first["status"] == "valid"
    assert first["dispatch_admitted"] is True
    assert first["record_id"] == second["record_id"]
    assert first["raw_input_digest"] == second["raw_input_digest"]
    assert first["execution_authorized"] is False
    assert first["github_writes_authorized"] is False
    assert first["side_effects_performed"] is False


def test_request_binding_fails_closed_before_dispatch_for_ambiguous_input() -> None:
    payload = _request_interpretation_payload()
    payload["action"] = "unknown"
    result = mcp_server.bind_agent_os_request_interpretation_tool(payload)
    assert result["status"] == "manual-review-required"
    assert result["dispatch_admitted"] is False
    assert result["record_id"] is not None
    assert "action.ambiguous" in result["details"]


CONNECTED_ISSUE_BODY = """### Issue tier

tier:1-standard-implementation

### Primary owner

owner:github-service-agent

### Readiness candidate

status:ready

### Work type

type:bug

### Source of truth

GitHub

### External write boundary

no-external-write

### Prior scope, duplicate, and supersession review

Reviewed current canonical owners and bounded duplicate/supersession evidence.
"""


def test_connected_issue_creation_tool_passes_distinct_bug_admission() -> None:
    result = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body=CONNECTED_ISSUE_BODY,
        duplicate_review_disposition="NEW_DISTINCT_BUG",
    )
    assert result["create_allowed"] is True
    assert result["next_operation"] == "create-then-canonical-readback-and-converge"
    assert result["duplicate_review_disposition"] == "NEW_DISTINCT_BUG"
    assert result["implementation_authorized"] is False
    assert result["merge_authorized"] is False
    assert result["closure_authorized"] is False
    assert result["external_write_authorized"] is False
    assert result["create_response_terminal"] is False
    assert result["post_create_readback_required"] is True
    assert result["post_create_reconciliation_required_on_mismatch"] is True
    assert result["terminal_success_requires_label_convergence"] is True


def test_connected_issue_creation_tool_passes_existing_owner_admission() -> None:
    recurrence = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body=CONNECTED_ISSUE_BODY,
        duplicate_review_disposition="RECURRENCE_EXISTING_OWNER",
        canonical_issue_number=2438,
    )
    duplicate = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body=CONNECTED_ISSUE_BODY,
        duplicate_review_disposition="DUPLICATE_EXISTING_OWNER",
        canonical_issue_number=2438,
    )
    assert recurrence["create_allowed"] is False
    assert recurrence["canonical_issue_number"] == 2438
    assert recurrence["next_operation"] == "append-recurrence-evidence-to-canonical-issue"
    assert duplicate["create_allowed"] is False
    assert duplicate["canonical_issue_number"] == 2438
    assert duplicate["next_operation"] == "reuse-canonical-issue-no-create"


def test_connected_issue_creation_tool_passes_focused_successor_evidence() -> None:
    result = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body=CONNECTED_ISSUE_BODY,
        duplicate_review_disposition="FOCUSED_SUCCESSOR",
        canonical_issue_number=2438,
        distinct_repair_seam=True,
    )
    assert result["create_allowed"] is True
    assert result["duplicate_review_disposition"] == "FOCUSED_SUCCESSOR"


def test_connected_issue_creation_tool_missing_admission_fails_closed() -> None:
    result = mcp_server.plan_connected_issue_creation_tool(
        repository="Blummer92/agent-os",
        issue_body=CONNECTED_ISSUE_BODY,
    )
    assert result["create_allowed"] is False
    assert result["duplicate_review_disposition"] == "MANUAL_REVIEW"
    assert result["next_operation"] == "manual-review-duplicate-admission-required"


def test_primary_pr_creation_tool_reuses_single_existing_pr() -> None:
    result = mcp_server.admit_agent_os_primary_pr_creation_tool(
        issue_number=2609,
        issue_open=True,
        evidence_current=True,
        active_primary_prs=[
            {
                "pull_request_number": 2610,
                "branch": "agent/2609-open-only-bug-candidates",
                "head_sha": "a" * 40,
            }
        ],
    )
    assert result["action"] == "reuse-existing-primary-pr"
    assert result["creation_admitted"] is False
    assert result["existing_pull_request_number"] == 2610
    assert result["github_writes_authorized"] is False


def test_primary_pr_creation_tool_fails_closed_on_2609_duplicate_reproduction() -> None:
    result = mcp_server.admit_agent_os_primary_pr_creation_tool(
        issue_number=2609,
        issue_open=True,
        evidence_current=True,
        active_primary_prs=[
            {
                "pull_request_number": 2610,
                "branch": "agent/2609-open-only-bug-candidates",
                "head_sha": "a" * 40,
            },
            {
                "pull_request_number": 2611,
                "branch": "agent/2609-open-only-bug-selection",
                "head_sha": "b" * 40,
            },
        ],
    )
    assert result["action"] == "manual-reconciliation"
    assert result["creation_admitted"] is False
    assert result["reason_codes"] == ["primary-pr.multiple-active"]
    assert result["github_writes_authorized"] is False


def test_2447_batch_packaging_tool_rejects_a_second_execution_wave() -> None:
    """#2688-#2695 reproduction, through the real creation-admission call path."""
    first_wave = mcp_server.admit_agent_os_batch_pr_packaging_tool(
        issue_evidence=[
            {
                "issue_number": 2688,
                "issue_open": True,
                "objective_ref": "objective/lp4-zero-comparable-runs",
                "active_primary_prs": [],
            }
        ],
        evidence_current=True,
    )
    assert first_wave["packaging_admitted"] is True
    assert first_wave["per_issue"][0]["action"] == "create-primary-pr"

    second_wave = mcp_server.admit_agent_os_batch_pr_packaging_tool(
        issue_evidence=[
            {
                "issue_number": 2688,
                "issue_open": True,
                "objective_ref": "objective/lp4-zero-comparable-runs",
                "active_primary_prs": [
                    {
                        "pull_request_number": 2703,
                        "branch": "agent/2688-lp-fix",
                        "head_sha": "6" * 40,
                    }
                ],
            }
        ],
        evidence_current=True,
    )
    assert second_wave["packaging_admitted"] is False
    assert second_wave["per_issue"][0]["action"] == "reuse-existing-primary-pr"
    assert second_wave["per_issue"][0]["existing_pull_request_number"] == 2703
    assert second_wave["github_writes_authorized"] is False


def test_2447_batch_packaging_tool_keeps_independent_issues_on_separate_prs() -> None:
    result = mcp_server.admit_agent_os_batch_pr_packaging_tool(
        issue_evidence=[
            {
                "issue_number": 2442,
                "issue_open": True,
                "objective_ref": "objective/candidate-packet-identity",
                "active_primary_prs": [],
            },
            {
                "issue_number": 2443,
                "issue_open": True,
                "objective_ref": "objective/candidate-packet-transport",
                "active_primary_prs": [],
            },
        ],
        evidence_current=True,
    )
    assert result["packaging_admitted"] is False
    assert result["reason_codes"] == ["primary-pr.independent-issues-require-separate-prs"]
    assert [item["action"] for item in result["per_issue"]] == [
        "create-primary-pr",
        "create-primary-pr",
    ]


def test_unbound_current_surface_is_projected_without_claiming_source_unavailable(monkeypatch) -> None:
    monkeypatch.delenv(LESSONS_LEARNED_DATA_SOURCE_ENV, raising=False)
    execute_read, status, reason, source_unavailable = mcp_server._lesson_route(None)
    assert execute_read is None
    assert status == "current-surface-unbound"
    assert reason == "connector-surface-unavailable"
    assert source_unavailable is False


def test_diagnostic_rows_do_not_depend_on_current_surface_binding(monkeypatch) -> None:
    monkeypatch.delenv(LESSONS_LEARNED_DATA_SOURCE_ENV, raising=False)
    execute_read, status, reason, source_unavailable = mcp_server._lesson_route([{"id": "fixture"}])
    assert execute_read is not None
    assert execute_read({}) == {"results": [{"id": "fixture"}]}
    assert status == "diagnostic-override"
    assert reason == "diagnostic-lesson-rows"
    assert source_unavailable is False


def test_2781_not_needed_issue_start_does_not_resolve_lesson_route(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        mcp_server,
        "resolve_lesson_read_route",
        lambda: calls.append("resolved") or (_ for _ in ()).throw(
            AssertionError("not-needed CKR6 must not resolve the Notion lesson route")
        ),
    )

    result = mcp_server.activate_agent_os_issue_start_lessons_tool(
        repository="Blummer92/agent-os",
        issue_number=2781,
        task_reference="issue:#2781",
        specialized_knowledge_required=False,
    )

    assert calls == []
    assert result["lesson_retrieval_status"] == "not-needed"
    assert result["lesson_read_route_status"] == "not-needed"
    assert result["lesson_read_route_reason_code"] == "lesson-retrieval-not-required"


def test_2781_required_issue_start_resolves_lesson_route_once(monkeypatch) -> None:
    calls = []

    class Route:
        status = type("Status", (), {"value": "configured-canonical-reader"})()
        reason_code = "configured-canonical-reader"
        canonical_source_unavailable = False

        @staticmethod
        def execute_read(_query):
            return {"results": []}

    monkeypatch.setattr(
        mcp_server,
        "resolve_lesson_read_route",
        lambda: calls.append("resolved") or Route(),
    )

    result = mcp_server.activate_agent_os_issue_start_lessons_tool(
        repository="Blummer92/agent-os",
        issue_number=2781,
        task_reference="issue:#2781",
        specialized_knowledge_required=True,
    )

    assert calls == ["resolved"]
    assert result["lesson_read_route_status"] == "configured-canonical-reader"


def test_issue_batch_completion_tool_requires_pr_or_explicit_no_pr_terminal_proof() -> None:
    result = mcp_server.classify_agent_os_issue_batch_completion_tool(
        repository="Blummer92/agent-os",
        issue_number=2607,
        lane_evidence=[
            {
                "issue_number": 2600,
                "current_state": "open-ready",
                "repository_gap": "yes",
                "implementation_authorized": True,
                "pr_required": "yes",
                "pr_number": 2606,
                "remaining_owner": "GitHub Service Agent",
                "branch_exists": True,
                "implementation_commit_count": 1,
                "draft_pr_exists": True,
                "canonical_pr_readback_verified": True,
                "capable_route_available": True,
                "subordinate_writes_only": False,
            },
            {
                "issue_number": 1386,
                "current_state": "open-external-boundary",
                "repository_gap": "no",
                "implementation_authorized": False,
                "pr_required": "no",
                "no_pr_reason": "external-only",
                "canonical_no_pr_evidence_verified": True,
                "remaining_owner": "ChatGPT Orchestrator",
            },
        ],
    )
    assert result["terminal"] is True
    assert result["agent_os_continuation"]["terminal"] is True
    assert result["github_writes_authorized"] is False


def test_investigation_completion_tool_continues_after_checkpoint_when_branch_remains() -> None:
    result = mcp_server.classify_agent_os_investigation_completion_tool(
        repository="Blummer92/agent-os",
        issue_number=2522,
        material_branch_states=("resolved-supported", "in-progress"),
        executable_next_action_available=True,
        subordinate_write_performed=True,
    )
    assert result["completion_admissible"] is False
    assert result["agent_os_continuation"]["terminal"] is False
    assert result["agent_os_continuation"]["blocked"] is False
    assert result["agent_os_continuation"]["action"] == "continue-same-lineage-investigation"
    assert result["github_writes_authorized"] is False


def test_mcp_main_runs_existing_server_over_stdio(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    def fake_run(**kwargs: object) -> None:
        calls.append(kwargs)
    monkeypatch.setattr(mcp_server.mcp, "run", fake_run)
    mcp_server.main()
    assert calls == [{"transport": "stdio"}]


def test_mcp_main_does_not_register_additional_tools() -> None:
    source = inspect.getsource(mcp_server.main)
    assert "mcp.run" in source
    assert "mcp.tool" not in source


def test_blocked_investigation_completion_preserves_existing_next_action() -> None:
    result = mcp_server.classify_agent_os_investigation_completion_tool(
        repository="Blummer92/agent-os",
        issue_number=2522,
        material_branch_states=("resolved-supported", "in-progress"),
        executable_next_action_available=False,
        subordinate_write_performed=True,
    )
    assert result["completion_admissible"] is False
    assert result["next_action"] == "report-investigation-blocker-with-clearing-condition"
    assert result["agent_os_continuation"]["terminal"] is False
    assert result["agent_os_continuation"]["blocked"] is True
    assert result["agent_os_continuation"]["action"] == result["next_action"]
