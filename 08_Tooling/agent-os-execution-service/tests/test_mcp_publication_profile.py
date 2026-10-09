"""#3372: opt-in ChatGPT publication exposes only the approved governance tools."""

from __future__ import annotations

import asyncio

import pytest
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from agent_os_execution_service.mcp_server import (
    _CHATGPT_PUBLICATION_TOOLS,
    _apply_chatgpt_publication_profile,
)


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
