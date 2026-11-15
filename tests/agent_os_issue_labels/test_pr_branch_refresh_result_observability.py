"""Terminal refresh-result observability (#3463).

Every terminal runner outcome must produce exactly one parseable
``agent-os-pr-refresh-result/v1`` line in ordinary stdout, carrying the
coded status/reasons plus invocation and trigger-comment correlation --
and nothing else (no receipt blob, no environment, no exception text).
Exit codes are the pre-existing contract: converged 0, blocked trigger 0,
any other runner outcome 1.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_actions import (
    BranchRefreshActionsTrigger,
    classify_branch_refresh_actions_trigger,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner import (
    RESULT_MARKER,
    BranchRefreshActionsExecutionResult,
    emit_refresh_result,
    format_refresh_result_line,
    main as runner_main,
    run_branch_refresh_actions,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization import (
    RefreshAuthorization,
    RefreshAuthorizationState,
)
from scripts.agent_os_issue_labels.pr_branch_refresh_authorization_source import (
    serialize_refresh_authorization_comment,
)

REPO = "Blummer92/agent-os"
HEAD = "1" * 40
MAIN = "2" * 40
WORKFLOW_REF = (
    "Blummer92/agent-os/.github/workflows/"
    "agent-os-governed-invocation.yml@refs/heads/main"
)
TRIGGER_COMMENT_ID = 6391174646


def authorization(**overrides) -> RefreshAuthorization:
    values = dict(
        schema_version="1.0",
        repository=REPO,
        pr_number=1619,
        base_branch="main",
        expected_head_sha=HEAD,
        expected_main_sha=MAIN,
        allowed_changed_paths=("a.py",),
        forbidden_paths=("b.py",),
        required_validation_command_ids=("pytest:pr-branch-refresh",),
        branch_refresh_authorized=True,
        label_write_authorized=True,
        owner_decision_reference="github-owner-decision:1619",
        state=RefreshAuthorizationState.AUTHORIZED,
    )
    values.update(overrides)
    return RefreshAuthorization(**values)


@dataclass
class FakeComment:
    id: int
    body: str
    login: str = "Blummer92"

    @property
    def user(self):
        return SimpleNamespace(login=self.login)

    @property
    def created_at(self):
        return datetime(2026, 9, 4, tzinfo=timezone.utc)


class FakeIssue:
    def __init__(self, comments):
        self.comments = list(comments)
        self.created = []

    def get_comments(self):
        # Model real GitHub: a receipt published by an earlier run is visible
        # to a later reacquisition of the same conversation.
        published = [FakeComment(100 + index, body) for index, body in enumerate(self.created)]
        return iter(list(self.comments) + published)

    def create_comment(self, body):
        self.created.append(body)


class FakeRepo:
    def __init__(self, comments, files=("a.py",)):
        self.owner = SimpleNamespace(login="Blummer92", type="User")
        self.issue = FakeIssue(comments)
        self.files = list(files)
        self.pr = SimpleNamespace(
            head=SimpleNamespace(sha=HEAD),
            get_files=lambda: [SimpleNamespace(filename=name) for name in self.files],
        )

    def get_issue(self, number):
        assert number == 1619
        return self.issue

    def get_pull(self, number):
        assert number == 1619
        return self.pr

    def get_branch(self, name):
        assert name == "main"
        return SimpleNamespace(commit=SimpleNamespace(sha=MAIN))


class FakeGithub:
    def __init__(self, comments, files=("a.py",)):
        self.repo = FakeRepo(comments, files=files)

    def get_repo(self, repository):
        assert repository == REPO
        return self.repo


def trigger(**overrides):
    values = dict(
        status="accepted",
        reason="finite-refresh-operation-requested",
        pr_number=1619,
        repository=REPO,
        trigger_comment_id=TRIGGER_COMMENT_ID,
    )
    values.update(overrides)
    return BranchRefreshActionsTrigger(**values)


def converged_refresh(auth, calls):
    def refresh(**kwargs):
        calls.append(kwargs)
        return {
            "status": "converged",
            "authorization_id": auth.authorization_id,
            "authorization_consumed": True,
            "admitted_main_sha": MAIN,
            "old_head_sha": HEAD,
            "new_head_sha": "3" * 40,
            "mutation_count": 1,
            "reason_codes": ("branch.current-proven",),
            "side_effects_performed": True,
        }

    return refresh


def run(github, **overrides):
    values = dict(
        trigger=trigger(),
        github_client=github,
        repository_root="/repo",
        invocation_id="actions:40145100948:1",
        environment={"GITHUB_TOKEN": "secret-token-123"},
    )
    values.update(overrides)
    return run_branch_refresh_actions(**values)


def parse_marker(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.startswith(RESULT_MARKER)]
    assert len(lines) == 1, f"expected exactly one marker line, got: {stdout!r}"
    marker, payload = lines[0].split(" ", 1)
    assert marker == RESULT_MARKER
    parsed = json.loads(payload)
    # Canonical compact serialization: re-serializing must be byte-identical.
    assert payload == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return parsed


# --- result-level outcomes -------------------------------------------------

def test_successful_refresh_result_carries_correlation():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    calls = []
    result = run(github, refresh_callable=converged_refresh(auth, calls))
    assert result.status == "converged"
    assert result.invocation_id == "actions:40145100948:1"
    assert result.trigger_comment_id == TRIGGER_COMMENT_ID
    assert len(calls) == 1
    line = format_refresh_result_line(result)
    parsed = json.loads(line.split(" ", 1)[1])
    assert parsed["status"] == "converged"
    assert parsed["invocation_id"] == "actions:40145100948:1"
    assert parsed["trigger_comment_id"] == TRIGGER_COMMENT_ID
    assert parsed["authorization_id"] == auth.authorization_id


def test_missing_authorization_blocks_without_facade_call():
    github = FakeGithub([])
    calls = []
    result = run(github, refresh_callable=lambda **kwargs: calls.append(kwargs))
    assert result.status == "blocked"
    assert result.reason_codes == ("authorization.absent",)
    assert result.mutation_count == 0
    assert not calls
    assert result.invocation_id == "actions:40145100948:1"
    assert result.trigger_comment_id == TRIGGER_COMMENT_ID


def test_expired_authorization_blocks():
    auth = authorization(state=RefreshAuthorizationState.EXPIRED)
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    calls = []
    result = run(github, refresh_callable=lambda **kwargs: calls.append(kwargs))
    assert result.status == "blocked"
    assert "authorization.consumed-or-not-current" in result.reason_codes
    assert not calls


def test_stale_head_blocks():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    github.repo.pr.head.sha = "4" * 40
    result = run(github, refresh_callable=lambda **kwargs: (_ for _ in ()).throw(AssertionError("facade must not run")))
    assert result.status == "blocked"
    assert "head.moved" in result.reason_codes


def test_changed_main_blocks():
    auth = authorization(expected_main_sha="5" * 40)
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    result = run(github, refresh_callable=lambda **kwargs: (_ for _ in ()).throw(AssertionError("facade must not run")))
    assert result.status == "blocked"
    assert "main.moved" in result.reason_codes


def test_changed_file_scope_blocks():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))], files=("a.py", "c.py"))
    result = run(github, refresh_callable=lambda **kwargs: (_ for _ in ()).throw(AssertionError("facade must not run")))
    assert result.status == "blocked"
    assert "scope.expanded" in result.reason_codes
    github2 = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))], files=("a.py", "b.py"))
    result2 = run(github2, refresh_callable=lambda **kwargs: (_ for _ in ()).throw(AssertionError("facade must not run")))
    assert "scope.forbidden-path" in result2.reason_codes


def test_parser_rejected_trigger_blocks_with_correlation_and_no_github_use():
    blocked = trigger(status="blocked", reason="operation-not-requested", pr_number=None)
    result = run_branch_refresh_actions(
        trigger=blocked, github_client=object(), repository_root="/repo",
        invocation_id="actions:1:1", environment={},
        refresh_callable=lambda **kwargs: (_ for _ in ()).throw(AssertionError("facade must not run")),
    )
    assert result.status == "blocked"
    assert result.reason_codes == ("operation-not-requested",)
    assert result.invocation_id == "actions:1:1"
    assert result.trigger_comment_id == TRIGGER_COMMENT_ID


def test_runtime_failure_propagates_from_runner_for_main_to_convert():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])

    def failing(**kwargs):
        raise RuntimeError("provider exploded with ghp_secret")

    with pytest.raises(RuntimeError):
        run(github, refresh_callable=failing)


def test_malformed_result_becomes_needs_decision():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])

    def malformed(**kwargs):
        return {"status": 123, "mutation_count": 99, "reason_codes": "not-a-list"}

    result = run(github, refresh_callable=malformed)
    assert result.status == "needs-decision"
    assert result.reason_codes == ("actions.malformed-refresh-receipt",)
    assert result.mutation_count == 0


def test_duplicate_invocation_is_blocked_by_receipt_consumption():
    auth = authorization()
    github = FakeGithub([FakeComment(10, serialize_refresh_authorization_comment(auth))])
    calls = []
    first = run(github, refresh_callable=converged_refresh(auth, calls))
    assert first.status == "converged"
    assert github.repo.issue.created, "first run must publish its consumption receipt"
    second = run(github, refresh_callable=converged_refresh(auth, calls))
    assert second.status == "blocked"
    assert "authorization.consumed-or-not-current" in second.reason_codes
    assert len(calls) == 1


def test_missing_or_malformed_correlation_identifiers_fail_closed():
    github = FakeGithub([])
    for bad_id in ("", "   ", None, 123):
        with pytest.raises((ValueError, TypeError)):
            run(github, invocation_id=bad_id, refresh_callable=lambda **kwargs: None)
    with pytest.raises(ValueError):
        BranchRefreshActionsExecutionResult(
            repository=REPO, pr_number=1619, status="blocked",
            reason_codes=("x",), trigger_comment_id=0,
        )


def test_deterministic_json_serialization_and_no_sensitive_output():
    result = BranchRefreshActionsExecutionResult(
        repository=REPO, pr_number=3723, status="needs-decision",
        reason_codes=("actions.malformed-refresh-receipt",),
        refresh_receipt={"token": "ghp_secret-token-123", "error": "unbounded provider boom"},
        invocation_id="actions:40145100948:1", trigger_comment_id=TRIGGER_COMMENT_ID,
    )
    line = format_refresh_result_line(result)
    assert format_refresh_result_line(result) == line
    assert "ghp_secret-token-123" not in line
    assert "unbounded provider boom" not in line
    assert "refresh_receipt" not in line
    parsed = json.loads(line.split(" ", 1)[1])
    assert parsed["reason_codes"] == ["actions.malformed-refresh-receipt"]
    with pytest.raises(TypeError):
        format_refresh_result_line(object())  # type: ignore[arg-type]


# --- classifier correlation -------------------------------------------------

def _event(body="/agent-os refresh-pr 1619", comment_id=TRIGGER_COMMENT_ID, login="Blummer92", user_id=32861845):
    comment: dict[str, object] = {"body": body, "user": {"login": login, "id": user_id}}
    if comment_id is not None:
        comment["id"] = comment_id
    return {
        "action": "created",
        "issue": {"number": 1807, "pull_request": None},
        "comment": comment,
        "repository": {"id": 1289370915, "full_name": REPO},
    }


def _classify(event, **overrides):
    values = dict(repository=REPO, repository_id=1289370915, ref="refs/heads/main", workflow_ref=WORKFLOW_REF, run_attempt=1)
    values.update(overrides)
    return classify_branch_refresh_actions_trigger(event, **values)


def test_trigger_comment_id_carried_for_accepted_and_blocked_triggers():
    assert _classify(_event()).trigger_comment_id == TRIGGER_COMMENT_ID
    assert _classify(_event(login="someone", user_id=7)).trigger_comment_id == TRIGGER_COMMENT_ID
    assert _classify(_event(comment_id="not-an-int")).trigger_comment_id is None
    assert _classify(_event(comment_id=0)).trigger_comment_id is None


# --- main() terminal behaviour ----------------------------------------------

def _main_args(tmp_path, event, invocation_id="actions:40145100948:1", run_attempt=1):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output = tmp_path / "result.json"
    return [
        "--event", str(event_path),
        "--repository", REPO,
        "--repository-id", "1289370915",
        "--ref", "refs/heads/main",
        "--workflow-ref", WORKFLOW_REF,
        "--run-attempt", str(run_attempt),
        "--repository-root", "/repo",
        "--invocation-id", invocation_id,
        "--output", str(output),
    ], output


def test_main_blocked_trigger_emits_exactly_one_marker_and_exits_zero(tmp_path, capsys):
    args, output = _main_args(tmp_path, _event(body="/agent-os refresh-pr 1619 extra"))
    assert runner_main(args) == 0
    parsed = parse_marker(capsys.readouterr().out)
    assert parsed["status"] == "blocked"
    assert parsed["reason_codes"] == ["operation-not-requested"]
    assert parsed["trigger_comment_id"] == TRIGGER_COMMENT_ID
    assert json.loads(output.read_text())["status"] == "blocked"


def test_main_rerun_duplicate_invocation_emits_blocked_marker(tmp_path, capsys):
    args, _ = _main_args(tmp_path, _event(), run_attempt=2)
    assert runner_main(args) == 0
    parsed = parse_marker(capsys.readouterr().out)
    assert parsed["reason_codes"] == ["rerun-not-allowed"]


def test_main_malformed_event_emits_runtime_failure_marker(tmp_path, capsys):
    event_path = tmp_path / "event.json"
    event_path.write_text("{not json", encoding="utf-8")
    output = tmp_path / "result.json"
    args = [
        "--event", str(event_path), "--repository", REPO, "--repository-id", "1289370915",
        "--ref", "refs/heads/main", "--workflow-ref", WORKFLOW_REF, "--run-attempt", "1",
        "--repository-root", "/repo", "--invocation-id", "actions:1:1", "--output", str(output),
    ]
    assert runner_main(args) == 1
    parsed = parse_marker(capsys.readouterr().out)
    assert parsed["status"] == "needs-decision"
    assert parsed["reason_codes"] == ["actions.runtime-failure"]
    assert parsed["pr_number"] is None


def test_main_runtime_failure_emits_marker_and_preserves_exit_code(tmp_path, capsys, monkeypatch):
    import scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner as runner_module

    monkeypatch.setattr(runner_module, "build_branch_refresh_github_client", lambda env: (_ for _ in ()).throw(RuntimeError("client exploded with ghp_secret")))
    args, _ = _main_args(tmp_path, _event())
    assert runner_main(args) == 1
    out = capsys.readouterr().out
    parsed = parse_marker(out)
    assert parsed["reason_codes"] == ["actions.runtime-failure"]
    assert parsed["trigger_comment_id"] == TRIGGER_COMMENT_ID
    assert "ghp_secret" not in out
    assert "client exploded" not in out


def test_main_missing_invocation_emits_marker_and_fails(tmp_path, capsys):
    args, _ = _main_args(tmp_path, _event(), invocation_id="")
    assert runner_main(args) == 1
    parsed = parse_marker(capsys.readouterr().out)
    assert parsed["reason_codes"] == ["actions.runtime-failure"]
    assert parsed["invocation_id"] is None


def test_main_blank_repository_emits_marker_and_fails(tmp_path, capsys):
    # QA F1: a blank --repository must not raise before the marker.
    args, _ = _main_args(tmp_path, _event())
    blank_repo_args = [value if value != REPO else "" for value in args]
    assert runner_main(blank_repo_args) == 1
    parsed = parse_marker(capsys.readouterr().out)
    assert parsed["reason_codes"] == ["actions.runtime-failure"]
    assert parsed["repository"] is None
    assert parsed["invocation_id"] == "actions:40145100948:1"


def test_main_success_and_blocked_refresh_preserve_exit_codes(tmp_path, capsys, monkeypatch):
    import scripts.agent_os_issue_labels.pr_branch_refresh_actions_runner as runner_module

    converged = BranchRefreshActionsExecutionResult(
        repository=REPO, pr_number=1619, status="converged", reason_codes=("branch.current-proven",),
        mutation_count=1, side_effects_performed=True,
        invocation_id="actions:40145100948:1", trigger_comment_id=TRIGGER_COMMENT_ID,
    )
    monkeypatch.setattr(runner_module, "run_branch_refresh_actions", lambda **kwargs: converged)
    monkeypatch.setattr(runner_module, "build_branch_refresh_github_client", lambda env: object())
    args, _ = _main_args(tmp_path, _event())
    assert runner_main(args) == 0
    assert parse_marker(capsys.readouterr().out)["status"] == "converged"

    blocked = BranchRefreshActionsExecutionResult(
        repository=REPO, pr_number=1619, status="blocked", reason_codes=("authorization.absent",),
        invocation_id="actions:40145100948:1", trigger_comment_id=TRIGGER_COMMENT_ID,
    )
    monkeypatch.setattr(runner_module, "run_branch_refresh_actions", lambda **kwargs: blocked)
    args, _ = _main_args(tmp_path, _event())
    assert runner_main(args) == 1
    assert parse_marker(capsys.readouterr().out)["status"] == "blocked"


def test_emit_refresh_result_prints_exactly_one_line(capsys):
    result = BranchRefreshActionsExecutionResult(repository=REPO, pr_number=1619, status="blocked", reason_codes=("authorization.absent",))
    line = emit_refresh_result(result)
    assert capsys.readouterr().out == line + "\n"
    assert line.startswith(RESULT_MARKER + " ")
