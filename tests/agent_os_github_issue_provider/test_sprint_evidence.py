"""Offline fixture-first tests for bounded Sprint evidence collection (#376).

Every test runs with injected fakes. No connected read, credential, or network
call is performed, and no connected smoke test is authorized or attempted.
Fixture builders are local and immutable per the recorded #376 allowlist.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.agent_os_github_issue_provider import sprint_evidence as module
from scripts.agent_os_github_issue_provider.models import (
    TransportAttempt,
    TransportResponse,
)
from scripts.agent_os_github_issue_provider.sprint_evidence import (
    SPRINT_EVIDENCE_REASON_CODES,
    SprintEvidenceLimits,
    SprintEvidenceRequest,
    SprintEvidenceRequestError,
    collect_sprint_evidence,
)
from scripts.agent_os_github_issue_provider.transport import GitHubTransportError

REPOSITORY = "owner/repo"
REPOSITORY_ID = 4242
BASE_BRANCH = "main"
HEAD_SHA = "a" * 40
MOVED_SHA = "b" * 40
COLLECTED_AT = "2026-07-27T00:00:00Z"
CANDIDATE = 101
PULL_NUMBER = 555

READ_METHODS = frozenset(
    {
        "get_installation_repositories",
        "get_issue",
        "get_linked_pull_requests",
        "get_pull_request",
        "get_pull_request_files",
        "get_check_runs",
    }
)


# --- immutable fixture builders ------------------------------------------


def _response(payload: object, *, link: str | None = None, status: int = 200):
    headers = {} if link is None else {"Link": link}
    return TransportResponse(
        status=status,
        headers=headers,
        payload=payload,
        attempts=(TransportAttempt(1),),
    )


def _repo_entry(full_name: str = REPOSITORY, repo_id: int = REPOSITORY_ID, **extra):
    entry = {"full_name": full_name, "id": repo_id, "fork": False}
    entry.update(extra)
    return entry


def _installation(*entries, link: str | None = None):
    collected = entries or (_repo_entry(),)
    return _response(
        {"total_count": len(collected), "repositories": list(collected)}, link=link
    )


def _issue(
    number: int = CANDIDATE,
    *,
    state: str = "open",
    body: str = "candidate body",
    dependencies=(),
    blockers=(),
):
    return {
        "number": number,
        "title": f"Lane {number}",
        "state": state,
        "body": body,
        "html_url": f"https://github.com/{REPOSITORY}/issues/{number}",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
        "closed_at": "2026-07-21T00:00:00Z" if state == "closed" else None,
        "state_reason": None,
        "labels": [{"name": "agent-os"}],
        "dependencies": list(dependencies),
        "blockers": list(blockers),
    }


def _pull(*, head: str = HEAD_SHA, base: str = BASE_BRANCH, state: str = "open"):
    return {
        "number": PULL_NUMBER,
        "state": state,
        "head": {"sha": head},
        "base": {"ref": base},
        "created_at": "2026-07-10T00:00:00Z",
        "updated_at": "2026-07-20T00:00:00Z",
    }


def _check(name: str = "validation-gate", conclusion: str = "success"):
    return {"name": name, "status": "completed", "conclusion": conclusion}


def _link(path: str, *, page: int = 2, per_page: int = 50, host: str = "api.github.com"):
    return f'<https://{host}{path}?page={page}&per_page={per_page}>; rel="next"'


class FakeReader:
    """Injected offline read port. No write or mutation method exists."""

    def __init__(self, **scripts) -> None:
        self.scripts = {name: list(values) for name, values in scripts.items()}
        self.calls: list[tuple[str, dict]] = []

    def _next(self, name: str, kwargs: dict):
        self.calls.append((name, kwargs))
        queue = self.scripts.get(name)
        if not queue:
            raise AssertionError(f"unscripted read: {name}")
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def get_installation_repositories(self, **kwargs):
        return self._next("installation", kwargs)

    def get_issue(self, **kwargs):
        return self._next("issue", kwargs)

    def get_linked_pull_requests(self, **kwargs):
        return self._next("linked", kwargs)

    def get_pull_request(self, **kwargs):
        return self._next("pull", kwargs)

    def get_pull_request_files(self, **kwargs):
        return self._next("files", kwargs)

    def get_check_runs(self, **kwargs):
        return self._next("checks", kwargs)


def _scripts(**overrides) -> dict:
    base = {
        "installation": [_installation()],
        "issue": [_response(_issue()), _response(_issue())],
        "linked": [_response([{"number": PULL_NUMBER}])],
        "pull": [_response(_pull()), _response(_pull())],
        "files": [_response([{"filename": "scripts/a.py"}])],
        "checks": [_response({"check_runs": [_check()]})],
    }
    base.update(overrides)
    return base


def _reader(**overrides) -> FakeReader:
    return FakeReader(**_scripts(**overrides))


def _limits(**overrides) -> SprintEvidenceLimits:
    values = {
        "max_candidates": 3,
        "max_pages": 3,
        "page_size": 50,
        "max_evidence_items": 100,
    }
    values.update(overrides)
    return SprintEvidenceLimits(**values)


def _request(**overrides) -> SprintEvidenceRequest:
    values = {
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "base_branch": BASE_BRANCH,
        "candidates": (CANDIDATE,),
        "sprint_id": "sprint-wsc-d1b",
        "correlation_id": "corr-0001",
        "collected_at": COLLECTED_AT,
        "reporting_schema_version": "0.1.0",
        "limits": overrides.pop("limits", _limits()),
    }
    values.update(overrides)
    return SprintEvidenceRequest(**values)


def _collect(**overrides):
    reader = _reader(**overrides.pop("scripts", {}))
    return collect_sprint_evidence(_request(**overrides), reader), reader


def _all_reasons(collection) -> set[str]:
    reasons = set(collection.manual_review_reasons)
    reasons.update(collection.identity.reason_codes)
    for candidate in collection.candidates:
        reasons.update(candidate.reason_codes)
        for source in candidate.sources:
            reasons.update(source.reason_codes)
    return reasons


# --- 1, 5: complete deterministic evidence with terminal proof ------------


def test_complete_evidence_is_current_with_terminal_pagination_proof():
    collection, reader = _collect()

    assert collection.freshness == "current"
    assert collection.manual_review_reasons == ()
    assert collection.evidence_mode == "connected-read-only"
    assert collection.execution_authorized is False
    assert collection.side_effects_performed is False
    assert collection.identity.verified is True
    assert collection.identity.terminal_page_proven is True
    assert collection.retry_count == 0
    assert collection.reads_stopped == 0

    candidate = collection.candidates[0]
    assert candidate.issue_number == CANDIDATE
    assert candidate.freshness == "current"
    assert candidate.source_revision is not None
    assert candidate.linked_pull_request_status == "resolved"
    assert candidate.pull_request.head_sha == HEAD_SHA
    assert candidate.pull_request.base_ref == BASE_BRANCH
    assert candidate.pull_request.changed_files == ("scripts/a.py",)
    assert candidate.pull_request.checks_status == "passing"
    assert all(source.terminal_page_proven for source in candidate.sources)
    assert {name for name, _ in reader.calls} <= {
        "installation",
        "issue",
        "linked",
        "pull",
        "files",
        "checks",
    }


# --- 2: explicitly supplied candidates only -------------------------------


def test_only_explicitly_supplied_candidates_are_read():
    collection, reader = _collect(
        candidates=(CANDIDATE,),
        scripts={},
    )

    requested = set(collection.requested_candidates)
    assert requested == {CANDIDATE}
    read_numbers = {
        kwargs["issue_number"] for _, kwargs in reader.calls if "issue_number" in kwargs
    }
    assert read_numbers == requested
    assert tuple(c.issue_number for c in collection.candidates) == (CANDIDATE,)


# --- 3: duplicate and invalid candidates rejected before any read ---------


@pytest.mark.parametrize(
    "candidates",
    [(CANDIDATE, CANDIDATE), (0,), (-3,), (True,), ()],
)
def test_invalid_candidates_are_rejected_before_any_read(candidates):
    reader = _reader()
    with pytest.raises(ValueError):
        _request(candidates=candidates)
    assert reader.calls == []


def test_non_tuple_candidates_are_rejected():
    with pytest.raises(TypeError):
        _request(candidates=[CANDIDATE])


# --- 4: fixed candidate, page, page-size and item bounds ------------------


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"max_candidates": 4}, "bounds:candidates-exceeded"),
        ({"max_pages": 11}, "bounds:pages-exceeded"),
        ({"page_size": 101}, "bounds:items-exceeded"),
        ({"max_evidence_items": 301}, "bounds:items-exceeded"),
    ],
)
def test_limits_outside_supported_bounds_are_rejected(override, reason):
    with pytest.raises(SprintEvidenceRequestError) as error:
        _limits(**override)
    assert error.value.reason_code == reason


@pytest.mark.parametrize("override", [{"max_pages": 0}, {"page_size": -1}])
def test_nonpositive_limits_are_rejected(override):
    with pytest.raises(ValueError):
        _limits(**override)


def test_supplied_candidate_count_cannot_exceed_the_frozen_bound():
    with pytest.raises(SprintEvidenceRequestError) as error:
        _request(candidates=(1, 2), limits=_limits(max_candidates=1))
    assert error.value.reason_code == "bounds:candidates-exceeded"


def test_unsupported_reporting_schema_version_is_rejected():
    with pytest.raises(SprintEvidenceRequestError) as error:
        _request(reporting_schema_version="0.2.0")
    assert error.value.reason_code == "schema:unsupported-version"


# --- 6, 7: incomplete pagination and absent terminal proof ----------------


def test_hitting_the_page_bound_before_terminal_proof_is_incomplete():
    collection, _ = _collect(
        limits=_limits(max_pages=1),
        scripts={
            "installation": [
                _installation(link=_link("/installation/repositories")),
            ]
        },
    )
    reasons = _all_reasons(collection)
    assert "bounds:pages-exceeded" in reasons
    assert "pagination:terminal-proof-absent" in reasons
    assert "pagination:incomplete" in reasons
    assert collection.identity.verified is False
    assert collection.freshness == "incomplete"


def test_absent_terminal_proof_on_a_later_page_is_incomplete():
    collection, _ = _collect(
        scripts={
            "installation": [
                _installation(link=_link("/installation/repositories")),
                # Page two carries no Link header at all, so nothing proves the
                # sequence terminated here.
                _installation(),
            ]
        },
    )
    reasons = _all_reasons(collection)
    assert "pagination:terminal-proof-absent" in reasons
    assert collection.identity.terminal_page_proven is False
    assert collection.identity.verified is False


def test_complete_multi_page_read_proves_termination():
    collection, _ = _collect(
        scripts={
            "files": [
                _response(
                    [{"filename": "scripts/a.py"}],
                    link=_link(f"/repos/{REPOSITORY}/pulls/{PULL_NUMBER}/files"),
                ),
                # A Link header without a `next` relation is positive proof.
                _response(
                    [{"filename": "scripts/b.py"}],
                    link=(
                        f'<https://api.github.com/repos/{REPOSITORY}/pulls/'
                        f'{PULL_NUMBER}/files?page=1&per_page=50>; rel="prev"'
                    ),
                ),
            ]
        },
    )
    candidate = collection.candidates[0]
    assert candidate.pull_request.changed_files == ("scripts/a.py", "scripts/b.py")
    assert collection.freshness == "current"


# --- 8: cross-host and cross-repository continuation rejection ------------


@pytest.mark.parametrize(
    "link",
    [
        _link("/installation/repositories", host="evil.example.com"),
        _link("/repos/other/repo/issues"),
        '<http://api.github.com/installation/repositories?page=2>; rel="next"',
        '<https://api.github.com/installation/repositories>; rel="next"',
        '<https://api.github.com/installation/repositories?page=1&per_page=50>; rel="next"',
        "<not a link header",
    ],
)
def test_unsafe_continuations_fail_closed(link):
    collection, _ = _collect(
        scripts={"installation": [_installation(link=link), _installation()]}
    )
    reasons = _all_reasons(collection)
    assert "pagination:continuation-rejected" in reasons
    assert collection.identity.verified is False
    assert collection.freshness == "incomplete"


def test_continuation_changing_page_size_is_rejected():
    collection, _ = _collect(
        scripts={
            "installation": [
                _installation(link=_link("/installation/repositories", per_page=99)),
                _installation(),
            ]
        }
    )
    assert "pagination:continuation-rejected" in _all_reasons(collection)


# --- 9, 10, 11: repository identity ---------------------------------------


def test_matching_owner_name_and_numeric_identity_verifies():
    collection, _ = _collect()
    assert collection.identity.verified is True
    assert collection.identity.reason_codes == ()


def test_numeric_id_mismatch_fails_closed_and_conflicts():
    collection, reader = _collect(
        scripts={"installation": [_installation(_repo_entry(repo_id=999))]}
    )
    reasons = _all_reasons(collection)
    assert "repository:id-mismatch" in reasons
    assert "repository:identity-unverified" in reasons
    assert collection.freshness == "conflicting"
    assert not any(name == "issue" for name, _ in reader.calls)


def test_owner_name_mismatch_fails_closed_and_conflicts():
    collection, _ = _collect(
        scripts={"installation": [_installation(_repo_entry(full_name="other/repo"))]}
    )
    reasons = _all_reasons(collection)
    assert "repository:name-mismatch" in reasons
    assert collection.freshness == "conflicting"


def test_unverified_numeric_identity_when_evidence_cannot_be_read():
    collection, reader = _collect(
        scripts={"installation": [GitHubTransportError("source-inaccessible", ())]}
    )
    reasons = _all_reasons(collection)
    assert "repository:identity-unverified" in reasons
    assert "source:unavailable" in reasons
    assert collection.freshness == "incomplete"
    assert not any(name == "issue" for name, _ in reader.calls)
    source = collection.candidates[0].sources[0]
    assert source.result_status == "not-retrieved"
    assert source.pagination_status == "unverified"


@pytest.mark.parametrize(
    "entry",
    [
        _repo_entry(fork=True),
        _repo_entry(parent={"full_name": "upstream/repo"}),
        _repo_entry(source={"full_name": "upstream/repo"}),
    ],
)
def test_fork_and_upstream_ambiguity_fails_closed(entry):
    collection, _ = _collect(scripts={"installation": [_installation(entry)]})
    assert "repository:fork-ambiguous" in _all_reasons(collection)
    assert collection.identity.verified is False


def test_duplicate_numeric_identity_in_installation_evidence_is_unverified():
    collection, _ = _collect(
        scripts={
            "installation": [
                _installation(_repo_entry(), _repo_entry(full_name="other/repo"))
            ]
        }
    )
    assert "repository:identity-unverified" in _all_reasons(collection)
    assert collection.identity.verified is False


# --- 12, 13, 14, 15: permission, quota, availability, malformed ----------


def test_permission_denial_is_classified_and_not_retried():
    collection, reader = _collect(
        scripts={"issue": [GitHubTransportError("permission-denied", ())]}
    )
    reasons = _all_reasons(collection)
    assert "permission:denied" in reasons
    assert collection.retry_count == 0
    assert sum(1 for name, _ in reader.calls if name == "issue") == 1
    source = collection.candidates[0].sources[0]
    assert source.result_status == "denied"
    assert source.permission_status == "denied"


def test_first_page_quota_exhaustion_is_distinguished():
    collection, _ = _collect(
        scripts={"installation": [GitHubTransportError("rate-limited", ())]}
    )
    reasons = _all_reasons(collection)
    assert "quota:exhausted-first-page" in reasons
    assert "quota:exhausted-later-page" not in reasons
    assert collection.retry_count == 0


def test_later_page_quota_exhaustion_is_distinguished():
    collection, _ = _collect(
        scripts={
            "installation": [
                _installation(link=_link("/installation/repositories")),
                GitHubTransportError("rate-limited", ()),
            ]
        }
    )
    reasons = _all_reasons(collection)
    assert "quota:exhausted-later-page" in reasons
    assert "quota:exhausted-first-page" not in reasons


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (GitHubTransportError("source-inaccessible", ()), "source:unavailable"),
        (GitHubTransportError("malformed-response", ()), "source:malformed"),
    ],
)
def test_unavailable_and_malformed_transport_failures(failure, reason):
    collection, _ = _collect(scripts={"issue": [failure]})
    assert reason in _all_reasons(collection)


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (403, "permission:denied"),
        (429, "quota:exhausted-first-page"),
        (404, "source:unavailable"),
        (500, "source:malformed"),
    ],
)
def test_non_success_statuses_are_classified(status, reason):
    collection, _ = _collect(
        scripts={"issue": [_response(_issue(), status=status)]}
    )
    assert reason in _all_reasons(collection)


def test_malformed_issue_payload_is_not_normalized():
    collection, _ = _collect(scripts={"issue": [_response({"number": CANDIDATE})]})
    candidate = collection.candidates[0]
    assert "source:malformed" in candidate.reason_codes
    assert candidate.source_revision is None
    assert candidate.title is None
    assert candidate.labels is None


# --- 16, 17, 18: the single explicitly safe retry -------------------------


def _safe_error(kind: str = "api-error") -> GitHubTransportError:
    error = GitHubTransportError(kind, ())
    error.safe_transient_retry = True
    return error


def test_one_explicitly_safe_transient_retry_is_permitted():
    collection, reader = _collect(
        scripts={"issue": [_safe_error(), _response(_issue()), _response(_issue())]}
    )
    assert collection.retry_count == 1
    assert collection.freshness == "current"
    assert sum(1 for name, _ in reader.calls if name == "issue") == 3


@pytest.mark.parametrize(
    "failure",
    [
        GitHubTransportError("api-error", ()),
        GitHubTransportError("permission-denied", ()),
        GitHubTransportError("rate-limited", ()),
        GitHubTransportError("malformed-response", ()),
    ],
)
def test_unsafe_or_unknown_failures_are_never_retried(failure):
    collection, reader = _collect(scripts={"issue": [failure]})
    assert collection.retry_count == 0
    assert sum(1 for name, _ in reader.calls if name == "issue") == 1


def test_missing_retry_signal_records_the_unsafe_classification():
    collection, _ = _collect(
        scripts={"issue": [GitHubTransportError("api-error", ())]}
    )
    assert "retry:unsafe-signal" in _all_reasons(collection)


def test_no_more_than_one_retry_occurs_per_collection():
    collection, reader = _collect(
        scripts={
            "installation": [_safe_error(), _installation()],
            "issue": [_safe_error()],
        }
    )
    assert collection.retry_count == 1
    assert "retry:safe-retry-exhausted" in _all_reasons(collection)
    assert sum(1 for name, _ in reader.calls if name == "issue") == 1


def test_a_failing_safe_retry_is_recorded_as_exhausted():
    collection, reader = _collect(
        scripts={"issue": [_safe_error(), _safe_error()]}
    )
    assert collection.retry_count == 1
    assert "retry:safe-retry-exhausted" in _all_reasons(collection)
    assert sum(1 for name, _ in reader.calls if name == "issue") == 2


# --- 19, 20: source and pull-request movement -----------------------------


def test_source_revision_mutation_during_collection_is_stale():
    collection, _ = _collect(
        scripts={
            "issue": [_response(_issue()), _response(_issue(body="edited body"))]
        }
    )
    candidate = collection.candidates[0]
    assert "source:mutated" in candidate.reason_codes
    assert candidate.freshness == "stale"
    assert collection.freshness == "stale"
    assert "evidence:stale" in collection.manual_review_reasons


def test_changed_pull_request_head_is_stale():
    collection, _ = _collect(
        scripts={"pull": [_response(_pull()), _response(_pull(head=MOVED_SHA))]}
    )
    candidate = collection.candidates[0]
    assert "pull-request:head-changed" in candidate.reason_codes
    assert candidate.freshness == "stale"
    assert candidate.pull_request.head_sha == HEAD_SHA


def test_changed_pull_request_base_is_stale():
    collection, _ = _collect(
        scripts={"pull": [_response(_pull()), _response(_pull(base="release"))]}
    )
    assert "pull-request:base-changed" in collection.candidates[0].reason_codes
    assert collection.freshness == "stale"


def test_pull_request_targeting_another_base_conflicts():
    collection, _ = _collect(
        scripts={
            "pull": [_response(_pull(base="release")), _response(_pull(base="release"))]
        }
    )
    assert "evidence:conflicting" in collection.candidates[0].reason_codes
    assert collection.freshness == "conflicting"
    assert collection.candidates[0].pull_request.base_branch_matches_request is False


# --- 21, 22, 23: linked pull requests and candidate state -----------------


def test_no_linked_pull_request_is_proven_absence_not_missing_evidence():
    collection, _ = _collect(scripts={"linked": [_response([])], "pull": [], "files": [], "checks": []})
    candidate = collection.candidates[0]
    assert candidate.linked_pull_request_status == "none"
    assert "pull-request:none-linked" in candidate.reason_codes
    assert "files:unknown" not in candidate.reason_codes
    assert candidate.freshness == "current"


def test_ambiguous_linked_pull_requests_fail_closed():
    collection, _ = _collect(
        scripts={
            "linked": [_response([{"number": 1}, {"number": 2}])],
            "pull": [],
            "files": [],
            "checks": [],
        }
    )
    candidate = collection.candidates[0]
    assert candidate.linked_pull_request_status == "ambiguous"
    assert "pull-request:ambiguous" in candidate.reason_codes
    assert "files:unknown" in candidate.reason_codes
    assert "checks:unknown" in candidate.reason_codes
    assert candidate.pull_request is None


def test_closed_candidate_is_recorded_without_degrading_freshness():
    collection, _ = _collect(scripts={"issue": [_response(_issue(state="closed"))] * 2})
    candidate = collection.candidates[0]
    assert candidate.state == "closed"
    assert "candidate:closed" in candidate.reason_codes
    assert candidate.freshness == "current"


# --- 24: exceeded evidence bounds ----------------------------------------


def test_exceeding_the_evidence_item_bound_fails_closed():
    collection, _ = _collect(
        limits=_limits(max_evidence_items=1),
        scripts={
            "files": [
                _response([{"filename": "a.py"}, {"filename": "b.py"}]),
            ]
        },
    )
    candidate = collection.candidates[0]
    assert "bounds:items-exceeded" in candidate.reason_codes
    assert "files:unknown" in candidate.reason_codes
    assert candidate.pull_request.changed_files is None


# --- unknown evidence stays unknown --------------------------------------


def test_unknown_file_and_check_evidence_never_becomes_empty_or_passing():
    collection, _ = _collect(
        scripts={
            "files": [GitHubTransportError("permission-denied", ())],
            "checks": [_response({"check_runs": []})],
        }
    )
    pull_request = collection.candidates[0].pull_request
    # Denied file evidence stays unknown rather than collapsing to "no files".
    assert pull_request.changed_files is None
    # A successfully read but empty check list is proven empty, and an empty
    # check list can still never be reported as passing.
    assert pull_request.checks == ()
    assert pull_request.checks_status == "unknown"
    reasons = collection.candidates[0].reason_codes
    assert "files:unknown" in reasons
    assert "checks:unknown" in reasons


@pytest.mark.parametrize(
    ("conclusion", "expected"),
    [("failure", "failing"), ("success", "passing"), ("neutral", "passing")],
)
def test_check_conclusions_are_classified(conclusion, expected):
    collection, _ = _collect(
        scripts={"checks": [_response({"check_runs": [_check(conclusion=conclusion)]})]}
    )
    assert collection.candidates[0].pull_request.checks_status == expected


def test_incomplete_check_runs_are_pending_not_passing():
    collection, _ = _collect(
        scripts={
            "checks": [
                _response(
                    {
                        "check_runs": [
                            {"name": "gate", "status": "in_progress", "conclusion": None}
                        ]
                    }
                )
            ]
        }
    )
    assert collection.candidates[0].pull_request.checks_status == "pending"


def test_unknown_dependencies_and_blockers_stay_unknown():
    payload = _issue()
    payload.pop("dependencies")
    payload.pop("blockers")
    collection, _ = _collect(scripts={"issue": [_response(payload)] * 2})
    candidate = collection.candidates[0]
    assert candidate.dependencies is None
    assert candidate.blockers is None
    assert "dependencies:unknown" in candidate.reason_codes
    assert "blockers:unknown" in candidate.reason_codes


# --- 25: bounded, non-sensitive diagnostics ------------------------------


def test_reason_evidence_is_bounded_and_non_sensitive():
    secret = "ghp_examplesecrettokenvalue"
    collection, _ = _collect(
        scripts={
            "issue": [_response({"number": CANDIDATE, "token": secret})],
        }
    )
    reasons = _all_reasons(collection)
    assert reasons <= SPRINT_EVIDENCE_REASON_CODES
    joined = " ".join(sorted(reasons))
    assert secret not in joined
    assert "https://" not in joined
    assert all(len(reason) <= 48 for reason in reasons)


def test_every_declared_reason_code_is_bounded_and_sorted():
    collection, _ = _collect(
        scripts={"installation": [GitHubTransportError("rate-limited", ())]}
    )
    reasons = collection.manual_review_reasons
    assert list(reasons) == sorted(set(reasons))
    assert set(reasons) <= SPRINT_EVIDENCE_REASON_CODES


# --- 26: deterministic immutable output ----------------------------------


def test_identical_input_produces_identical_immutable_output():
    first = collect_sprint_evidence(_request(), _reader())
    second = collect_sprint_evidence(_request(), _reader())
    assert first == second
    with pytest.raises(AttributeError):
        first.freshness = "stale"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        first.candidates[0].reason_codes = ()  # type: ignore[misc]


def test_collection_rejects_non_request_and_missing_reader():
    with pytest.raises(TypeError):
        collect_sprint_evidence(object(), _reader())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        collect_sprint_evidence(_request(), None)  # type: ignore[arg-type]


# --- 27: no write or mutation behavior -----------------------------------


def test_reader_port_exposes_only_bounded_reads():
    reader = _reader()
    collect_sprint_evidence(_request(), reader)
    assert {name for name, _ in reader.calls} <= {
        "installation",
        "issue",
        "linked",
        "pull",
        "files",
        "checks",
    }
    protocol_methods = {
        name
        for name in dir(module.SprintEvidenceReader)
        if not name.startswith("_")
    }
    assert protocol_methods == READ_METHODS


def test_module_contains_no_write_or_filesystem_behavior():
    """The collector owns transport *classification*, never transport itself."""

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    modules: set[str] = set()
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)

    # urllib.parse is URL *parsing* for Link headers; urllib.request is absent.
    assert modules <= {
        "__future__",
        "dataclasses",
        "datetime",
        "re",
        "typing",
        "urllib.parse",
    }

    forbidden = {
        "connect",
        "create",
        "delete",
        "environ",
        "eval",
        "exec",
        "getenv",
        "input",
        "merge",
        "mkdir",
        "open",
        "os",
        "pathlib",
        "patch",
        "post",
        "print",
        "put",
        "remove",
        "requests",
        "send",
        "socket",
        "subprocess",
        "unlink",
        "update",
        "urlopen",
        "write",
        "write_text",
    }
    assert not referenced & forbidden
