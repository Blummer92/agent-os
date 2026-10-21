"""#3502: evidence-backed admission for an owner-approved finite campaign.

Each test maps to the #3502 regression matrix or one of its six Expected
requirements. Bodies are synthetic; readiness is always decided by the
canonical evaluator the projection executes.
"""
from __future__ import annotations

import json

import pytest

from agent_os_execution_service import campaign_item_admission as admission
from agent_os_execution_service.campaign_item_admission import (
    ADMISSION_NOT_COMPLETED,
    ADMITTED,
    VERIFIED_BLOCKER,
    classify_campaign_admission,
    classify_campaign_item_admission,
)
from agent_os_execution_service.issue_batch_completion import classify_issue_batch_completion

_SECTIONS = (
    "Objective and Value",
    "Owner and Source of Truth",
    "Scope and Non-Goals",
    "Allowed files or areas",
    "Required tests, validation, and documentation",
    "Dependencies and blockers",
    "Acceptance criteria",
    "Definition of done",
)


def tier1_body(*, omit: tuple[str, ...] = ()) -> str:
    parts = ["Tier: 1", ""]
    for section in _SECTIONS:
        if section not in omit:
            parts += [f"### {section}", "", f"Bounded {section.lower()} content.", ""]
    parts += [
        "### Documentation impact", "", "docs-not-required", "",
        "### Documentation exemption reason", "", "Pure offline contract change.", "",
        "### Prior scope, duplicate, and supersession review", "", "No duplicate owner exists.", "",
    ]
    return "\n".join(parts)


LEGACY_BODY = "## Scope\nLegacy body that names no tier and no decision fields.\n"


def item(issue: int, **changes) -> dict[str, object]:
    value: dict[str, object] = {
        "issue_number": issue,
        "issue_open": True,
        "issue_body": tier1_body(),
        "observed_labels": ["agent-os", "status:ready"],
        "ckr6": {"route": "in-process", "result_status": "not-needed", "substantial_hypothesis_admissible": True},
        "implementation_authorized": True,
        "concurrency": {"execution_route": "connector-native", "active_primary_prs": []},
        "repository_seam": "identified",
        "repository_seam_refs": ["scripts/example.py"],
        "live_acceptance": "none",
    }
    value.update(changes)
    return value


# Regression row 1: three needs-decision-labelled items with repository-only
# approval -- one genuinely blocked, one stale label backed by canonical READY,
# one independently admitted. Only admitted items progress.
def test_only_admitted_items_progress_in_mixed_campaign() -> None:
    result = classify_campaign_admission([
        item(3498, issue_body=LEGACY_BODY, observed_labels=["status:needs-decision"]),
        item(3499, observed_labels=["status:needs-decision"]),
        item(3500),
    ])
    states = {row["issue_number"]: row["campaign_disposition"] for row in result["items"]}
    assert states == {3498: VERIFIED_BLOCKER, 3499: ADMITTED, 3500: ADMITTED}
    assert result["admitted_issue_numbers"] == [3499, 3500]
    assert result["stop_permitted"] is False
    stale = result["items"][1]
    assert stale["label"]["state"] == "mechanical-drift"
    assert stale["label_mutation_performed"] is False
    assert "label.mechanical-drift-projection-repair-only" in stale["notes"]


# Expected 1: label, missing heading and owner approval never equal READY.
def test_ready_label_and_owner_approval_cannot_make_legacy_body_ready() -> None:
    row = classify_campaign_item_admission(item(1, issue_body=LEGACY_BODY, observed_labels=["status:ready"]))
    assert row["readiness"]["outcome"] == "needs-decision"
    assert row["admission_state"] == VERIFIED_BLOCKER
    assert "readiness.needs-decision" in row["verified_blocker_codes"]
    assert row["label"]["state"] == "conflicting"


# Regression row 2: a missing required field yields exact evaluator evidence.
def test_missing_required_field_reports_exact_evaluator_evidence() -> None:
    row = classify_campaign_item_admission(item(2, issue_body=tier1_body(omit=("Dependencies and blockers",))))
    assert row["readiness"]["outcome"] == "blocked"
    assert row["readiness"]["evaluator"].endswith("evaluate_issue_readiness")
    fields = next(check for check in row["readiness"]["checks"] if check["name"] == "required issue fields")
    assert fields == {
        "name": "required issue fields",
        "status": "fail",
        "evidence": ["missing=dependencies"],
    }
    assert row["owner_decision_required"] == ["Missing required field: dependencies."]


# Expected 4: substantive needs-decision is preserved with the smallest decision.
def test_substantive_needs_decision_is_preserved_with_smallest_owner_decision() -> None:
    row = classify_campaign_item_admission(item(3, issue_body=LEGACY_BODY, observed_labels=["status:needs-decision"]))
    assert row["label"]["state"] == "consistent"
    assert row["owner_decision_required"] == [
        "Choose Tier 0, Tier 1, or Tier 2.",
        "Documentation-impact evidence is missing.",
        "Provide visible prior-scope, duplicate, and supersession review evidence.",
    ]
    assert row["label_mutation_performed"] is False


