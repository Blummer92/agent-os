"""Production reachability of the stale-head and validation-failure owners (#3280).

``project_validation_head_disposition`` had no production caller and
``classify_validation_failure`` was reached only through the offline
``agent-os-release-run.py`` CLI, which no workflow or registered MCP tool
invokes. Both are now composed by ``evaluate_failed_repair_admission``, which is
reachable from the registered ``admit_agent_os_failed_repair_tool``.

The shared reachability helper only admits ``@mcp.tool`` functions, ``__main__``
guards and the narrow runtime-entrypoint set as roots, so a unit test, an
allow-list entry, a doc, or an uninvoked CLI cannot satisfy these assertions.
"""
from __future__ import annotations

from pathlib import Path

from tests.agent_os_execution_interface.test_continuation_reachability import (
    REPO_ROOT,
    _production_consumers,
)

SERVICE_SRC = REPO_ROOT / "08_Tooling/agent-os-execution-service/src/agent_os_execution_service"
ADMISSION = SERVICE_SRC / "failed_repair_admission.py"
SUPERSESSION = SERVICE_SRC / "validation_supersession.py"
CLASSIFIER = REPO_ROOT / "scripts/agent_os_issue_acceptance/validation_failure_classifier.py"


def _relative(paths: tuple[Path, ...]) -> set[str]:
    return {str(path) for path in paths}


def test_stale_head_owner_is_consumed_by_live_failed_repair_admission() -> None:
    consumers = _relative(_production_consumers("project_validation_head_disposition", SUPERSESSION))
    assert str(ADMISSION.relative_to(REPO_ROOT)) in consumers


def test_validation_failure_classifier_is_consumed_by_live_failed_repair_admission() -> None:
    consumers = _relative(_production_consumers("classify_validation_failure", CLASSIFIER))
    assert str(ADMISSION.relative_to(REPO_ROOT)) in consumers


def test_failed_repair_admission_is_reached_from_the_registered_mcp_tool() -> None:
    consumers = _relative(
        _production_consumers("evaluate_failed_repair_admission", ADMISSION)
    )
    assert "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/mcp_facade.py" in consumers
