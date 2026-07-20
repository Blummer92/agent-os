from __future__ import annotations

import ast
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.agent_os_issue_acceptance import (  # noqa: E402
    APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
    ApprovedExecutionProjection,
    HandoffCohort,
)
from workflow_scheduler.planning import (  # noqa: E402
    consume_approved_execution_projection,
)

HEAD_SHA = "a" * 40
TESTED_SHA = "b" * 40


def _projection(**changes: object) -> ApprovedExecutionProjection:
    values: dict[str, object] = {
        "schema_version": APPROVED_EXECUTION_PROJECTION_SCHEMA_VERSION,
        "projection_id": "",
        "proposal_version": "0.1.0",
        "proposal_id": "draft-task-proposal:" + "1" * 64,
        "approval_id": "approval:" + "2" * 64,
        "approval_revision": "approval-revision:" + "3" * 64,
        "approval_revision_number": 2,
        "approval_kind": "implementation",
        "approval_state": "approved",
        "approval_authorizer_id": "operator-1",
        "approval_decision_id": "decision-1",
        "approval_decision_at": "2026-07-20T12:10:00Z",
        "approval_expires_at": None,
        "approval_supersedes_id": None,
        "handoff_digest": "4" * 64,
        "graph_digest": "5" * 64,
        "planning_result_digest": "6" * 64,
        "repository": "Blummer92/agent-os",
        "base_branch": "main",
        "evaluated_repository_sha": HEAD_SHA,
        "evaluator_commit_sha": "c" * 40,
        "tested_repository_sha": TESTED_SHA,
        "repository_evidence_type": "synthetic-pr-merge",
        "supplied_node_ids": ("issue-422",),
        "cohort_summaries": (
            HandoffCohort(
                node_ids=("issue-422",),
                classification="parallel-candidate",
                reason_codes=("covered-no-deterministic-conflict",),
            ),
        ),
        "issueplan_current_state_evidence_id": (
            "issueplan-current-state:" + "7" * 64
        ),
        "repository_state_evidence_id": "8" * 64,
        "source_snapshot_fingerprint": "9" * 64,
        "scanner_result_fingerprint": "a" * 64,
        "implementation_contract_fingerprint": "b" * 64,
        "allowed_files": ("08_Tooling/workflow-scheduler/src/",),
        "forbidden_paths": (".github/workflows/",),
        "required_tests": ("python -m pytest",),
        "projected_at": "2026-07-20T12:20:00Z",
    }
    values.update(changes)
    return ApprovedExecutionProjection(**values)


def _consume(projection: object, **changes: object):
    values: dict[str, object] = {
        "expected_repository": "Blummer92/agent-os",
        "expected_base_branch": "main",
        "expected_evaluated_repository_sha": HEAD_SHA,
        "expected_tested_repository_sha": TESTED_SHA,
    }
    values.update(changes)
    return consume_approved_execution_projection(projection, **values)


def test_accepts_valid_projection_without_expanding_authority() -> None:
    projection = _projection()

    result = _consume(
        projection,
        expected_projection_id=projection.projection_id,
        expected_proposal_id=projection.proposal_id,
        expected_approval_id=projection.approval_id,
    )

    assert result.status == "accepted"
    assert result.projection is projection
    assert result.complete is True
    assert result.reason_codes == ()
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.side_effects_performed is False


def test_rejects_non_projection_input() -> None:
    result = _consume({"schema_version": "1.0"})

    assert result.status == "rejected"
    assert result.reason_codes == ("projection.incomplete",)
    assert result.projection is None


def test_blocks_when_required_expectation_is_missing() -> None:
    result = _consume(_projection(), expected_repository=None)

    assert result.status == "blocked"
    assert result.reason_codes == ("projection.lookup-failed",)
    assert result.details == ("expectation:repository:missing",)


def test_rejects_repository_or_branch_identity_mismatch() -> None:
    result = _consume(_projection(), expected_base_branch="release")

    assert result.status == "rejected"
    assert result.reason_codes == ("identity.quarantined",)


def test_marks_sha_binding_mismatch_stale() -> None:
    result = _consume(_projection(), expected_tested_repository_sha="d" * 40)

    assert result.status == "stale"
    assert result.reason_codes == ("validation.stale",)


def test_routes_optional_identity_mismatch_to_needs_decision() -> None:
    result = _consume(_projection(), expected_approval_id="approval:" + "f" * 64)

    assert result.status == "needs-decision"
    assert result.reason_codes == ("projection.lookup-failed",)
    assert result.details == ("approval-id:mismatch",)


def test_result_is_immutable() -> None:
    result = _consume(_projection())

    with pytest.raises(FrozenInstanceError):
        result.status = "blocked"


def test_consumer_has_no_runtime_or_io_imports() -> None:
    source_path = (
        REPOSITORY_ROOT
        / "08_Tooling/workflow-scheduler/src/workflow_scheduler/planning"
        / "projection_consumer.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        node.names[0].name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert imported.isdisjoint(
        {"asyncio", "http", "requests", "socket", "subprocess", "urllib"}
    )
    source = source_path.read_text(encoding="utf-8")
    for forbidden in ("Task(", "Queue(", "Lease(", "dispatch(", "retry("):
        assert forbidden not in source
