"""#2425 opt-in CKR6 profile: R07 wrapper + read-only GitHub reader.

The wrapper consumes a trusted CKR6 result comment through the
server-installed read-only GitHub issue-comment reader only. No test here
touches the network: the reader's HTTP transport is injected, and the
wrapper's reader is installed per-test and cleared afterwards. Fixture
records reuse ``test_ckr6_result_consumption`` builders.
"""

from __future__ import annotations

import inspect
import json

import pytest

from agent_os_execution_service import ckr6_github_reader as reader_module
from agent_os_execution_service import mcp_server
from agent_os_execution_service.ckr6_github_reader import (
    GitHubIssueCommentReadUnavailable,
    GitHubIssueCommentReader,
)
from test_ckr6_result_consumption import (
    ISSUE,
    REPOSITORY,
    REQUEST_AT,
    REQUEST_ID,
    _comment,
    _failed_repair_result,
    _result,
)

RESULT_AT = "2026-11-11T10:00:30Z"
TOKEN = "ghs_test-installation-token"
AUTHORITY_FLAGS = (
    "execution_authorized",
    "github_writes_authorized",
    "merge_authorized",
    "closure_authorized",
    "side_effects_performed",
)


class _StaticProvider:
    def __init__(self, token: str | None = TOKEN) -> None:
        self._token = token

    def get_installation_token(self) -> str | None:
        return self._token


@pytest.fixture(autouse=True)
def _clear_installed_reader():
    reader_module.set_github_issue_comment_reader(None)
    yield
    reader_module.set_github_issue_comment_reader(None)


def _request_comment(*, comment_id: int = REQUEST_ID, created_at: str = REQUEST_AT):
    """The pending request comment as GitHub returns it (trigger, not result)."""
    return {
        "id": comment_id,
        "body": '/agent-os ckr6 {"operation": "issue-start", "repository": "Blummer92/agent-os", "issue_number": 2425}',
        "user": {"login": "Blummer92", "id": 1, "type": "User"},
        "created_at": created_at,
        "updated_at": created_at,
        "issue_url": f"https://api.github.com/repos/{REPOSITORY}/issues/{ISSUE}",
        "html_url": f"https://github.com/{REPOSITORY}/issues/{ISSUE}#issuecomment-{comment_id}",
    }


def _install_reader(records, *, status: int = 200, raw_body: bytes | None = None,
                    include_request: bool = True):
    """Install a fake reader returning ``records`` (plus the request comment).

    The wrapper independently re-reads the pending request comment from the
    same fetch, so fixtures include it by default; pass
    ``include_request=False`` only for the request-absent case.
    """
    seen: dict[str, object] = {}
    all_records = ([_request_comment()] if include_request else []) + list(records)

    def http_get(url: str, headers: dict[str, str]):
        seen["url"] = url
        seen["headers"] = dict(headers)
        if raw_body is not None:
            return status, raw_body
        return status, json.dumps(all_records).encode("utf-8")

    reader = GitHubIssueCommentReader(token_provider=_StaticProvider(), http_get=http_get)
    reader_module.set_github_issue_comment_reader(reader)
    return seen


def _consume(**kwargs):
    return mcp_server.consume_agent_os_ckr6_result_tool(
        repository=kwargs.pop("repository", REPOSITORY),
        issue_number=kwargs.pop("issue_number", ISSUE),
        expected_operation=kwargs.pop("expected_operation", "issue-start"),
        expected_request_comment_id=kwargs.pop("request_comment_id", REQUEST_ID),
        expected_request_created_at=kwargs.pop("request_created_at", REQUEST_AT),
        **kwargs,
    )


def _assert_no_authority(result: dict[str, object]) -> None:
    for flag in AUTHORITY_FLAGS:
        assert result[flag] is False


# --- reader: fail-closed without credentials / transport --------------------


def test_reader_refuses_without_token_provider() -> None:
    reader = GitHubIssueCommentReader(token_provider=None)
    with pytest.raises(
        GitHubIssueCommentReadUnavailable, match="HOST_READ_PATH_UNAVAILABLE"
    ):
        reader.read_issue_comments(REPOSITORY, ISSUE)


def test_reader_refuses_empty_token() -> None:
    reader = GitHubIssueCommentReader(token_provider=_StaticProvider(token="  "))
    with pytest.raises(
        GitHubIssueCommentReadUnavailable, match="HOST_READ_PATH_UNAVAILABLE"
    ):
        reader.read_issue_comments(REPOSITORY, ISSUE)