# Regression row 3: lease language vs live concurrency evidence.
@pytest.mark.parametrize(
    ("route", "lease", "state", "code"),
    [
        ("connector-native", "unavailable", ADMITTED, None),
        ("connector-native", "not-observed", ADMITTED, None),
        ("scheduler", "unavailable", ADMISSION_NOT_COMPLETED, "lease.evidence-unavailable"),
        ("governed-runner", "not-observed", ADMISSION_NOT_COMPLETED, "lease.evidence-unavailable"),
        ("scheduler", "clear", ADMITTED, None),
        ("connector-native", "active", VERIFIED_BLOCKER, "lease.active"),
    ],
)
def test_lease_evidence_is_never_fabricated(route: str, lease: str, state: str, code: str | None) -> None:
    row = classify_campaign_item_admission(
        item(4, concurrency={"execution_route": route, "lease_observation": lease, "active_primary_prs": []})
    )
    assert row["admission_state"] == state
    if code is not None:
        assert code in row["verified_blocker_codes"] + row["unverified_checks"]
    if route == "connector-native" and lease in {"unavailable", "not-observed"}:
        assert row["concurrency"]["lease_authority"] == "not-applicable"
        assert "lease.not-applicable-for-route" in row["notes"]


# Regression row 4: repository seam available, live Canva unavailable.
def test_offline_delivery_is_distinguished_from_live_acceptance() -> None:
    row = classify_campaign_item_admission(item(5, live_acceptance="required-not-authorized"))
    assert row["admission_state"] == ADMITTED
    assert row["offline_delivery_admissible"] is True
    assert row["live_acceptance_pending"] is True
    assert row["external_write_authorized"] is False


# Regression row 5: no consumer seam -> precise blocker, no invented executor.
def test_absent_repository_seam_is_a_precise_verified_blocker() -> None:
    row = classify_campaign_item_admission(item(6, repository_seam="absent-verified", repository_seam_refs=[]))
    assert row["admission_state"] == VERIFIED_BLOCKER
    assert row["verified_blocker_codes"] == ["repository-seam.absent"]
    assert row["lane_evidence"]["no_pr_reason"] == "no-repository-seam"


def test_uninvestigated_seam_is_admission_not_completed() -> None:
    row = classify_campaign_item_admission(item(7, repository_seam="not-investigated", repository_seam_refs=[]))
    assert row["admission_state"] == ADMISSION_NOT_COMPLETED
    assert row["next_action"] == "complete-admission:repository-seam.not-investigated"
    assert row["lane_evidence"] is None


def test_identified_seam_requires_refs() -> None:
    with pytest.raises(ValueError, match="repository_seam_refs"):
        classify_campaign_item_admission(item(8, repository_seam_refs=[]))


# Regression row 6: CKR6/route missing is reason-coded, never a claimed preflight.
@pytest.mark.parametrize(
    ("ckr6", "unverified"),
    [
        ({"route": "not-run"}, "ckr6.not-run"),
        ({"route": "github-ingress", "observation_state": "ingress-failed"}, "ckr6.ingress-failed"),
        ({"route": "github-ingress", "observation_state": "pending"}, "ckr6.pending"),
        ({"route": "github-ingress", "observation_state": "result-not-returned"}, "ckr6.result-not-returned"),
    ],
)
def test_missing_ckr6_result_is_admission_not_completed(ckr6: dict[str, object], unverified: str) -> None:
    row = classify_campaign_item_admission(item(9, ckr6=ckr6))
    assert row["admission_state"] == ADMISSION_NOT_COMPLETED
    assert row["unverified_checks"] == [unverified]
    assert row["ckr6"]["substantial_hypothesis_admissible"] is False


def test_ckr6_admission_cannot_be_asserted_without_a_returned_result() -> None:
    with pytest.raises(ValueError, match="only a returned CKR6 result"):
        classify_campaign_item_admission(item(10, ckr6={
            "route": "github-ingress", "observation_state": "ingress-failed",
            "substantial_hypothesis_admissible": True,
        }))
    with pytest.raises(ValueError, match="must match the canonical result status"):
        classify_campaign_item_admission(item(10, ckr6={
            "route": "in-process", "result_status": "manual-review", "substantial_hypothesis_admissible": True,
        }))


def test_returned_ckr6_refusal_is_a_verified_blocker() -> None:
    row = classify_campaign_item_admission(item(11, ckr6={
        "route": "github-ingress", "observation_state": "result-returned",
        "result_status": "insufficient", "substantial_hypothesis_admissible": False,
    }))
    assert row["verified_blocker_codes"] == ["ckr6.insufficient"]


# Regression row 7: no duplicate PRs, no unauthorized mutation, no merge/closure.
def test_existing_or_conflicting_primary_pr_claims_prevent_duplicates() -> None:
    one = classify_campaign_item_admission(item(12, concurrency={
        "execution_route": "connector-native", "active_primary_prs": [3687],
    }))
    assert one["admission_state"] == ADMITTED
    assert one["next_action"] == "resume-existing-primary-pr"
    two = classify_campaign_item_admission(item(12, concurrency={
        "execution_route": "connector-native", "active_primary_prs": [3687, 3688],
    }))
    assert two["verified_blocker_codes"] == ["claim.multiple-primary"]
    for row in (one, two):
        for flag in ("github_writes_authorized", "merge_authorized", "issue_closure_authorized",
                     "workflow_authorized", "external_write_authorized", "label_mutation_performed"):
            assert row[flag] is False


