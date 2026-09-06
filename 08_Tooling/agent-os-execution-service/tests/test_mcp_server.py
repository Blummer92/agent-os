from __future__ import annotations

import inspect

from agent_os_execution_service import mcp_server


def test_mcp_server_exposes_only_bounded_agent_os_tools() -> None:
    source = inspect.getsource(mcp_server)
    assert source.count("@mcp.tool()") == 2
    assert "plan_agent_os_continuation_tool" in source
    assert "classify_agent_os_continuation_tool" in source


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
