from __future__ import annotations

import inspect
import re

from agent_os_execution_service import mcp_server


# Exact bounded MCP surface. A bare count drifts silently when a governed tool is
# added; pinning the allowlist by name names the offender instead (#2154 mission).
EXPECTED_TOOLS = frozenset(
    {
        "plan_agent_os_continuation_tool",
        "activate_agent_os_issue_start_lessons_tool",
        "activate_agent_os_failed_repair_tool",
        "admit_agent_os_failed_repair_tool",
        "classify_agent_os_mission_completion_tool",
        "classify_agent_os_continuation_tool",
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