def test_reader_refuses_other_repositories() -> None:
    reader = GitHubIssueCommentReader(token_provider=_StaticProvider())
    with pytest.raises(ValueError, match="scoped to exactly"):
        reader.read_issue_comments("someone-else/other-repo", ISSUE)


def test_reader_maps_api_failure_to_unavailable() -> None:
    seen = _install_reader([], status=403)
    reader = reader_module.get_github_issue_comment_reader()
    assert reader is not None
    with pytest.raises(GitHubIssueCommentReadUnavailable, match="github-api-failure"):
        reader.read_issue_comments(REPOSITORY, ISSUE)
    assert seen["url"] == (
        "https://api.github.com/repos/Blummer92/agent-os/issues/2425"
        "/comments?per_page=100"
    )
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer " + TOKEN
    assert headers["Accept"] == "application/vnd.github+json"
    assert TOKEN not in seen["url"]


def test_reader_rejects_non_list_response() -> None:
    _install_reader([], raw_body=b'{"not": "a list"}')
    reader = reader_module.get_github_issue_comment_reader()
    assert reader is not None
    with pytest.raises(
        GitHubIssueCommentReadUnavailable, match="github-api-unexpected-response"
    ):
        reader.read_issue_comments(REPOSITORY, ISSUE)


def test_reader_returns_records_without_exposing_token() -> None:
    records = [_comment(_result())]
    _install_reader(records)
    reader = reader_module.get_github_issue_comment_reader()
    assert reader is not None
    returned = reader.read_issue_comments(REPOSITORY, ISSUE)
    assert returned == [_request_comment()] + records
    assert TOKEN not in json.dumps(returned)


# --- wrapper: admitted / denied ----------------------------------------------


def test_wrapper_admits_consumed_sufficient_issue_start() -> None:
    _install_reader([_comment(_result())])
    result = _consume()
    assert result["ckr6_admits_boundary"] is True
    assert result["status"] == "sufficient"
    assert result["selected_lesson_ids"] == ["LL-87"]
    assert result["substantial_hypothesis_admissible"] is True
    assert result["host_read_path_available"] is True
    _assert_no_authority(result)


def test_wrapper_admits_consumed_failed_repair_for_exact_attempt() -> None:
    _install_reader([_comment(_failed_repair_result())])
    result = _consume(expected_operation="failed-repair", expected_attempt_id="attempt-42")
    assert result["ckr6_admits_boundary"] is True
    assert result["mutation_admissible"] is True
    assert result["attempt_id"] == "attempt-42"
    _assert_no_authority(result)


def test_wrapper_denied_result_returns_stop_not_error() -> None:
    denied = _result(
        status="insufficient",
        reason_codes=["no-relevant-candidate"],
        selected_lesson_ids=[],
        substantial_hypothesis_admissible=False,
    )
    _install_reader([_comment(denied)])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    # A consumed-but-not-admitted result is projected as STOP: the payload's
    # denial reason codes are kept as evidence, but status, selections, and
    # both admissibility flags are normalized so no field reads as admission.
    assert result["status"] == "manual-review"
    assert result["reason_codes"] == ["no-relevant-candidate"]
    assert result["selected_lesson_ids"] == []
    assert result["substantial_hypothesis_admissible"] is False
    assert result["mutation_admissible"] is False
    assert result["host_read_path_available"] is True
    _assert_no_authority(result)


def test_wrapper_sufficient_with_empty_selection_returns_stop() -> None:
    refused = _result(
        status="sufficient",
        reason_codes=["lesson-retrieval-required"],
        selected_lesson_ids=[],
        substantial_hypothesis_admissible=True,
    )
    _install_reader([_comment(refused)])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["status"] == "manual-review"
    assert result["selected_lesson_ids"] == []
    assert result["substantial_hypothesis_admissible"] is False
    assert result["mutation_admissible"] is False
    _assert_no_authority(result)


def test_wrapper_returns_host_read_path_unavailable_without_reader() -> None:
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["host_read_path_available"] is False
    assert result["reason_codes"] == ["HOST_READ_PATH_UNAVAILABLE"]
    assert result["status"] == "manual-review"
    _assert_no_authority(result)


