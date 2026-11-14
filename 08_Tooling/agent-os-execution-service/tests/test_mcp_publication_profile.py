"""#3372: opt-in ChatGPT publication exposes only the approved governance tools."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agent_os_execution_service import mcp_server
from agent_os_execution_service.mcp_server import (
    _CHATGPT_CKR6_OPT_IN_PROFILE,
    _CHATGPT_CKR6_OPT_IN_TOOLS,
    _CHATGPT_PUBLICATION_TOOLS,
    _apply_chatgpt_publication_profile,
    _apply_publication_profile,
)


def _nine_tool_fixture_server() -> MCPServer:
    """Fixture server carrying both profiles' tools plus one excluded tool."""
    server = MCPServer("nine-tool-fixture")

    @server.tool()
    def admit_agent_os_issue_comment_mutation_tool() -> str:
        return "comment"

    @server.tool()
    def project_agent_os_lane_post_pr_issue_reconciliation_tool() -> str:
        return "reconciliation"

    @server.tool()
    def admit_agent_os_ready_for_review_tool() -> str:
        return "ready"

    @server.tool()
    def admit_agent_os_issue_closure_tool() -> str:
        return "closure-admission"

    @server.tool()
    def verify_agent_os_issue_closure_admission_tool() -> str:
        return "closure-verify"

    @server.tool()
    def activate_agent_os_issue_start_lessons_tool() -> str:
        return "issue-start"

    @server.tool()
    def activate_agent_os_failed_repair_tool() -> str:
        return "failed-repair"

    @server.tool()
    def admit_agent_os_failed_repair_tool() -> str:
        return "failed-repair-admission"

    @server.tool()
    def consume_agent_os_ckr6_result_tool() -> str:
        return "ckr6-result"

    @server.tool()
    def excluded_tool() -> str:
        return "should-not-run"

    return server


def test_publication_removes_excluded_tools_from_sdk_catalog_and_dispatch() -> None:
    server = MCPServer("publication-fixture")

    @server.tool()
    def admit_agent_os_issue_comment_mutation_tool() -> str:
        return "comment"

    @server.tool()
    def project_agent_os_lane_post_pr_issue_reconciliation_tool() -> str:
        return "reconciliation"

    @server.tool()
    def admit_agent_os_ready_for_review_tool() -> str:
        return "ready"

    @server.tool()
    def admit_agent_os_issue_closure_tool() -> str:
        return "closure-admission"

    @server.tool()
    def verify_agent_os_issue_closure_admission_tool() -> str:
        return "closure-verify"

    @server.tool()
    def excluded_tool() -> str:
        return "should-not-run"

    _apply_chatgpt_publication_profile(server)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == _CHATGPT_PUBLICATION_TOOLS
    assert asyncio.run(server.call_tool("admit_agent_os_ready_for_review_tool", {}))
    with pytest.raises(ToolError, match="Unknown tool: excluded_tool"):
        asyncio.run(server.call_tool("excluded_tool", {}))


def test_publication_fails_closed_if_approved_tool_is_missing() -> None:
    server = MCPServer("incomplete-fixture")

    @server.tool()
    def admit_agent_os_ready_for_review_tool() -> str:
        return "ready"

    with pytest.raises(RuntimeError, match="missing approved tools"):
        _apply_chatgpt_publication_profile(server)


def test_main_refuses_unknown_profile_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_OS_MCP_TOOL_PROFILE", "not-a-real-profile")
    monkeypatch.setattr(
        mcp_server.mcp,
        "run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mcp.run must not start")),
    )
    with pytest.raises(RuntimeError, match="Unrecognized AGENT_OS_MCP_TOOL_PROFILE"):
        mcp_server.main()


def test_main_without_profile_starts_default_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_OS_MCP_TOOL_PROFILE", raising=False)
    started: dict = {}
    monkeypatch.setattr(mcp_server.mcp, "run", lambda **kwargs: started.update(kwargs))
    mcp_server.main()
    assert started == {"transport": "stdio"}


# --- #2425 opt-in CKR6 profile: chatgpt-ckr6-opt-in -------------------------


def test_opt_in_profile_exposes_exactly_the_four_ckr6_tools() -> None:
    server = _nine_tool_fixture_server()
    _apply_publication_profile(server, _CHATGPT_CKR6_OPT_IN_PROFILE)
    assert {tool.name for tool in asyncio.run(server.list_tools())} == _CHATGPT_CKR6_OPT_IN_TOOLS
    assert asyncio.run(server.call_tool("consume_agent_os_ckr6_result_tool", {}))
    with pytest.raises(ToolError, match="Unknown tool: excluded_tool"):
        asyncio.run(server.call_tool("excluded_tool", {}))
    with pytest.raises(ToolError, match="Unknown tool: admit_agent_os_ready_for_review_tool"):
        asyncio.run(server.call_tool("admit_agent_os_ready_for_review_tool", {}))


def test_governance_profile_unchanged_through_generic_applier() -> None:
    server = _nine_tool_fixture_server()
    _apply_publication_profile(server, "chatgpt-governance")
    assert {tool.name for tool in asyncio.run(server.list_tools())} == _CHATGPT_PUBLICATION_TOOLS
    assert _CHATGPT_PUBLICATION_TOOLS == {
        "admit_agent_os_issue_comment_mutation_tool",
        "project_agent_os_lane_post_pr_issue_reconciliation_tool",
        "admit_agent_os_ready_for_review_tool",
        "admit_agent_os_issue_closure_tool",
        "verify_agent_os_issue_closure_admission_tool",
    }
    with pytest.raises(ToolError, match="Unknown tool: consume_agent_os_ckr6_result_tool"):
        asyncio.run(server.call_tool("consume_agent_os_ckr6_result_tool", {}))


def test_profiles_are_disjoint() -> None:
    assert _CHATGPT_PUBLICATION_TOOLS.isdisjoint(_CHATGPT_CKR6_OPT_IN_TOOLS)
    assert len(_CHATGPT_PUBLICATION_TOOLS) == 5
    assert len(_CHATGPT_CKR6_OPT_IN_TOOLS) == 4


def test_main_applies_opt_in_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _nine_tool_fixture_server()
    monkeypatch.setenv("AGENT_OS_MCP_TOOL_PROFILE", _CHATGPT_CKR6_OPT_IN_PROFILE)
    monkeypatch.setattr(mcp_server, "mcp", server)
    started: dict = {}
    monkeypatch.setattr(server, "run", lambda **kwargs: started.update(kwargs))
    mcp_server.main()
    assert started == {"transport": "stdio"}
    assert {tool.name for tool in asyncio.run(server.list_tools())} == _CHATGPT_CKR6_OPT_IN_TOOLS


def test_main_refuses_near_miss_profile_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_OS_MCP_TOOL_PROFILE", "chatgpt-governance-plus-ckr6")
    monkeypatch.setattr(
        mcp_server.mcp,
        "run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("mcp.run must not start")),
    )
    with pytest.raises(RuntimeError, match="Unrecognized AGENT_OS_MCP_TOOL_PROFILE"):
        mcp_server.main()
