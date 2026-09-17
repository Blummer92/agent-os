from __future__ import annotations

import inspect
import re

from agent_os_execution_service import mcp_server
from agent_os_execution_service.lesson_reader_composition import LESSONS_LEARNED_DATA_SOURCE_ENV

EXPECTED_TOOLS = frozenset(
    {
        "plan_connected_issue_creation_tool",
        "plan_agent_os_continuation_tool",
        "admit_agent_os_primary_pr_creation_tool",
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
