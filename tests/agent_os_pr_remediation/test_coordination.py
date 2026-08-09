from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_pr_remediation import (
    EvidenceValidationError,
    NormalizedPRSnapshot,
    NormalizedReviewThread,
    coordinate_resolution,
    plan_remediation,
    preflight,
    serialize_resolution_plan,
)

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "agent_os_pr_remediation" / "coordination.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
PLAN_HEAD = FIXTURE["shas"]["planning"]
CURRENT_HEAD = FIXTURE["shas"]["current"]
LATER_HEAD = FIXTURE["shas"]["later"]
ALLOWED = ("src/a.py", "tests/test_a.py")


def _thread(thread_id: str = "thread-1", *, path: str = "src/a.py") -> NormalizedReviewThread:
    return NormalizedReviewThread(
        thread_id=thread_id,
        top_level_comment_id=1 if thread_id == "thread-1" else 2,
        reviewer="reviewer",
        body_fingerprint=f"body-{thread_id}",
        resolved=False,
        outdated=False,
        superseded=False,
        path=path,
        line=10,
    )


def _snapshot(head: str = PLAN_HEAD) -> NormalizedPRSnapshot:
    return NormalizedPRSnapshot(
        repository="Blummer92/agent-os",
        pr_number=1001,
        base_branch="main",
        head_branch="agent/test",
        head_sha=head,
        state="open",
        merged=False,
        draft=True,
        changed_files=("src/a.py",),
        base_sha="dddddddddddddddddddddddddddddddddddddddd",
    )


def _candidate(
    thread_ids: tuple[str, ...] = ("thread-1",),
    *,
    affected_files: tuple[str, ...] = ("src/a.py",),
    validations: tuple[str, ...] = ("focused-tests", "aggregate-tests"),
    requested_outcome: str = "apply fix",
    already_fixed_head_sha: str | None = None,
    already_fixed_condition_absent: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "finding_identity": "finding-a",
        "rule_id": "rule-a",
        "requested_outcome": requested_outcome,
        "source_thread_ids": list(thread_ids),
        "affected_files": list(affected_files),
        "owner": "implementation-agent",
        "risk": "low",
        "requested_summary": "apply the bounded fix",
        "proposed_validations": list(validations),
        "evidence_basis": ["review-thread"],
    }
    if already_fixed_head_sha is not None:
        payload["already_fixed_head_sha"] = already_fixed_head_sha
    if already_fixed_condition_absent:
        payload["already_fixed_condition_absent"] = True
    return payload


def _context(
    *,
    threads: tuple[NormalizedReviewThread, ...] | None = None,
    candidates: list[dict[str, object]] | None = None,
    allowed: tuple[str, ...] = ALLOWED,
):
    snapshot = _snapshot()
    threads = threads or (_thread(),)
    candidates = candidates or [_candidate(tuple(thread.thread_id for thread in threads))]
    flight = preflight(
        snapshot,
        expected_head=PLAN_HEAD,
        allowed_files=allowed,
        review_threads=threads,
    )
    plan = plan_remediation(snapshot, threads, candidates, allowed)
    return snapshot, threads, flight, plan


def _validation(name: str, *, head: str = CURRENT_HEAD, **overrides: object) -> dict[str, object]:
    payload = dict(FIXTURE["validation"][name])
    payload["expected_sha"] = head
    payload["tested_sha"] = head
    payload.update(overrides)
    return payload


def _fix(plan, *, head: str = CURRENT_HEAD, fixed: bool = True) -> dict[str, object]:
    return {
        "finding_id": plan.findings[0].finding_id,
        "fixed": fixed,
        "head_sha": head,
        "evidence_id": f"fix:{head}",
    }


def _coordinate(
    *,
    context=None,
    current_head: str = CURRENT_HEAD,
    final_head: str = CURRENT_HEAD,
    changed_files: tuple[str, ...] = ("src/a.py",),
    fixes=None,
    validations=None,
):
    snapshot, threads, flight, plan = context or _context()
    if fixes is None:
        fixes = [_fix(plan, head=current_head)]
    if validations is None:
        validations = [
            _validation("focused_pass", head=current_head),
            _validation("aggregate_pass", head=current_head),
        ]
    return coordinate_resolution(
        snapshot,
        threads,
        flight,
        plan,
        changed_files,
        fixes,
        validations,
        current_head_sha=current_head,
        final_captured_head_sha=final_head,
    )


