"""#3489: MCP publication of the governed issue-closure admission gate.

The closure tools are verify-only host bindings over the canonical
`closure_admission_actions` implementation: they evaluate and verify
admission receipts over host-supplied evidence, perform no GitHub write,
and name the fixed host dispatch contract only after affirmative
verification.
"""

from __future__ import annotations

import asyncio
import copy

from agent_os_execution_service import mcp_server
from agent_os_execution_service.mcp_server import (
    _CHATGPT_PUBLICATION_TOOLS,
    admit_agent_os_issue_closure_tool,
    verify_agent_os_issue_closure_admission_tool,
)
from scripts.agent_os_issue_acceptance.closure_admission_actions import (
    ClosureAcceptanceEvidence,
    IssueClosureRequest,
    evaluate_issue_closure,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_authorization import (
    LifecycleOwnerDecision,
    produce_lifecycle_mutation_authorization,
)
from scripts.agent_os_issue_acceptance.lifecycle_mutation_guard import (
    LifecycleStateSnapshot,
)

REPO = "Blummer92/agent-os"


def snapshot_dict(issue=3432, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        source_head=None,
        base_head=None,
        pr_state="none",
        merged=False,
        issue_state="open",
        review_state="clear",
        unresolved_threads=0,
        lifecycle_labels=[],
        observed_revision=f"rev-{issue}-1",
    )
    data.update(changes)
    return data


def decision_dict(issue=3432, **changes):
    data = dict(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=["close-issue"],
        authorizer_id="repository-owner",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )
    data.update(changes)
    return data


def acceptance_dict(issue=3432, **changes):
    data = dict(
        verdict="pass",
        evidence_id=f"qa-evidence-{issue}",
        evaluator_id="independent-qa",
    )
    data.update(changes)
    return data


def _snapshot(issue=3432, **changes):
    data = snapshot_dict(issue)
    data["lifecycle_labels"] = tuple(data["lifecycle_labels"])
    data.update(changes)
    return LifecycleStateSnapshot(**data)


def _authorization(issue=3432):
    decision = LifecycleOwnerDecision(
        repository=REPO,
        issue_number=issue,
        pull_request_number=None,
        requested_mutations=("close-issue",),
        authorizer_id="repository-owner",
        decision_id=f"owner-decision-{issue}",
        decision_recorded=True,
    )
    return produce_lifecycle_mutation_authorization(decision, _snapshot(issue))


def _admitted_receipt(issue=3432):
    request = IssueClosureRequest(
        decision=LifecycleOwnerDecision(
            repository=REPO,
            issue_number=issue,
            pull_request_number=None,
            requested_mutations=("close-issue",),
            authorizer_id="repository-owner",
            decision_id=f"owner-decision-{issue}",
            decision_recorded=True,
        ),
        acceptance=ClosureAcceptanceEvidence(
            verdict="pass",
            evidence_id=f"qa-evidence-{issue}",
            evaluator_id="independent-qa",
        ),
    )
    return evaluate_issue_closure(request, _snapshot(issue))


def test_evaluate_tool_returns_canonical_receipt_verbatim():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(), acceptance_dict(), snapshot_dict()
    )
    assert receipt == _admitted_receipt()
    assert receipt["admitted"] is True
    assert receipt["closure_performed"] is False
    assert receipt["next_action"] == "host-close-issue-then-canonical-readback"


def test_verify_tool_affirms_exact_receipt_and_names_dispatch_contract():
    receipt = _admitted_receipt()
    result = verify_agent_os_issue_closure_admission_tool(
        REPO,
        3432,
        receipt,
        _authorization().to_dict(),
        snapshot_dict(),
        acceptance_dict(),
    )
    assert result["verified"] is True
    assert result["closure_performed"] is False
    assert result["github_writes_authorized"] is False
    contract = result["host_dispatch_contract"]
    assert contract["tool"] == "issue_write"
    assert contract["chatgpt_connector_tool"] == "update_issue"
    assert contract["method"] == "update"
    assert contract["state"] == "closed"
    assert contract["state_reason"] == "completed"
    assert contract["gate"] == "verify_closure_admission_receipt"