# Expected 6: an admitted item routes to the governed delivery obligations.
def test_admitted_item_routes_through_github_service_agent_delivery() -> None:
    row = classify_campaign_item_admission(item(13))
    assert row["next_action"] == "route-github-service-agent-branch-draft-pr"
    assert row["delivery_obligations"] == [
        "github-service-agent-writer",
        "one-issue-specific-branch",
        "focused-tests",
        "primary-pr-creation-admission-before-draft-pr",
        "draft-pr",
        "exact-head-readback",
    ]


def test_authorization_and_excluded_surfaces_are_item_local_verified_blockers() -> None:
    row = classify_campaign_item_admission(item(
        14,
        implementation_authorized=False,
        excluded_surfaces={"required": ["workflow", "credentials"], "separately_authorized": ["workflow"]},
    ))
    assert row["verified_blocker_codes"] == [
        "authorization.implementation-not-granted",
        "authorization.excluded-surface:credentials",
    ]
    assert row["lane_evidence"]["no_pr_reason"] == "authorization-blocked"


# Expected 5: item-local blockers never stop independent items; an incomplete
# admission keeps the campaign open; no generic blocked summary.
def test_campaign_continues_past_item_local_blockers_and_names_each_cause() -> None:
    result = classify_campaign_admission([
        item(20, issue_body=LEGACY_BODY),
        item(21, ckr6={"route": "github-ingress", "observation_state": "ingress-failed"}),
        item(22, implementation_authorized=False),
    ])
    assert result["verified_blocker_issue_numbers"] == [20, 22]
    assert result["admission_not_completed_issue_numbers"] == [21]
    assert result["stop_permitted"] is False
    assert result["generic_blocked_summary_permitted"] is False
    causes = [tuple(row["verified_blocker_codes"] + row["unverified_checks"]) for row in result["items"]]
    assert len(set(causes)) == 3
    assert result["next_actions"]["21"] == "complete-admission:ckr6.ingress-failed"


def test_shared_blocker_stops_remaining_items_but_keeps_their_evidence() -> None:
    result = classify_campaign_admission(
        [item(30), item(31, issue_body=LEGACY_BODY)], shared_blockers=["capability"]
    )
    assert [row["campaign_disposition"] for row in result["items"]] == ["blocked-shared", VERIFIED_BLOCKER]
    assert result["stop_permitted"] is True
    assert result["items"][0]["readiness"]["outcome"] == "ready"
    with pytest.raises(ValueError, match="unsupported shared blockers"):
        classify_campaign_admission([item(32)], shared_blockers=["impatience"])


def test_campaign_items_must_be_unique() -> None:
    with pytest.raises(ValueError, match="unique"):
        classify_campaign_admission([item(40), item(40)])


# Only verified blockers become terminal no-PR lanes in the existing #2607
# batch classifier; an incomplete admission cannot be closed out as blocked.
def test_lane_evidence_composes_with_issue_batch_completion() -> None:
    blocked = classify_campaign_item_admission(item(50, issue_body=LEGACY_BODY))
    seamless = classify_campaign_item_admission(item(51, repository_seam="absent-verified", repository_seam_refs=[]))
    unauthorized = classify_campaign_item_admission(item(52, implementation_authorized=False))
    batch = classify_issue_batch_completion(
        repository="Blummer92/agent-os",
        issue_number=3502,
        lane_evidence=[blocked["lane_evidence"], seamless["lane_evidence"], unauthorized["lane_evidence"]],
    )
    assert batch["terminal"] is True
    assert [lane["reason_codes"] for lane in batch["lanes"]] == [
        ["no-pr-terminal:material-decision-required"],
        ["no-pr-terminal:no-repository-seam"],
        ["no-pr-terminal:authorization-blocked"],
    ]
    incomplete = classify_campaign_item_admission(item(53, ckr6={"route": "not-run"}))
    assert incomplete["lane_evidence"] is None


def test_label_projection_mirrors_canonical_managed_labels() -> None:
    from scripts.agent_os_issue_acceptance.issue_operational_state import _MANAGED_READINESS_LABELS

    assert set(admission._LABEL_BY_READINESS.values()) == set(_MANAGED_READINESS_LABELS.values())


def test_closed_issue_is_never_admitted() -> None:
    row = classify_campaign_item_admission(item(60, issue_open=False))
    assert row["verified_blocker_codes"][0] == "issue.not-open"


def test_cli_emits_campaign_projection(tmp_path, capsys) -> None:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"items": [item(70), item(71, issue_body=LEGACY_BODY)]}), encoding="utf-8")
    assert admission.main(["--evidence", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["admitted_issue_numbers"] == [70]
    assert result["verified_blocker_issue_numbers"] == [71]