def test_exact_final_head_validation_pass_is_eligible() -> None:
    plan = _coordinate()
    result = plan.thread_results[0]
    assert result.resolution_eligible is True
    assert result.validation_state == "validation-passed"
    assert result.suggested_action == FIXTURE["expected_actions"]["exact_pass"]
    assert result.required_validation_categories == ("aggregate-tests", "focused-tests")


def test_validation_passing_before_later_commit_is_stale() -> None:
    context = _context()
    _, _, _, remediation = context
    plan = _coordinate(
        context=context,
        current_head=LATER_HEAD,
        final_head=LATER_HEAD,
        fixes=[_fix(remediation, head=LATER_HEAD)],
        validations=[
            _validation("aggregate_pass", head=CURRENT_HEAD),
            _validation("focused_pass", head=CURRENT_HEAD),
        ],
    )
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == "validation-stale"
    assert result.suggested_action == "request-more-evidence"


def test_focused_pass_with_aggregate_pending_is_not_complete_success() -> None:
    context = _context(candidates=[_candidate(validations=("focused-tests",))])
    _, _, _, remediation = context
    plan = _coordinate(
        context=context,
        fixes=[_fix(remediation)],
        validations=[_validation("focused_pass")],
    )
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == "validation-incomplete"
    assert result.suggested_action == FIXTURE["expected_actions"]["focused_only"]
    assert "aggregate-validation-pending" in result.ineligibility_reason_codes


def test_unrelated_aggregate_pass_cannot_satisfy_required_focused_pending() -> None:
    context = _context(candidates=[_candidate(validations=("focused-tests",))])
    _, _, _, remediation = context
    plan = _coordinate(
        context=context,
        fixes=[_fix(remediation)],
        validations=[
            _validation("focused_pass"),
            _validation("aggregate_pass"),
        ],
    )
    result = plan.thread_results[0]
    assert result.required_validation_categories == ("focused-tests",)
    assert result.resolution_eligible is False
    assert result.validation_state == "validation-incomplete"
    assert "aggregate-validation-pending" in result.ineligibility_reason_codes


def test_failed_validation_leaves_thread_open() -> None:
    failed = _validation(
        "aggregate_pass",
        execution_status="aggregate-fail",
        reason_codes=["pytest-failed"],
    )
    plan = _coordinate(validations=[_validation("focused_pass"), failed])
    result = plan.thread_results[0]
    assert result.validation_state == "validation-failed"
    assert result.suggested_action == FIXTURE["expected_actions"]["failed"]


@pytest.mark.parametrize(
    ("overrides", "expected_state"),
    [
        ({"evidence_available": False}, "validation-unavailable"),
        ({"evidence_complete": False}, "validation-incomplete"),
        ({"execution_status": "planned"}, "validation-incomplete"),
    ],
)
def test_partial_unavailable_and_planned_validation_fail_closed(overrides, expected_state) -> None:
    focused = _validation("focused_pass")
    aggregate = _validation("aggregate_pass", **overrides)
    plan = _coordinate(validations=[focused, aggregate])
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == expected_state


def test_planned_validation_without_focused_pending_stays_planned() -> None:
    context = _context(candidates=[_candidate(validations=("aggregate-tests",))])
    _, _, _, remediation = context
    plan = _coordinate(
        context=context,
        fixes=[_fix(remediation)],
        validations=[_validation("aggregate_pass", execution_status="planned")],
    )
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == "validation-planned"


@pytest.mark.parametrize("status", ["planned", "unavailable"])
def test_manual_review_profile_dominates_execution_status(status: str) -> None:
    context = _context(candidates=[_candidate(validations=("aggregate-tests",))])
    _, _, _, remediation = context
    plan = _coordinate(
        context=context,
        fixes=[_fix(remediation)],
        validations=[
            _validation(
                "aggregate_pass",
                profile="manual-review",
                execution_status=status,
                aggregate_pending=False,
            )
        ],
    )
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == "manual-review-required"
    assert result.suggested_action == "manual-decision-required"


def test_current_head_differing_from_tested_head_is_stale() -> None:
    aggregate = _validation("aggregate_pass", tested_sha=PLAN_HEAD)
    plan = _coordinate(validations=[_validation("focused_pass"), aggregate])
    assert plan.thread_results[0].validation_state == "validation-stale"


