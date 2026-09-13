"""#2220 runtime conformance for the existing Agent OS MCP continuation seam.

This fixture deliberately lives in the already-governed remote-validation suite.
It adds no VM command, ingress vocabulary, retry loop, or continuation mechanism.
The GCE runner executes this exact repository-owned suite and therefore proves
that the runtime checkout can load the real MCP binding and project an unfinished
mission as non-terminal structured continuation evidence.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTION_SERVICE_SRC = ROOT / "08_Tooling" / "agent-os-execution-service" / "src"
SCHEDULER_SRC = ROOT / "08_Tooling" / "workflow-scheduler" / "src"
MEMORY_SRC = ROOT / "08_Tooling" / "agent-memory-context-manager" / "src"
for source_root in (EXECUTION_SERVICE_SRC, SCHEDULER_SRC, MEMORY_SRC, ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from agent_os_execution_service.mcp_server import classify_agent_os_mission_completion_tool


def test_vm_runtime_mcp_projects_unfinished_mission_as_non_terminal() -> None:
    result = classify_agent_os_mission_completion_tool(
        repository="Blummer92/agent-os",
        issue_number=2220,
        branch_exists=True,
        implementation_commit_count=1,
        draft_pr_exists=False,
        canonical_pr_readback_verified=False,
        capable_route_available=True,
        subordinate_writes_only=False,
    )

    assert result["completion_admissible"] is False
    assert result["next_action"] == "continue-same-lineage-on-capable-implementation-route"
    continuation = result["agent_os_continuation"]
    assert continuation["terminal"] is False
    assert continuation["blocked"] is False
    assert continuation["stalled"] is False
    assert continuation["action"] == "continue-same-lineage-on-capable-implementation-route"
    assert continuation["execution_authorized"] is False
    assert continuation["github_writes_authorized"] is False
    assert continuation["side_effects_performed"] is False


def test_vm_runtime_mcp_projects_completed_delivery_as_terminal() -> None:
    result = classify_agent_os_mission_completion_tool(
        repository="Blummer92/agent-os",
        issue_number=2220,
        branch_exists=True,
        implementation_commit_count=1,
        draft_pr_exists=True,
        canonical_pr_readback_verified=True,
        capable_route_available=True,
        subordinate_writes_only=False,
    )

    assert result["completion_admissible"] is True
    continuation = result["agent_os_continuation"]
    assert continuation["terminal"] is True
    assert continuation["blocked"] is False
    assert continuation["action"] == ""