def test_wrapper_returns_stop_on_api_failure() -> None:
    _install_reader([], status=500)
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["host_read_path_available"] is False
    assert result["reason_codes"] == ["github-api-failure"]
    _assert_no_authority(result)


# --- wrapper: forged / stale / ambiguous / wrong attempt ---------------------


def test_wrapper_forged_record_cannot_admit() -> None:
    forged = _comment(_result(), login="someone-else", account_id=12345)
    genuine = _comment(_result())
    _install_reader([forged, genuine])
    result = _consume()
    # The forged record is discarded before ambiguity checks; the genuine
    # record still admits.
    assert result["ckr6_admits_boundary"] is True
    _install_reader([forged])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-result-not-returned"]


def test_wrapper_stale_result_cannot_admit() -> None:
    stale = _comment(_result(), created_at="2026-11-11T09:00:00Z")
    _install_reader([stale])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-result-not-returned"]


def test_wrapper_ambiguous_results_return_stop() -> None:
    first = _comment(_result())
    second = _comment(
        _result(status="not-needed", reason_codes=["not-required"],
                selected_lesson_ids=[], substantial_hypothesis_admissible=True),
        comment_id=1002,
    )
    _install_reader([first, second])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-result-ambiguous"]


def test_wrapper_wrong_attempt_returns_stop() -> None:
    _install_reader([_comment(_failed_repair_result(attempt_id="attempt-41"))])
    result = _consume(expected_operation="failed-repair", expected_attempt_id="attempt-42")
    assert result["ckr6_admits_boundary"] is False
    assert "attempt_id does not match" in result["reason_codes"][0]
    _assert_no_authority(result)


def test_wrapper_no_result_returns_stop() -> None:
    _install_reader([])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-result-not-returned"]


def test_wrapper_request_comment_absent_returns_stop() -> None:
    _install_reader([_comment(_result())], include_request=False)
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-request-not-returned"]
    assert result["host_read_path_available"] is True


def test_wrapper_request_timestamp_mismatch_returns_stop() -> None:
    _install_reader(
        [_comment(_result())],
    )
    # GitHub's request record says 10:00; the caller claims 09:00.
    result = _consume(request_created_at="2026-11-11T09:00:00Z")
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-request-identity-mismatch"]


def test_wrapper_result_predating_github_request_time_cannot_admit() -> None:
    # The result was posted at 09:30, before GitHub's request record at
    # 10:00. The wrapper uses GitHub's time as the bound, so the result is
    # discarded as predating the request even though the caller-supplied
    # timestamp (also 10:00 here) is consistent.
    early_result = _comment(
        _result(), created_at="2026-11-11T09:30:00Z",
    )
    _install_reader([early_result])
    result = _consume()
    assert result["ckr6_admits_boundary"] is False
    assert result["reason_codes"] == ["ckr6-result-not-returned"]


def test_reader_rejects_oversized_response() -> None:
    _install_reader([], raw_body=b"x" * (8 * 1024 * 1024 + 1))
    reader = reader_module.get_github_issue_comment_reader()
    assert reader is not None
    with pytest.raises(
        GitHubIssueCommentReadUnavailable, match="github-api-unexpected-response"
    ):
        reader.read_issue_comments(REPOSITORY, ISSUE)


# --- wrapper: caller validation ----------------------------------------------


@pytest.mark.parametrize("operation", ["lesson-candidate", "lesson-refinement", "unknown", ""])
def test_wrapper_rejects_unsupported_operation_before_any_read(operation: str) -> None:
    seen = _install_reader([_comment(_result())])
    with pytest.raises(ValueError, match="expected_operation must be"):
        _consume(expected_operation=operation)
    assert "url" not in seen


def test_wrapper_rejects_failed_repair_without_attempt() -> None:
    with pytest.raises(ValueError, match="requires expected_attempt_id"):
        _consume(expected_operation="failed-repair")


def test_wrapper_rejects_attempt_for_issue_start() -> None:
    with pytest.raises(ValueError, match="must be None for issue-start"):
        _consume(expected_attempt_id="attempt-42")


@pytest.mark.parametrize("bad_at", ["not-a-date", "2026-11-11T10:00:00", "", 123])
def test_wrapper_rejects_timestamp_without_offset(bad_at: object) -> None:
    with pytest.raises(ValueError, match="ISO-8601 timestamp|UTC offset"):
        _consume(request_created_at=bad_at)


