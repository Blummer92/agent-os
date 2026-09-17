from __future__ import annotations

import inspect
import re

from agent_os_execution_service import mcp_server
from agent_os_execution_service.lesson_reader_composition import LESSONS_LEARNED_DATA_SOURCE_ENV


# Exact bounded MCP surface. A bare count drifts silently when a governed tool is
# added; pinning the allowlist by name names the offender instead (#2154 mission).
EXPECTED_TOOLS = frozenset(
    {
        "plan_connected_issue_creation_tool",
        "plan_agent_os_continuation_tool",
        "activate_agent_os_issue_start_lessons_tool",
        "activate_agent_os_failed_repair_tool",
        "admit_agent_os_failed_repair_tool",
        "classify_agent_os_mission_completion_tool",
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