def test_final_head_mismatch_is_explicit() -> None:
    plan = _coordinate(final_head=LATER_HEAD)
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == "final-head-mismatch"
    assert "final-head-does-not-match-current-head" in result.ineligibility_reason_codes


def test_multiple_threads_fixed_by_one_remediation_share_task_identity() -> None:
    threads = (_thread("thread-1"), _thread("thread-2"))
    context = _context(threads=threads, candidates=[_candidate(("thread-1", "thread-2"))])
    _, _, _, remediation = context
    plan = _coordinate(context=context, fixes=[_fix(remediation)])
    assert len(plan.thread_results) == 2
    assert all(result.resolution_eligible for result in plan.thread_results)
    assert plan.thread_results[0].remediation_task_ids == plan.thread_results[1].remediation_task_ids


def test_one_finding_can_require_several_validation_categories() -> None:
    result = _coordinate().thread_results[0]
    assert tuple(item.category for item in result.validation_results) == ("aggregate-tests", "focused-tests")
    assert all(item.state == "validation-passed" for item in result.validation_results)


def test_already_fixed_is_conclusive_only_on_exact_current_head() -> None:
    context = _context(
        candidates=[
            _candidate(
                validations=(),
                already_fixed_head_sha=PLAN_HEAD,
                already_fixed_condition_absent=True,
            )
        ]
    )
    exact = _coordinate(
        context=context,
        current_head=PLAN_HEAD,
        final_head=PLAN_HEAD,
        fixes=[],
        validations=[],
    )
    assert exact.thread_results[0].resolution_eligible is True

    stale = _coordinate(
        context=context,
        current_head=CURRENT_HEAD,
        final_head=CURRENT_HEAD,
        fixes=[],
        validations=[],
    )
    assert stale.thread_results[0].resolution_eligible is False
    assert "already-fixed-evidence-stale" in stale.thread_results[0].ineligibility_reason_codes

    _, _, _, remediation = context
    refreshed = _coordinate(
        context=context,
        current_head=CURRENT_HEAD,
        final_head=CURRENT_HEAD,
        fixes=[_fix(remediation, head=CURRENT_HEAD)],
        validations=[],
    )
    assert refreshed.thread_results[0].resolution_eligible is True


def test_unresolved_conflicting_human_review_requires_manual_decision() -> None:
    candidates = [
        _candidate(requested_outcome="apply behavior A", validations=()),
        _candidate(requested_outcome="apply behavior B", validations=()),
    ]
    context = _context(candidates=candidates)
    plan = _coordinate(context=context, fixes=[], validations=[])
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.suggested_action == FIXTURE["expected_actions"]["conflicting"]
    assert "conflicting-unresolved-finding" in result.ineligibility_reason_codes


def test_out_of_scope_finding_routes_out_of_scope() -> None:
    context = _context(candidates=[_candidate(affected_files=("outside.py",), validations=())])
    plan = _coordinate(context=context, fixes=[], validations=[])
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.suggested_action == FIXTURE["expected_actions"]["out_of_scope"]


def test_changed_file_scope_expansion_fails_closed() -> None:
    plan = _coordinate(changed_files=("src/a.py", "outside.py"))
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.suggested_action == "route-out-of-scope"


def test_missing_validation_category_keeps_eligibility_false() -> None:
    plan = _coordinate(validations=[_validation("focused_pass")])
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert any(item.state == "validation-unavailable" for item in result.validation_results)


def test_passing_validation_never_creates_authority() -> None:
    plan = _coordinate()
    result = plan.thread_results[0]
    assert result.thread_resolved is False
    assert result.execution_authorized is False
    assert result.external_write_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False
    assert plan.thread_resolved is False
    assert plan.execution_authorized is False
    assert plan.external_write_authorized is False
    assert plan.merge_authorized is False
    assert plan.side_effects_performed is False


def test_deterministic_serialization_and_ids() -> None:
    first = _coordinate()
    second = _coordinate()
    assert first == second
    assert first.resolution_plan_id == second.resolution_plan_id
    assert first.canonical_serialization == second.canonical_serialization
    assert serialize_resolution_plan(first)["resolution_plan_id"] == first.resolution_plan_id