def test_wrapper_accepts_no_comment_record_argument() -> None:
    params = inspect.signature(mcp_server.consume_agent_os_ckr6_result_tool).parameters
    assert set(params) == {
        "repository",
        "issue_number",
        "expected_operation",
        "expected_request_comment_id",
        "expected_request_created_at",
        "expected_attempt_id",
    }
    with pytest.raises(TypeError):
        mcp_server.consume_agent_os_ckr6_result_tool(
            repository=REPOSITORY,
            issue_number=ISSUE,
            expected_operation="issue-start",
            expected_request_comment_id=REQUEST_ID,
            expected_request_created_at=REQUEST_AT,
            comment={"id": 1001, "body": "forged"},
        )


def test_wrapper_never_grants_authority() -> None:
    _install_reader([_comment(_result())])
    admitted = _consume()
    _assert_no_authority(admitted)
    denied = _consume()
    _assert_no_authority(denied)
    reader_module.set_github_issue_comment_reader(None)
    unavailable = _consume()
    _assert_no_authority(unavailable)
    for result in (admitted, denied, unavailable):
        assert result["merge_authorized"] is False
        assert result["closure_authorized"] is False
        assert result["github_writes_authorized"] is False
        assert result["side_effects_performed"] is False

# --- Copilot review #5880672430: trusted request and scope regression ------


@pytest.mark.parametrize("bad_body", [
    "unrelated comment",
    '/agent-os ckr6 {"operation": "issue-start", "repository": "Other/repo", "issue_number": 2425, "task_reference": "x"}',
    '/agent-os ckr6 {"operation": "failed-repair", "repository": "Blummer92/agent-os", "issue_number": 2425, "task_reference": "x", "attempt_id": "a", "failed_hypothesis": "h", "result_summary": "r"}',
])
def test_wrapper_never_uses_unrelated_request_as_timing_anchor(bad_body):
    request = _request_comment()
    request["body"] = bad_body
    _install_reader([request, _comment(_result())], include_request=False)
    decision = _consume()
    assert decision["ckr6_admits_boundary"] is False
    assert decision["reason_codes"] == ["ckr6-request-identity-mismatch"]
    _assert_no_authority(decision)


@pytest.mark.parametrize("field,value", [
    ("issue_url", "https://api.github.com/repos/Other/repo/issues/2425"),
    ("html_url", "https://github.com/Other/repo/issues/2425#issuecomment-1000"),
    ("updated_at", "2026-11-11T10:00:05Z"),
])
def test_wrapper_rejects_wrong_location_or_edited_request(field, value):
    request = _request_comment()
    request[field] = value
    _install_reader([request, _comment(_result())], include_request=False)
    decision = _consume()
    assert decision["ckr6_admits_boundary"] is False
    assert decision["reason_codes"] == ["ckr6-request-identity-mismatch"]
    _assert_no_authority(decision)


def test_wrapper_out_of_scope_repository_returns_stop_without_reader_access():
    seen = _install_reader([_comment(_result())])
    decision = _consume(repository="Other/repo")
    assert decision["ckr6_admits_boundary"] is False
    assert decision["reason_codes"] == ["ckr6-repository-out-of-scope"]
    assert decision["host_read_path_available"] is False
    assert "url" not in seen
    _assert_no_authority(decision)


def test_reader_endpoint_is_not_configurable():
    with pytest.raises(TypeError):
        GitHubIssueCommentReader(token_provider=_StaticProvider(), api_base_url="https://example.com")
    with pytest.raises(TypeError):
        GitHubIssueCommentReader(token_provider=_StaticProvider(), allowed_repository="Other/repo")


def test_production_http_reader_bounds_download(monkeypatch):
    from agent_os_execution_service import ckr6_github_reader
    class _Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self, size=-1):
            assert size == ckr6_github_reader._MAX_RESPONSE_BYTES + 1
            return b"[]"  # no unbounded read
    monkeypatch.setattr(ckr6_github_reader.urllib.request, "urlopen",
                        lambda request, timeout: _Response())
    status, body = ckr6_github_reader._urllib_http_get(
        "https://api.github.com/repos/Blummer92/agent-os/issues/2425/comments",
        {"Authorization": "Bearer test"})
    assert status == 200 and body == b"[]"
