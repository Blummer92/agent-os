"""Offline tests for the pure Sprint evidence normalizer (#376).

Provider evidence is represented by local immutable stand-ins so these tests
prove the normalizer consumes evidence structurally and carries no provider,
transport, or network dependency. One end-to-end test normalizes a real
collection from the provider package to guard against contract drift.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance import sprint_evidence_ingestion as module
from scripts.agent_os_issue_acceptance.sprint_dashboard import (
    SCHEMA_VERSION,
    Compatibility,
    SprintMode,
    SuppliedSprintEvidence,
    serialize_sprint_evidence,
)
from scripts.agent_os_issue_acceptance.sprint_evidence_ingestion import (
    normalize_sprint_evidence,
)

REPOSITORY = "owner/repo"
COLLECTED_AT = "2026-07-27T00:00:00Z"
HEAD_SHA = "a" * 40
SPRINT_GOAL = "Ship bounded Sprint evidence ingestion"


# --- immutable provider-evidence stand-ins --------------------------------


@dataclass(frozen=True)
class _Source:
    object_type: str = "issue"
    object_id: str = "101"
    repository: str = REPOSITORY
    retrieved_at: str = COLLECTED_AT
    updated_at: str | None = "2026-07-20T00:00:00Z"
    result_status: str = "complete"
    permission_status: str = "granted"
    pagination_status: str = "not-applicable"
    evidence_digest: str | None = "github-issue-v1:abc"


@dataclass(frozen=True)
class _Pull:
    number: int = 555
    state: str | None = "open"
    base_ref: str | None = "main"
    head_sha: str | None = HEAD_SHA
    changed_files: tuple[str, ...] | None = ("scripts/a.py",)
    checks: tuple[object, ...] | None = ()
    checks_status: str = "passing"
    base_branch_matches_request: bool = True


@dataclass(frozen=True)
class _Candidate:
    issue_number: int = 101
    title: str | None = "Lane one"
    state: str | None = "open"
    blockers: tuple[str, ...] | None = ()
    linked_pull_request_status: str = "resolved"
    pull_request: object | None = None
    freshness: str = "current"
    reason_codes: tuple[str, ...] = ()
    sources: tuple[_Source, ...] = ()


@dataclass(frozen=True)
class _Collection:
    contract_version: str = "0.1.0"
    reporting_schema_version: str = SCHEMA_VERSION
    sprint_id: str = "sprint-wsc-d1b"
    correlation_id: str = "corr-0001"
    repository: str = REPOSITORY
    base_branch: str = "main"
    collected_at: str = COLLECTED_AT
    requested_candidates: tuple[int, ...] = (101,)
    candidates: tuple[_Candidate, ...] = ()
    freshness: str = "current"
    manual_review_reasons: tuple[str, ...] = ()
    evidence_mode: str = "connected-read-only"
    execution_authorized: bool = False
    side_effects_performed: bool = False


def _candidate(**overrides) -> _Candidate:
    values = {
        "pull_request": _Pull(),
        "sources": (_Source(), _Source(object_type="pull-request", object_id="555")),
    }
    values.update(overrides)
    return _Candidate(**values)


def _collection(**overrides) -> _Collection:
    values = {"candidates": (_candidate(),)}
    values.update(overrides)
    collection = _Collection(**values)
    if "requested_candidates" not in overrides:
        collection = replace(
            collection,
            requested_candidates=tuple(c.issue_number for c in collection.candidates),
        )
    return collection


def _normalize(collection=None, **kwargs):
    return normalize_sprint_evidence(
        collection if collection is not None else _collection(),
        sprint_goal=kwargs.pop("sprint_goal", SPRINT_GOAL),
        **kwargs,
    )


# --- 1, 2, 3: schema 0.1.0, connected mode, execution authority -----------


def test_complete_provider_evidence_normalizes_into_schema_0_1_0():
    result = _normalize()
    evidence = result.sprint_evidence

    assert isinstance(evidence, SuppliedSprintEvidence)
    assert evidence.schema_version == SCHEMA_VERSION
    assert evidence.sprint_id == "sprint-wsc-d1b"
    assert evidence.sprint_goal == SPRINT_GOAL
    assert evidence.sprint_state == "active"
    assert evidence.freshness == "current"
    assert evidence.evaluated_at == COLLECTED_AT
    assert evidence.lanes[0].mode is SprintMode.IMPLEMENTATION
    assert evidence.lanes[0].compatibility is Compatibility.COMPATIBLE
    assert evidence.lanes[0].pull_request == 555
    assert evidence.lanes[0].files_changed == ("scripts/a.py",)
    assert evidence.risks == ()
    assert result.repository == REPOSITORY
    assert result.correlation_id == "corr-0001"
    assert result.provider_contract_version == "0.1.0"


def test_connected_read_only_mode_is_preserved():
    evidence = _normalize().sprint_evidence
    assert evidence.evidence_mode == "connected-read-only"
    assert evidence.sources, "connected-read-only mode requires source records"


def test_execution_authorization_remains_false():
    evidence = _normalize().sprint_evidence
    assert evidence.execution_authorized is False
    with pytest.raises(AttributeError):
        evidence.execution_authorized = True  # type: ignore[misc]


def test_provider_evidence_claiming_execution_authority_is_rejected():
    with pytest.raises(ValueError):
        _normalize(_collection(execution_authorized=True))
    with pytest.raises(ValueError):
        _normalize(_collection(side_effects_performed=True))
    with pytest.raises(ValueError):
        _normalize(_collection(evidence_mode="supplied-evidence"))


# --- 4: deterministic normalization --------------------------------------


def test_identical_provider_evidence_normalizes_deterministically():
    first = _normalize().sprint_evidence
    second = _normalize().sprint_evidence
    assert serialize_sprint_evidence(first) == serialize_sprint_evidence(second)
    assert first == second


# --- 5: canonical source and lane ordering -------------------------------


def test_lane_and_source_ordering_is_canonical():
    collection = _collection(
        candidates=(
            _candidate(
                issue_number=303,
                title="Lane three",
                pull_request=None,
                linked_pull_request_status="none",
                reason_codes=("pull-request:none-linked",),
                sources=(_Source(object_id="303"),),
            ),
            _candidate(issue_number=101),
        )
    )
    evidence = _normalize(collection).sprint_evidence

    assert tuple(lane.issue for lane in evidence.lanes) == (101, 303)
    keys = [
        (source.repository, source.object_type, source.object_id)
        for source in evidence.sources
    ]
    assert keys == sorted(keys)


def test_candidate_evidence_must_match_the_supplied_candidates():
    collection = _Collection(
        candidates=(_candidate(issue_number=101),), requested_candidates=(999,)
    )
    with pytest.raises(ValueError):
        _normalize(collection)


# --- 6: sorted and deduplicated manual-review reasons --------------------


def test_manual_review_reasons_are_sorted_and_deduplicated():
    collection = _collection(
        freshness="incomplete",
        manual_review_reasons=(
            "source:unavailable",
            "checks:unknown",
            "source:unavailable",
        ),
        candidates=(
            _candidate(
                freshness="incomplete", reason_codes=("checks:unknown", "checks:unknown")
            ),
        ),
    )
    evidence = _normalize(collection).sprint_evidence
    assert evidence.manual_review_reasons == ("checks:unknown", "source:unavailable")
    assert evidence.lanes[0].reason_codes == ("checks:unknown",)


# --- 7, 8: unknown evidence and validation never become passing ----------


def test_unknown_file_and_check_evidence_remains_unknown():
    collection = _collection(
        freshness="incomplete",
        manual_review_reasons=("checks:unknown", "files:unknown"),
        candidates=(
            _candidate(
                freshness="incomplete",
                reason_codes=("checks:unknown", "files:unknown"),
                pull_request=_Pull(
                    changed_files=None, checks=None, checks_status="unknown"
                ),
            ),
        ),
    )
    evidence = _normalize(collection).sprint_evidence
    lane = evidence.lanes[0]

    assert lane.files_changed == ()
    # The empty tuple never stands alone: the unknown marker travels with it.
    assert "files:unknown" in lane.reason_codes
    assert "checks:unknown" in lane.reason_codes
    assert evidence.validation.status_checks == "unknown"


def test_missing_validation_is_never_reported_as_passing():
    evidence = _normalize().sprint_evidence
    assert evidence.validation.repository_validation == "unknown"
    assert evidence.validation.tests_run == ()
    # Bounded ingestion collects no Cloud Build evidence, so both metrics stay
    # unknown rather than claiming an observed zero.
    assert evidence.validation.builds_avoided is None
    assert evidence.validation.cloud_build_runs is None


@pytest.mark.parametrize(
    ("checks_status", "expected"),
    [
        ("failing", "failed"),
        ("unknown", "unknown"),
        ("pending", "pending"),
        ("passing", "passed"),
    ],
)
def test_check_aggregation_never_upgrades_unknown_to_passed(checks_status, expected):
    freshness = "current" if checks_status == "passing" else "incomplete"
    collection = _collection(
        freshness=freshness,
        candidates=(
            _candidate(
                freshness=freshness,
                pull_request=_Pull(checks_status=checks_status),
            ),
        ),
    )
    evidence = _normalize(collection).sprint_evidence
    assert evidence.validation.status_checks == expected


def _collection_with_check_states(*states: str, freshness: str = "incomplete"):
    candidates = tuple(
        _candidate(
            issue_number=100 + index,
            freshness=freshness,
            pull_request=_Pull(checks_status=state),
            sources=(_Source(object_id=str(100 + index)),),
        )
        for index, state in enumerate(states)
    )
    return _collection(freshness=freshness, candidates=candidates)


def test_unsupported_check_state_fails_closed():
    with pytest.raises(ValueError) as error:
        _normalize(_collection_with_check_states("bogus"))
    assert "bogus" not in str(error.value)
    assert str(error.value) == "unsupported check status in provider evidence"


def test_passing_mixed_with_an_unsupported_check_state_never_becomes_passed():
    with pytest.raises(ValueError):
        _normalize(_collection_with_check_states("passing", "bogus"))


@pytest.mark.parametrize("state", [None, "", "PASSING", "success", "passed"])
def test_non_canonical_check_states_never_become_passed(state):
    with pytest.raises(ValueError):
        _normalize(_collection_with_check_states("passing", state))


def test_passing_only_is_the_sole_path_to_passed():
    evidence = _normalize(
        _collection_with_check_states("passing", "passing", freshness="current")
    ).sprint_evidence
    assert evidence.validation.status_checks == "passed"


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (("failing", "passing"), "failed"),
        (("failing", "unknown"), "failed"),
        (("failing", "bogus"), "failed"),
        (("unknown", "passing"), "unknown"),
        (("unknown", "pending"), "unknown"),
        (("unknown", "bogus"), "unknown"),
        (("pending", "passing"), "pending"),
        (("pending", "bogus"), "pending"),
    ],
)
def test_check_state_precedence_across_lanes(states, expected):
    evidence = _normalize(_collection_with_check_states(*states)).sprint_evidence
    assert evidence.validation.status_checks == expected
    assert evidence.validation.status_checks != "passed"


def test_absent_pull_requests_report_checks_as_not_posted():
    collection = _collection(
        candidates=(
            _candidate(
                pull_request=None,
                linked_pull_request_status="none",
                reason_codes=("pull-request:none-linked",),
            ),
        )
    )
    evidence = _normalize(collection).sprint_evidence
    assert evidence.validation.status_checks == "not-posted"
    assert evidence.lanes[0].mode is SprintMode.PLANNING_ONLY


# --- 9, 10, 11: non-current evidence routes to review or blocked ---------


@pytest.mark.parametrize("freshness", ["stale", "incomplete", "conflicting"])
def test_non_current_evidence_routes_the_sprint_to_review(freshness):
    collection = _collection(
        freshness=freshness,
        manual_review_reasons=("evidence:stale",),
        candidates=(_candidate(freshness=freshness, reason_codes=("source:mutated",)),),
    )
    evidence = _normalize(collection).sprint_evidence
    assert evidence.sprint_state == "review"
    assert evidence.lanes[0].mode is SprintMode.REVIEW
    assert evidence.lanes[0].compatibility is Compatibility.UNKNOWN


@pytest.mark.parametrize(
    "reason",
    [
        "permission:denied",
        "quota:exhausted-first-page",
        "source:unavailable",
        "source:malformed",
        "repository:identity-unverified",
    ],
)
def test_blocking_evidence_routes_every_lane_to_blocked(reason):
    collection = _collection(
        freshness="incomplete",
        manual_review_reasons=(reason,),
        candidates=(
            _candidate(
                freshness="incomplete",
                reason_codes=(reason,),
                pull_request=None,
                linked_pull_request_status="unknown",
            ),
        ),
    )
    evidence = _normalize(collection).sprint_evidence
    assert evidence.lanes[0].mode is SprintMode.BLOCKED
    assert evidence.sprint_state == "blocked"


def test_mixed_blocked_and_review_lanes_route_to_review():
    collection = _collection(
        freshness="incomplete",
        candidates=(
            _candidate(
                issue_number=101,
                freshness="incomplete",
                reason_codes=("permission:denied",),
                pull_request=None,
                linked_pull_request_status="unknown",
            ),
            _candidate(
                issue_number=202,
                freshness="incomplete",
                reason_codes=("checks:unknown",),
                sources=(_Source(object_id="202"),),
            ),
        ),
    )
    evidence = _normalize(collection).sprint_evidence
    assert {lane.mode for lane in evidence.lanes} == {
        SprintMode.BLOCKED,
        SprintMode.REVIEW,
    }
    assert evidence.sprint_state == "review"


# --- 12: unsupported versions --------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"contract_version": "0.9.9"},
        {"reporting_schema_version": "0.2.0"},
    ],
)
def test_unsupported_versions_are_rejected(overrides):
    with pytest.raises(ValueError):
        _normalize(_collection(**overrides))


# --- 13: malformed immutable evidence fails closed -----------------------


def test_structurally_incomplete_evidence_fails_closed():
    @dataclass(frozen=True)
    class _Partial:
        contract_version: str = "0.1.0"

    with pytest.raises(TypeError):
        _normalize(_Partial())


def test_candidate_missing_required_evidence_fails_closed():
    @dataclass(frozen=True)
    class _PartialCandidate:
        issue_number: int = 101

    collection = _Collection(
        candidates=(_PartialCandidate(),), requested_candidates=(101,)
    )
    with pytest.raises(TypeError):
        _normalize(collection)


@pytest.mark.parametrize(
    "overrides",
    [
        {"candidates": ()},
        {"freshness": "unknown"},
        {"sprint_id": "  "},
    ],
)
def test_invalid_collection_values_fail_closed(overrides):
    values = {"candidates": (_candidate(),), "requested_candidates": (101,)}
    values.update(overrides)
    with pytest.raises(ValueError):
        _normalize(_Collection(**values))


def test_empty_sprint_goal_is_rejected():
    with pytest.raises(ValueError):
        _normalize(sprint_goal="   ")


def test_evidence_without_source_records_fails_closed():
    collection = _collection(candidates=(_candidate(sources=()),))
    with pytest.raises(ValueError):
        _normalize(collection)


# --- 14: closed candidates ------------------------------------------------


def test_closed_candidates_never_normalize_as_implementation_ready():
    collection = _collection(
        candidates=(
            _candidate(state="closed", reason_codes=("candidate:closed",)),
        )
    )
    evidence = _normalize(collection).sprint_evidence
    lane = evidence.lanes[0]
    assert lane.mode is SprintMode.REVIEW
    assert lane.mode is not SprintMode.IMPLEMENTATION
    assert lane.compatibility is Compatibility.UNKNOWN
    assert "candidate:closed" in lane.reason_codes


# --- 15: movement stays visible ------------------------------------------


def test_source_and_pull_request_movement_remain_visible():
    collection = _collection(
        freshness="stale",
        manual_review_reasons=("evidence:stale", "pull-request:head-changed"),
        candidates=(
            _candidate(
                freshness="stale",
                reason_codes=("pull-request:head-changed", "source:mutated"),
            ),
        ),
    )
    evidence = _normalize(collection).sprint_evidence
    assert "pull-request:head-changed" in evidence.lanes[0].reason_codes
    assert "source:mutated" in evidence.lanes[0].reason_codes
    assert "evidence:stale" in evidence.manual_review_reasons
    assert evidence.freshness == "stale"
    assert evidence.sprint_state == "review"


# --- 16: architectural boundary ------------------------------------------


def test_normalizer_imports_no_transport_network_or_filesystem_module():
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    absolute: set[str] = set()
    relative: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative.add((node.module or "").split(".")[0])
            elif node.module:
                absolute.add(node.module.split(".")[0])

    assert absolute <= {"__future__", "dataclasses", "typing"}
    assert relative == {"sprint_dashboard"}


def _referenced_identifiers(tree: ast.AST) -> set[str]:
    """Identifiers the code actually references, ignoring prose and comments."""

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


_FORBIDDEN_RUNTIME_IDENTIFIERS = frozenset(
    {
        "compile",
        "connect",
        "credentials",
        "environ",
        "eval",
        "exec",
        "getenv",
        "http",
        "input",
        "mkdir",
        "open",
        "os",
        "pathlib",
        "requests",
        "retry",
        "scheduler",
        "socket",
        "subprocess",
        "token",
        "unlink",
        "urlopen",
        "urllib",
        "write_text",
    }
)


def test_normalizer_source_declares_no_write_or_runtime_behavior():
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    referenced = _referenced_identifiers(tree)
    assert not referenced & _FORBIDDEN_RUNTIME_IDENTIFIERS


def test_normalization_touches_no_network_or_filesystem_entry_point(monkeypatch):
    import builtins
    import http.client
    import os
    import pathlib
    import socket
    import subprocess
    import urllib.request

    def _boom(*args, **kwargs):
        raise AssertionError("the normalizer must not use this entry point")

    monkeypatch.setattr(builtins, "open", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(http.client, "HTTPConnection", _boom)
    monkeypatch.setattr(http.client, "HTTPSConnection", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(pathlib.Path, "open", _boom)
    monkeypatch.setattr(pathlib.Path, "read_text", _boom)
    monkeypatch.setattr(pathlib.Path, "write_text", _boom)
    monkeypatch.setattr(os, "environ", {})

    result = normalize_sprint_evidence(_collection(), sprint_goal=SPRINT_GOAL)

    assert result.sprint_evidence.execution_authorized is False
    assert result.sprint_evidence.evidence_mode == "connected-read-only"


def test_normalizer_module_exposes_only_the_bounded_surface():
    public = {name for name in dir(module) if not name.startswith("_")}
    assert "normalize_sprint_evidence" in public
    assert not {name for name in public if name.startswith(("fetch", "post", "write"))}


# --- contract-drift guard against the real provider collection ------------


def test_real_provider_collection_normalizes_end_to_end():
    from scripts.agent_os_github_issue_provider.models import (
        TransportAttempt,
        TransportResponse,
    )
    from scripts.agent_os_github_issue_provider.sprint_evidence import (
        SprintEvidenceLimits,
        SprintEvidenceRequest,
        collect_sprint_evidence,
    )

    def response(payload):
        return TransportResponse(
            status=200, headers={}, payload=payload, attempts=(TransportAttempt(1),)
        )

    issue = {
        "number": 101,
        "title": "Lane one",
        "state": "open",
        "body": "body",
        "html_url": f"https://github.com/{REPOSITORY}/issues/101",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
        "closed_at": None,
        "state_reason": None,
        "labels": [{"name": "agent-os"}],
        "dependencies": [],
        "blockers": [],
    }
    pull = {
        "number": 555,
        "state": "open",
        "head": {"sha": HEAD_SHA},
        "base": {"ref": "main"},
        "created_at": "2026-07-10T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
    }

    class Reader:
        def get_installation_repositories(self, **_):
            return response(
                {"repositories": [{"full_name": REPOSITORY, "id": 4242, "fork": False}]}
            )

        def get_issue(self, **_):
            return response(dict(issue))

        def get_linked_pull_requests(self, **_):
            return response([{"number": 555}])

        def get_pull_request(self, **_):
            return response(dict(pull))

        def get_pull_request_files(self, **_):
            return response([{"filename": "scripts/a.py"}])

        def get_check_runs(self, **_):
            return response(
                {"check_runs": [{"name": "gate", "status": "completed", "conclusion": "success"}]}
            )

    collection = collect_sprint_evidence(
        SprintEvidenceRequest(
            repository=REPOSITORY,
            repository_id=4242,
            base_branch="main",
            candidates=(101,),
            sprint_id="sprint-wsc-d1b",
            correlation_id="corr-0001",
            collected_at=COLLECTED_AT,
            reporting_schema_version=SCHEMA_VERSION,
            limits=SprintEvidenceLimits(
                max_candidates=3, max_pages=3, page_size=50, max_evidence_items=100
            ),
        ),
        Reader(),
    )

    result = normalize_sprint_evidence(collection, sprint_goal=SPRINT_GOAL)
    evidence = result.sprint_evidence

    assert evidence.freshness == "current"
    assert evidence.sprint_state == "active"
    assert evidence.lanes[0].mode is SprintMode.IMPLEMENTATION
    assert evidence.lanes[0].files_changed == ("scripts/a.py",)
    assert evidence.validation.status_checks == "passed"
    assert evidence.execution_authorized is False
    assert result.correlation_id == "corr-0001"