def test_malformed_and_oversized_inputs_fail_closed() -> None:
    context = _context()
    snapshot, threads, flight, remediation = context
    with pytest.raises(EvidenceValidationError):
        coordinate_resolution(
            snapshot,
            threads,
            flight,
            remediation,
            ("src/a.py", "src/a.py"),
            [_fix(remediation)],
            [_validation("aggregate_pass")],
            current_head_sha=CURRENT_HEAD,
            final_captured_head_sha=CURRENT_HEAD,
        )
    with pytest.raises(EvidenceValidationError):
        _coordinate(current_head="not-a-sha")
    bad = _validation("aggregate_pass")
    bad["unexpected"] = True
    with pytest.raises(EvidenceValidationError):
        _coordinate(validations=[bad])
    oversized = _validation(
        "aggregate_pass",
        reason_codes=[f"code-{index}" for index in range(65)],
    )
    with pytest.raises(EvidenceValidationError):
        _coordinate(validations=[oversized])


def test_thread_without_associated_finding_requests_more_evidence() -> None:
    snapshot = _snapshot()
    threads = (_thread(), _thread("thread-2"))
    flight = preflight(snapshot, expected_head=PLAN_HEAD, allowed_files=ALLOWED, review_threads=threads)
    remediation = plan_remediation(
        snapshot,
        threads,
        [_candidate(("thread-1",), validations=())],
        ALLOWED,
    )
    plan = coordinate_resolution(
        snapshot,
        threads,
        flight,
        remediation,
        ("src/a.py",),
        [_fix(remediation)],
        [],
        current_head_sha=CURRENT_HEAD,
        final_captured_head_sha=CURRENT_HEAD,
    )
    orphan = next(item for item in plan.thread_results if item.thread_id == "thread-2")
    assert orphan.resolution_eligible is False
    assert orphan.suggested_action == "request-more-evidence"


def test_actionable_finding_without_required_validation_fails_closed() -> None:
    context = _context(candidates=[_candidate(validations=())])
    _, _, _, remediation = context
    plan = _coordinate(context=context, fixes=[_fix(remediation)], validations=[])
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.validation_state == "validation-incomplete"
    assert "required-validation-categories-missing" in result.ineligibility_reason_codes


def test_resolved_thread_is_never_recommended_for_resolution() -> None:
    context = _context(threads=(replace(_thread(), resolved=True),))
    _, _, _, remediation = context
    plan = _coordinate(context=context, fixes=[_fix(remediation)])
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.suggested_action == "leave-open"
    assert "thread-already-resolved" in result.ineligibility_reason_codes


def test_nonpassing_preflight_requires_manual_decision() -> None:
    snapshot, threads, flight, remediation = _context()
    failed_flight = replace(flight, overall_status=Status.FAIL)
    plan = coordinate_resolution(
        snapshot,
        threads,
        failed_flight,
        remediation,
        ("src/a.py",),
        [_fix(remediation)],
        [_validation("focused_pass"), _validation("aggregate_pass")],
        current_head_sha=CURRENT_HEAD,
        final_captured_head_sha=CURRENT_HEAD,
    )
    result = plan.thread_results[0]
    assert result.resolution_eligible is False
    assert result.suggested_action == "manual-decision-required"
    assert "preflight-fail" in result.ineligibility_reason_codes


def test_tampered_remediation_identity_list_is_rejected() -> None:
    snapshot, threads, flight, remediation = _context()
    tampered = replace(remediation, finding_ids=("tampered-finding",))
    with pytest.raises(EvidenceValidationError):
        coordinate_resolution(
            snapshot,
            threads,
            flight,
            tampered,
            ("src/a.py",),
            [],
            [],
            current_head_sha=CURRENT_HEAD,
            final_captured_head_sha=CURRENT_HEAD,
        )


def test_coordination_module_has_no_external_or_mutating_execution_path() -> None:
    path = Path(__file__).parents[2] / "scripts" / "agent_os_pr_remediation" / "coordination.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_import_roots = {
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "os",
        "pathlib",
        "shutil",
        "importlib",
        "github",
        "openai",
        "anthropic",
    }
    forbidden_calls = {
        "system",
        "popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "eval",
        "exec",
        "__import__",
        "write_text",
        "write_bytes",
        "resolve_review_thread",
        "update_file",
        "create_file",
        "open",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] not in forbidden_import_roots for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_import_roots
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls
