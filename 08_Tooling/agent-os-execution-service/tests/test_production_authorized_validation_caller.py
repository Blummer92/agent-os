"""Bounded caller coverage for Issue #1929."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXEC_SERVICE_SRC = REPOSITORY_ROOT / "08_Tooling/agent-os-execution-service/src"
SCHEDULER_SRC = REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src"
for path in (REPOSITORY_ROOT, EXEC_SERVICE_SRC, SCHEDULER_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_os_execution_service import production_authorized_validation_caller as caller  # noqa: E402


def test_caller_reuses_existing_owners_and_delegates_once() -> None:
    source = inspect.getsource(caller.run_production_authorized_validation)
    assert source.count("run_production_authorized_validation_with_source_capture(") == 1
    assert "reconstruct_authorized_validation_lifecycle_request(payload)" in source
    assert "pilot_reconstruction_evidence(request)" in source
    assert "reacquire_execution_authorization(" in source
    assert "prepare_candidate_packet(" in source
    assert "runtime.verify(pilot)" in source


def test_caller_requires_vnext_and_current_authorization_before_delegation() -> None:
    source = inspect.getsource(caller.run_production_authorized_validation)
    assert "AUTHORIZED_VALIDATION_VNEXT_SCHEMA_VERSION" in source
    assert "ExecutionAuthorizationSourceStatus.CURRENT" in source
    assert "expected_authorization_id=request.execution_authorization.authorization_id" in source
    assert "authorization.evidence != request.execution_authorization" in source


def test_caller_adds_no_new_execution_or_persistence_system() -> None:
    source = inspect.getsource(caller)
    forbidden = (
        "subprocess.run(",
        "sqlite3",
        "requests.",
        "urllib",
        "publish_authorized_validation_handoff(",
        "append_pre_publication_evidence(",
        "acquire_lease",
        "release_lease",
        "Scheduler(",
    )
    for token in forbidden:
        assert token not in source


def test_complete_pilot_input_is_not_serialized_or_persisted() -> None:
    source = inspect.getsource(caller)
    assert "serialize_single_issue" not in source
    assert "persist_single_issue" not in source
    assert "json.dump" not in source
    assert "json.dumps" not in source
