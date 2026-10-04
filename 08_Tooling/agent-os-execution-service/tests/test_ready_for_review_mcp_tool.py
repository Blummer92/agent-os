"""Focused #3279 tests: Ready-for-Review admission exposed as an MCP tool.

The #3157 fix added `evaluate_ready_for_review_admission` but no production
surface called it, so the accidental #2772 closure (negated closing phrase in
PR #3156) could recur at the Draft -> Ready transition. These tests prove the
thin MCP tool `admit_agent_os_ready_for_review_tool` now covers that
transition: it binds the exact head SHA and the PR body revision, refuses the
verbatim #3156 negated closing phrase with a named reason, lets `Part of` /
`Refs`-only linkage pass, and introduces no new closing-reference parser.
"""

from __future__ import annotations

import inspect
import re

from agent_os_execution_service import mcp_server

HEAD = "a" * 40

# Verbatim excerpt of PR #3156's "## Linked issue" section: a `Part of` linkage
# plus the negated closing phrase that GitHub treated as effective (#2772).
NEGATED_3156_BODY = (
    "Part of #2772. This PR deliberately does **not** close #2772: its remaining "
    "candidates stay blocked or decision-gated (see #2772 comment 5917898623)."
)


def _ready_kwargs(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "repository": "Blummer92/agent-os",
        "pr_number": 3156,
        "pr_lifecycle_state": "draft",
        "expected_head_sha": HEAD,
        "observed_head_sha": HEAD,
        "validation_head_sha": HEAD,
        "validation_admission_mode": "draft-final-candidate",
        "aggregate_status": "success",
        "focused_status": "success",
        "requested_changes": False,
        "blocking_unresolved": 0,
        "ready_for_review_authority_supplied": True,
        "pr_title": "#2772 Retire Wave 1 zero-consumer execution-interface paths",
        "pr_body": "",
    }
    values.update(overrides)
    return values


def _closure_evidence(
    issue_number: int = 2772, repository: str = "Blummer92/agent-os"
) -> dict[str, object]:
    """Canonical close-issue authorization evidence for one issue (#3157)."""
    return {
        "repository": repository,
        "issue_number": issue_number,
        "authorizer_id": "test-authorizer",
        "decision_id": "test-decision",
        "observed_at_revision": "rev-1",
    }


def test_3279_gap_no_mcp_tool_covers_ready_transition() -> None:
    """#3279 reproduction: the #3157 evaluator had no production caller.

    Before the fix this fails: no registered MCP tool routes through
    `evaluate_ready_for_review_admission`, so nothing covers the Draft -> Ready
    transition.
    """
    source = inspect.getsource(mcp_server)
    tool_blocks = re.split(r"(?=@mcp\.tool\(\))", source)
    covering = [
        block
        for block in tool_blocks
        if block.startswith("@mcp.tool()")
        and "evaluate_ready_for_review_admission" in block
    ]
    assert covering, (
        "#3279: no registered MCP tool covers the Draft->Ready transition"
    )


def test_3279_tool_registered_on_mcp_surface() -> None:
    source = inspect.getsource(mcp_server)
    assert re.search(
        r"@mcp\.tool\(\)\s*\ndef admit_agent_os_ready_for_review_tool\(", source
    ), "#3279: admit_agent_os_ready_for_review_tool is not a registered MCP tool"


def test_3279_negated_3156_closing_phrase_refused_with_named_reason() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(pr_body=NEGATED_3156_BODY)
    )
    assert result["transition_admissible"] is False
    assert "unauthorized-closing-reference" in result["reason_codes"]
    assert result["next_action"] == "authorize-issue-closure-before-ready"
    assert result["issue_closure_authorized"] is False
    assert result["merge_authorized"] is False


def test_3279_authorized_closing_reference_permits_ready_transition() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(
            pr_body=NEGATED_3156_BODY,
            closure_admissions=[_closure_evidence(2772)],
        )
    )
    assert result["transition_admissible"] is True
    assert "unauthorized-closing-reference" not in result["reason_codes"]
    assert result["authorized_closing_targets"] == ["#2772"]
    # The Ready gate projects admissibility only; it grants no authority.
    assert result["issue_closure_authorized"] is False
    assert result["merge_authorized"] is False


def test_3279_part_of_linkage_passes_without_closure_authorization() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(pr_body="Part of #2772. Remaining candidates stay blocked.")
    )
    assert result["transition_admissible"] is True
    assert "unauthorized-closing-reference" not in result["reason_codes"]


def test_3279_refs_only_linkage_passes_without_closure_authorization() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(pr_body="Refs #2772 for context on the remaining candidates.")
    )
    assert result["transition_admissible"] is True
    assert "unauthorized-closing-reference" not in result["reason_codes"]


def test_3279_exact_head_binding_refuses_drift() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(observed_head_sha="b" * 40)
    )
    assert result["transition_admissible"] is False
    assert "exact-head-drift" in result["reason_codes"]
    assert result["next_action"] == "reacquire-current-head-and-validation"


def test_3279_stale_validation_head_refused_with_named_reason() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(validation_head_sha="c" * 40)
    )
    assert result["transition_admissible"] is False
    assert "stale-validation-head" in result["reason_codes"]


def test_3279_matching_body_revision_is_bound() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(
            expected_body_revision="rev-9", observed_body_revision="rev-9"
        )
    )
    assert result["transition_admissible"] is True
    assert result["expected_body_revision"] == "rev-9"
    assert result["observed_body_revision"] == "rev-9"


def test_3279_stale_body_revision_refused_with_named_reason() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(
            expected_body_revision="rev-9", observed_body_revision="rev-10"
        )
    )
    assert result["transition_admissible"] is False
    assert result["reason_codes"] == ["stale-body-revision"]
    assert result["next_action"] == "reacquire-pr-body-revision"
    assert result["issue_closure_authorized"] is False
    assert result["merge_authorized"] is False


def test_3279_missing_observed_body_revision_refused() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(expected_body_revision="rev-9", observed_body_revision=None)
    )
    assert result["transition_admissible"] is False
    assert "stale-body-revision" in result["reason_codes"]


def test_3279_unverifiable_closure_evidence_fails_closed() -> None:
    evidence = _closure_evidence(2772)
    del evidence["authorizer_id"]
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(
            pr_body=NEGATED_3156_BODY,
            closure_admissions=[evidence],
        )
    )
    assert result["transition_admissible"] is False
    assert result["reason_codes"] == ["closure-authorization-evidence-invalid"]
    assert result["next_action"] == "supply-canonical-closure-authorization-evidence"


def test_3279_result_grants_no_authority() -> None:
    result = mcp_server.admit_agent_os_ready_for_review_tool(
        **_ready_kwargs(
            pr_body=NEGATED_3156_BODY,
            closure_admissions=[_closure_evidence(2772)],
        )
    )
    assert result["transition_admissible"] is True
    for flag in (
        "ready_for_review_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "workflow_authorized",
        "protected_setting_authorized",
        "production_authorized",
        "external_system_write_authorized",
    ):
        assert result[flag] is False


def test_3279_no_new_closing_reference_parser_introduced() -> None:
    """The MCP layer must not duplicate `detect_github_effective_closing_references`."""
    source = inspect.getsource(mcp_server)
    assert "def detect_github_effective_closing_references" not in source
    assert "_GITHUB_EFFECTIVE_CLOSING_RE" not in source
    assert "from scripts.agent_os_issue_acceptance.parse_pr import" not in source
    assert "import scripts.agent_os_issue_acceptance.parse_pr" not in source