def test_verify_tool_rejects_forged_receipt_with_recomputed_id():
    receipt = _admitted_receipt()
    forged = copy.deepcopy(receipt)
    # Swap in a different (real, admitted) issue's identity and recompute
    # nothing: the receipt id no longer matches its core.
    forged["issue_number"] = 3306
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, forged, _authorization().to_dict(), snapshot_dict(), acceptance_dict()
    )
    assert result["verified"] is False
    assert result["host_dispatch_contract"] is None


def test_verify_tool_rejects_synthetic_receipt_that_never_passed_evaluation():
    # A self-consistent synthetic receipt (valid id over invented core) must
    # still fail: the gate recomputes admission from the authorization.
    receipt = _admitted_receipt()
    synthetic = copy.deepcopy(receipt)
    synthetic["authorization_id"] = "lifecycle-authorization:" + "0" * 64
    from scripts.agent_os_issue_acceptance.closure_admission_actions import _receipt_id

    core = {k: synthetic[k] for k in synthetic if k not in ("receipt_id", "closure_performed", "merge_authorized", "side_effects_performed")}
    synthetic["receipt_id"] = _receipt_id(core)
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, synthetic, _authorization().to_dict(), snapshot_dict(), acceptance_dict()
    )
    assert result["verified"] is False


def test_verify_tool_rejects_stale_snapshot():
    receipt = _admitted_receipt()
    stale = snapshot_dict(observed_revision="rev-3432-2")
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, receipt, _authorization().to_dict(), stale, acceptance_dict()
    )
    assert result["verified"] is False


def test_verify_tool_rejects_cross_issue_substitution():
    receipt = _admitted_receipt(issue=3306)
    result = verify_agent_os_issue_closure_admission_tool(
        REPO,
        3432,
        receipt,
        _authorization(issue=3432).to_dict(),
        snapshot_dict(issue=3432),
        acceptance_dict(issue=3432),
    )
    assert result["verified"] is False


def test_evaluate_tool_refuses_protected_target():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3292, decision_dict(issue=3292), acceptance_dict(issue=3292), snapshot_dict(issue=3292)
    )
    assert receipt["admitted"] is False
    assert "closure.protected-target" in receipt["reason_codes"]


def test_verify_tool_refuses_protected_target():
    receipt = _admitted_receipt()
    result = verify_agent_os_issue_closure_admission_tool(
        REPO,
        3292,
        receipt,
        _authorization().to_dict(),
        snapshot_dict(issue=3292),
        acceptance_dict(),
    )
    assert result["verified"] is False


def test_evaluate_tool_refuses_missing_acceptance():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(), acceptance_dict(verdict="missing"), snapshot_dict()
    )
    assert receipt["admitted"] is False
    assert "closure.acceptance-not-passed" in receipt["reason_codes"]


def test_evaluate_tool_refuses_self_acceptance():
    receipt = admit_agent_os_issue_closure_tool(
        REPO,
        3432,
        decision_dict(),
        acceptance_dict(evaluator_id="repository-owner"),
        snapshot_dict(),
    )
    assert receipt["admitted"] is False
    assert "closure.acceptance-not-independent" in receipt["reason_codes"]


def test_evaluate_tool_refuses_unrecorded_owner_decision():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(decision_recorded=False), acceptance_dict(), snapshot_dict()
    )
    assert receipt["admitted"] is False
    assert "closure.authorization-not-recorded" in receipt["reason_codes"]


def test_tools_fail_closed_on_malformed_evidence():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, {"repository": REPO}, acceptance_dict(), snapshot_dict()
    )
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure-evidence-invalid"]
    result = verify_agent_os_issue_closure_admission_tool(
        REPO, 3432, {}, {"repository": REPO}, snapshot_dict(), acceptance_dict()
    )
    assert result["verified"] is False
    assert result["reason_codes"] == ["closure-verification-evidence-invalid"]


def test_tools_fail_closed_on_target_binding_mismatch():
    receipt = admit_agent_os_issue_closure_tool(
        REPO, 3432, decision_dict(issue=3306), acceptance_dict(), snapshot_dict()
    )
    assert receipt["admitted"] is False
    assert receipt["reason_codes"] == ["closure-target-binding-mismatch"]


def test_closure_tools_are_in_publication_profile():
    assert "admit_agent_os_issue_closure_tool" in _CHATGPT_PUBLICATION_TOOLS
    assert "verify_agent_os_issue_closure_admission_tool" in _CHATGPT_PUBLICATION_TOOLS
    registered = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert _CHATGPT_PUBLICATION_TOOLS <= registered
