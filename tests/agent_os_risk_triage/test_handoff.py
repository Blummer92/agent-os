import ast

import pytest

from scripts.agent_os_risk_triage import (
    Disposition,
    HandoffRoute,
    RiskTriageHandoff,
    RiskTriageResult,
    TargetKind,
    plan_risk_triage_handoff,
)


@pytest.mark.parametrize(
    ("result", "route"),
    [
        (RiskTriageResult(Disposition.NO_ACTION, ("finding.no-action-required",)), HandoffRoute.NO_ACTION),
        (
            RiskTriageResult(
                Disposition.RECORD_IN_CURRENT_WORK,
                ("current-work.match",),
                "pr:10",
                TargetKind.CURRENT_WORK,
                ("supplied",),
            ),
            HandoffRoute.CURRENT_WORK,
        ),
        (
            RiskTriageResult(
                Disposition.LINK_CANONICAL_RISK_OWNER,
                ("canonical-owner.unambiguous",),
                "issue:543",
                TargetKind.CANONICAL_RISK_OWNER,
                ("owner-map",),
            ),
            HandoffRoute.CANONICAL_RISK_OWNER,
        ),
        (
            RiskTriageResult(
                Disposition.UPDATE_EXISTING_ISSUE_CANDIDATE,
                ("existing-issue.match",),
                "issue:10",
                TargetKind.EXISTING_ISSUE,
                ("duplicate-proof",),
            ),
            HandoffRoute.EXISTING_ISSUE,
        ),
        (
            RiskTriageResult(
                Disposition.CREATE_CHILD_ISSUE_CANDIDATE,
                ("child.explicit-relationship",),
                "issue:10",
                TargetKind.EXISTING_ISSUE,
                ("parent-proof",),
            ),
            HandoffRoute.ISSUE_DRAFT_ADMISSION,
        ),
        (
            RiskTriageResult(
                Disposition.CREATE_NEW_ISSUE_CANDIDATE,
                ("finding.no-current-target",),
            ),
            HandoffRoute.ISSUE_DRAFT_ADMISSION,
        ),
        (
            RiskTriageResult(Disposition.NEEDS_DECISION, ("uncertainty.explicit",)),
            HandoffRoute.MANUAL_REVIEW,
        ),
    ],
)
def test_all_seven_dispositions_map_deterministically(result, route):
    assert plan_risk_triage_handoff(result).route is route
    assert plan_risk_triage_handoff(result) == plan_risk_triage_handoff(result)


@pytest.mark.parametrize(
    "disposition,kind,identity,evidence",
    [
        (Disposition.RECORD_IN_CURRENT_WORK, TargetKind.CURRENT_WORK, "pr:10", ("current",)),
        (
            Disposition.LINK_CANONICAL_RISK_OWNER,
            TargetKind.CANONICAL_RISK_OWNER,
            "issue:543",
            ("owner",),
        ),
        (
            Disposition.UPDATE_EXISTING_ISSUE_CANDIDATE,
            TargetKind.EXISTING_ISSUE,
            "issue:10",
            ("existing",),
        ),
        (
            Disposition.CREATE_CHILD_ISSUE_CANDIDATE,
            TargetKind.EXISTING_ISSUE,
            "issue:20",
            ("parent",),
        ),
    ],
)
def test_target_identity_and_evidence_are_preserved(disposition, kind, identity, evidence):
    result = RiskTriageResult(disposition, ("reason",), identity, kind, evidence)
    handoff = plan_risk_triage_handoff(result)
    assert handoff.target_identity == identity
    assert handoff.target_kind is kind
    assert handoff.target_evidence == evidence


@pytest.mark.parametrize(
    "disposition",
    [Disposition.CREATE_NEW_ISSUE_CANDIDATE, Disposition.CREATE_CHILD_ISSUE_CANDIDATE],
)
def test_create_candidates_route_to_existing_contracts_without_authority(disposition):
    kwargs = {}
    if disposition is Disposition.CREATE_CHILD_ISSUE_CANDIDATE:
        kwargs = {
            "target_identity": "issue:10",
            "target_kind": TargetKind.EXISTING_ISSUE,
            "target_evidence": ("parent",),
        }
    handoff = plan_risk_triage_handoff(RiskTriageResult(disposition, ("reason",), **kwargs))
    assert handoff.route is HandoffRoute.ISSUE_DRAFT_ADMISSION
    assert handoff.downstream_contracts == (
        "scripts.agent_os_issue_labels.draft",
        "scripts.agent_os_issue_labels.validation",
        "scripts.agent_os_issue_labels.connected_issue_creation",
    )
    assert handoff.mutation_performed is False
    assert handoff.write_authorized is False


@pytest.mark.parametrize(
    "result",
    [
        RiskTriageResult(Disposition.RECORD_IN_CURRENT_WORK, ("reason",)),
        RiskTriageResult(
            Disposition.UPDATE_EXISTING_ISSUE_CANDIDATE,
            ("reason",),
            "pr:wrong-kind",
            TargetKind.CURRENT_WORK,
            ("evidence",),
        ),
        RiskTriageResult(Disposition.CREATE_CHILD_ISSUE_CANDIDATE, ("reason",)),
        RiskTriageResult(
            Disposition.CREATE_NEW_ISSUE_CANDIDATE,
            ("reason",),
            "issue:unexpected",
            TargetKind.EXISTING_ISSUE,
            ("evidence",),
        ),
        RiskTriageResult(Disposition.NO_ACTION, ()),
        RiskTriageResult(
            Disposition.NO_ACTION,
            ("reason",),
            write_authorized=True,
        ),
    ],
)
def test_missing_or_incompatible_evidence_fails_closed(result):
    handoff = plan_risk_triage_handoff(result)
    assert handoff.route is HandoffRoute.MANUAL_REVIEW
    assert handoff.mutation_performed is False
    assert handoff.write_authorized is False


def test_handoff_result_is_always_non_authorizing():
    assert RiskTriageHandoff(HandoffRoute.NO_ACTION, ("reason",)).mutation_performed is False
    assert RiskTriageHandoff(HandoffRoute.NO_ACTION, ("reason",)).write_authorized is False


def test_handoff_has_no_network_github_or_subprocess_dependencies():
    import scripts.agent_os_risk_triage.handoff as handoff

    tree = ast.parse(open(handoff.__file__, encoding="utf-8").read())
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    forbidden = {"requests", "urllib", "httpx", "subprocess", "github"}
    assert imported_roots.isdisjoint(forbidden)
