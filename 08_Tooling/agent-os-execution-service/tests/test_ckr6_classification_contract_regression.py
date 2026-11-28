"""Regression coverage for CKR6 classification routing and fail-closed contracts.

These tests exercise the production bridge without mutmut-specific setup.
They protect the contract boundaries identified by the 2026-11-08
classification mutation investigation.
"""

from __future__ import annotations

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge


EXPECTED_KEYS = {
    "operation",
    "repository",
    "issue_number",
    "retrieval_required",
    "reason_codes",
    "recommended_escalation",
    "notion_read_performed",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "closure_authorized",
    "side_effects_performed",
}

AUTHORITY_FLAGS = (
    "notion_read_performed",
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "closure_authorized",
    "side_effects_performed",
)


def envelope(operation: str, specialized: bool = False):
    data = {
        "operation": operation,
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
    }
    if operation == "lesson-candidate":
        data["candidate"] = {}
    elif operation == "lesson-refinement":
        data["refinement"] = {}
    else:
        data["specialized_knowledge_required"] = specialized
        if operation == "failed-repair":
            data.update(
                attempt_id="attempt-1",
                failed_hypothesis="prior repair failed",
                result_summary="validation remained red",
                repair_context="failed-pr-repair",
            )
    return bridge.parse_envelope(data)


@pytest.mark.parametrize(
    ("operation", "specialized", "expected_read", "expected_escalation", "expected_reasons"),
    [
        ("issue-start", False, False, "none", ["knowledge-not-needed"]),
        ("issue-start", True, True, "filtered-data-source-query", ["lesson-retrieval-required"]),
        ("failed-repair", False, False, "none", ["knowledge-not-needed"]),
        ("failed-repair", True, True, "filtered-data-source-query", ["lesson-retrieval-required"]),
        ("lesson-candidate", False, False, "none", ["learning-operation:lesson-candidate"]),
        ("lesson-refinement", False, True, "known-reference", ["learning-operation:lesson-refinement"]),
    ],
)
def test_classification_schema_and_safety(
    operation: str,
    specialized: bool,
    expected_read: bool,
    expected_escalation: str,
    expected_reasons: list[str],
):
    result = bridge.classify_envelope(envelope(operation, specialized))

    assert set(result) == EXPECTED_KEYS
    assert result["operation"] == operation
    assert result["repository"] == "Blummer92/agent-os"
    assert result["issue_number"] == 3418

    assert type(result["retrieval_required"]) is bool
    assert result["retrieval_required"] is expected_read

    for flag in AUTHORITY_FLAGS:
        assert result[flag] is False, flag

    assert type(result["reason_codes"]) is list
    assert result["reason_codes"] == expected_reasons

    assert type(result["recommended_escalation"]) is str
    assert result["recommended_escalation"] == expected_escalation


def test_sparse_issue_start_does_not_inherit_failed_repair_context():
    request = bridge.parse_envelope({
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "specialized_knowledge_required": None,
    })

    result = bridge.classify_envelope(request)

    assert result["retrieval_required"] is False
    assert result["recommended_escalation"] == "none"
    assert result["reason_codes"] == ["knowledge-not-needed"]


@pytest.mark.parametrize(
    ("operation", "detail_key"),
    [
        ("lesson-candidate", "candidate"),
        ("lesson-refinement", "refinement"),
    ],
)
def test_learning_operation_reason_code_is_exact(operation: str, detail_key: str):
    request = bridge.parse_envelope({
        "operation": operation,
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        detail_key: {},
    })

    result = bridge.classify_envelope(request)

    assert result["reason_codes"] == [f"learning-operation:{operation}"]


def test_direct_invalid_repair_context_fails_closed():
    # Defense in depth: bypass the ingress parser to exercise the bridge guard.
    request = bridge.Ckr6Envelope(
        operation="failed-repair",
        repository="Blummer92/agent-os",
        issue_number=3418,
        task_reference="issue:#3418",
        repair_context="none",
    )

    with pytest.raises(
        ValueError,
        match=r"^failed-repair must use a repair or CI diagnosis context$",
    ):
        bridge.classify_envelope(request)

@pytest.mark.parametrize(
    ("repair_context", "expected_reason"),
    [
        ("failed-pr-repair", "failed-pr-repair-material-use-evaluation-required"),
        ("ci-diagnosis", "ci-diagnosis-material-use-evaluation-required"),
    ],
)
def test_sparse_failed_repair_forces_material_preflight(
    repair_context: str, expected_reason: str
):
    request = bridge.parse_envelope({
        "operation": "failed-repair",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "attempt_id": "attempt-1",
        "failed_hypothesis": "repair failed",
        "result_summary": "CI still red",
        "repair_context": repair_context,
        "specialized_knowledge_required": None,
    })

    result = bridge.classify_envelope(request)

    assert result["retrieval_required"] is True
    assert result["recommended_escalation"] == "filtered-data-source-query"
    assert result["reason_codes"] == [expected_reason]
    for flag in AUTHORITY_FLAGS:
        assert result[flag] is False


def test_failed_repair_explicit_opt_out_is_not_overridden_by_ci_diagnosis():
    request = bridge.parse_envelope({
        "operation": "failed-repair",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "attempt_id": "attempt-1",
        "failed_hypothesis": "repair failed",
        "result_summary": "CI still red",
        "repair_context": "ci-diagnosis",
        "specialized_knowledge_required": False,
    })

    result = bridge.classify_envelope(request)

    assert result["retrieval_required"] is False
    assert result["recommended_escalation"] == "none"
    assert result["reason_codes"] == ["knowledge-not-needed"]


def test_issue_start_known_reference_is_not_routed_to_filtered_query():
    request = bridge.parse_envelope({
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": 3418,
        "task_reference": "issue:#3418",
        "specialized_knowledge_required": None,
        "known_knowledge_refs": ["LL-71"],
    })

    result = bridge.classify_envelope(request)

    assert result["retrieval_required"] is True
    assert result["recommended_escalation"] == "known-reference"
    assert result["reason_codes"] == ["lesson-known-reference-retrieval-required"]
    for flag in AUTHORITY_FLAGS:
        assert result[flag] is False

