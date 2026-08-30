from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.agent_os_issue_acceptance.models import Status
from scripts.agent_os_issue_labels import issue_create as issue_create_module
from scripts.agent_os_issue_labels import issue_create_cli
from scripts.agent_os_issue_labels.draft import IssueDraftInput, build_issue_draft
from scripts.agent_os_issue_labels.issue_create import (
    GitHubRepositoryTarget,
    IssueCreateConfirmation,
    IssueCreateExitCode,
    IssueCreateProcessResult,
    IssueCreateReasonCode,
    IssueCreateRequest,
    MutationState,
    SubprocessGhRunner,
    build_issue_create_argv,
    build_issue_readback_argv,
    execute_issue_creation,
    issue_create_result_to_dict,
    plan_issue_creation,
    render_issue_create_result,
    sanitize_diagnostic_text,
)
from scripts.agent_os_issue_labels.validation import DraftReasonCode, validate_issue_draft

ROOT = Path(__file__).resolve().parents[2]
FORM = ROOT / ".github/ISSUE_TEMPLATE/agent-os-task.yml"
MAP = ROOT / ".github/labeler/agent-os-issue-label-map.yml"
FIXTURE = ROOT / "tests/fixtures/agent_os_issue_labels/draft_minimum_valid.json"
TARGET = GitHubRepositoryTarget.parse("Blummer92/agent-os")


class Runner:
    def __init__(self, *, executable="gh", create=None, readback=None, overrides=None):
        self.executable = executable
        self.create = create or IssueCreateProcessResult(
            0, "https://github.com/Blummer92/agent-os/issues/700\n", ""
        )
        self.readback = readback
        self.overrides = overrides or {}
        self.calls = []
        self.submitted_title = None
        self.submitted_body = None
        self.submitted_labels = ()

    def resolve_executable(self):
        return self.executable

    def run(self, argv, *, input_text=None, timeout=30.0):
        key = tuple(argv)
        self.calls.append((key, input_text, timeout))
        if key in self.overrides:
            return self.overrides[key]
        defaults = {
            (self.executable, "--version"): IssueCreateProcessResult(
                0, "gh version 2.80.0\n", ""
            ),
            (self.executable, "issue", "create", "--help"): IssueCreateProcessResult(
                0, "--repo --title --body-file --label\n", ""
            ),
            (self.executable, "issue", "view", "--help"): IssueCreateProcessResult(
                0, "--repo --json\n", ""
            ),
            (
                self.executable, "auth", "status", "--active", "--hostname",
                "github.com",
            ): IssueCreateProcessResult(
                0, "Logged in to github.com account tester\n", ""
            ),
            (
                self.executable, "repo", "view", "github.com/Blummer92/agent-os",
                "--json", "nameWithOwner,url,hasIssuesEnabled,isArchived",
            ): IssueCreateProcessResult(
                0,
                json.dumps({
                    "nameWithOwner": "Blummer92/agent-os",
                    "url": "https://github.com/Blummer92/agent-os",
                    "hasIssuesEnabled": True,
                    "isArchived": False,
                }),
                "",
            ),
        }
        if key in defaults:
            return defaults[key]
        if "--body-file=-" in key:
            self.submitted_title = next(
                value[len("--title=") :] for value in key if value.startswith("--title=")
            )
            self.submitted_body = input_text or ""
            self.submitted_labels = tuple(
                value[len("--label=") :] for value in key if value.startswith("--label=")
            )
            expected = len((input_text or "").encode("utf-8"))
            updates = {}
            if self.create.stdin_bytes_expected is None:
                updates["stdin_bytes_expected"] = expected
            if self.create.stdin_bytes_written is None:
                updates["stdin_bytes_written"] = expected
            if self.create.stdin_delivery_completed is None:
                updates["stdin_delivery_completed"] = not self.create.stdin_error
            return replace(self.create, **updates)
        if len(key) >= 4 and key[1:3] == ("issue", "view"):
            if self.readback is not None:
                return self.readback
            number = int(key[3])
            return IssueCreateProcessResult(
                0,
                json.dumps(
                    {
                        "number": number,
                        "url": f"https://github.com/Blummer92/agent-os/issues/{number}",
                        "title": self.submitted_title,
                        "body": self.submitted_body,
                        "labels": [{"name": label} for label in self.submitted_labels],
                    }
                ),
                "",
            )
        raise AssertionError(key)


class _ByteStream:
    def __init__(self, data=b""):
        self.data = bytearray(data)

    def read(self, size=-1):
        if not self.data:
            return b""
        if size < 0:
            size = len(self.data)
        value = bytes(self.data[:size])
        del self.data[:size]
        return value


class _Stdin:
    def __init__(self, actions, *, close_error=None):
        self.actions = list(actions)
        self.close_error = close_error

    def write(self, value):
        action = self.actions.pop(0) if self.actions else len(value)
        if isinstance(action, BaseException):
            raise action
        return min(int(action), len(value))

    def flush(self):
        return None

    def close(self):
        if self.close_error is not None:
            raise self.close_error


class _Process:
    def __init__(self, stdin):
        self.stdin = stdin
        self.stdout = _ByteStream(
            b"https://github.com/Blummer92/agent-os/issues/700\n"
        )
        self.stderr = _ByteStream()
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def poll(self):
        return self.returncode


class Confirm:
    def __init__(
        self, *, invocation="inv-1", confirmed=True, fingerprint=None,
        target=None, warnings=None
    ):
        self.invocation = invocation
        self.confirmed = confirmed
        self.fingerprint = fingerprint
        self.target = target
        self.warnings = warnings

    def confirm(self, plan):
        return IssueCreateConfirmation(
            self.invocation,
            self.fingerprint or plan.operation_fingerprint,
            self.target or plan.target.canonical,
            self.confirmed,
            plan.warning_reason_codes if self.warnings is None else self.warnings,
        )


class Missing:
    def confirm(self, plan):
        return None


def validation():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source = IssueDraftInput.from_mapping(payload)
    draft = build_issue_draft(source, FORM, MAP)
    return validate_issue_draft(draft, source, FORM)


def request(*, result=None, invocation="inv-1", prior=(), optional=()):
    return IssueCreateRequest(
        result or validation(), TARGET, invocation,
        prior_fingerprints=prior, optional_metadata=optional,
    )


def creates(runner):
    return [call for call in runner.calls if "--body-file=-" in call[0]]


def readbacks(runner):
    return [
        call for call in runner.calls
        if len(call[0]) >= 4
        and call[0][1:3] == ("issue", "view")
        and call[0][3] != "--help"
    ]


def readback_process(**changes):
    baseline = validation().draft
    payload = {
        "number": 700,
        "url": "https://github.com/Blummer92/agent-os/issues/700",
        "title": baseline.title,
        "body": baseline.body,
        "labels": [{"name": label} for label in baseline.proposed_labels],
    }
    payload.update(changes)
    return IssueCreateProcessResult(0, json.dumps(payload), "")


def warned():
    return replace(
        validation(), status=Status.WARN,
        reason_codes=(
            DraftReasonCode.ELIGIBLE_WARNING,
            DraftReasonCode.DUPLICATE_CANDIDATE_ADVISORY,
        ),
        submission_eligible=True,
    )


@pytest.mark.parametrize(
    "value",
    (
        "widgets", " github.com/acme/widgets", "github_com/acme/widgets",
        "github.com/./widgets", "github.com/../widgets",
        "github.com/acme/widgets/extra", "github.com/acme/",
        "例.example/acme/widgets",
    ),
)
def test_target_parsing(value):
    with pytest.raises(ValueError):
        GitHubRepositoryTarget.parse(value)


def test_argv_controls_identity_and_eligibility():
    target = GitHubRepositoryTarget.parse("ghe.example.com/acme/widgets")
    argv = build_issue_create_argv(
        target, "-title", ("z", "-label", "z"), executable="/opt/gh"
    )
    assert "--title=-title" in argv and "--label=-label" in argv
    assert "--body-file=-" in argv
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "bad\ntitle", ())
    with pytest.raises(ValueError):
        build_issue_create_argv(target, "title", ("bad\rlabel",))
    first, error = plan_issue_creation(request(invocation="one"), Runner())
    second, second_error = plan_issue_creation(request(invocation="two"), Runner())
    assert error is second_error is None
    assert first.operation_identity == second.operation_identity
    assert first.operation_fingerprint != second.operation_fingerprint
    for changed in (
        replace(validation(), submission_eligible=False),
        replace(validation(), status=Status.MANUAL_REVIEW),
        replace(validation(), status=Status.FAIL),
        replace(validation(), write_authorized=True),
        replace(validation(), mutation_performed=True),
    ):
        probe = Runner()
        plan, failure = plan_issue_creation(request(result=changed), probe)
        assert plan is None
        assert failure.reason_code == IssueCreateReasonCode.VALIDATION_INELIGIBLE
        assert probe.calls == []
    plan, failure = plan_issue_creation(request(optional=("project",)), Runner())
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.OPTIONAL_METADATA_UNSUPPORTED


@pytest.mark.parametrize(
    "provider, reason",
    (
        (Missing(), IssueCreateReasonCode.CONFIRMATION_MISSING),
        (Confirm(confirmed=False), IssueCreateReasonCode.CONFIRMATION_CANCELLED),
        (Confirm(fingerprint="stale"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
        (Confirm(invocation="other"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
        (Confirm(target="github.com/other/repo"), IssueCreateReasonCode.CONFIRMATION_STALE_OR_MISMATCHED),
    ),
)
def test_confirmation_failures(provider, reason):
    probe = Runner()
    result = execute_issue_creation(request(), probe, provider)
    assert result.reason_code == reason
    assert creates(probe) == []


def test_warning_success_body_repeat_and_serializers():
    warning = warned()
    rejected_runner = Runner()
    rejected = execute_issue_creation(
        request(result=warning), rejected_runner, Confirm(warnings=())
    )
    assert rejected.reason_code == IssueCreateReasonCode.ELIGIBLE_WARNING_NOT_ACCEPTED
    assert creates(rejected_runner) == []
    runner = Runner()
    draft = request(result=warning)
    result = execute_issue_creation(draft, runner, Confirm())
    call = creates(runner)[0]
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.mutation_state == MutationState.CONFIRMED
    assert call[1] == draft.validation.draft.body
    assert draft.validation.draft.body not in call[0]
    plan, error = plan_issue_creation(request(invocation="first"), Runner())
    assert error is None
    repeat_plan, repeated = plan_issue_creation(
        request(invocation="second", prior=(plan.operation_identity,)), Runner()
    )
    assert repeat_plan is None and repeated.exit_code == 80
    payload = issue_create_result_to_dict(result)
    assert payload["reason_code"] == result.reason_code.value
    assert result.operation_identity in render_issue_create_result(result)


def test_readback_builder_is_bounded_and_success_is_verified():
    argv = build_issue_readback_argv(TARGET, 700, executable="/opt/gh")
    assert argv == (
        "/opt/gh",
        "issue",
        "view",
        "700",
        "--repo=github.com/Blummer92/agent-os",
        "--json",
        "number,url,title,body,labels",
    )
    with pytest.raises(ValueError):
        build_issue_readback_argv(TARGET, 0)
    with pytest.raises(ValueError):
        build_issue_readback_argv(TARGET, True)

    runner = Runner()
    result = execute_issue_creation(request(), runner, Confirm())
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.reason_codes == (
        IssueCreateReasonCode.CREATE_CONFIRMED,
        IssueCreateReasonCode.READBACK_VERIFIED,
    )
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert result.readback_attempted is True
    assert result.readback_verified is True
    assert result.readback_reason == IssueCreateReasonCode.READBACK_VERIFIED.value
    assert result.readback_raw_process_exit_code == 0
    assert result.readback_output_digest.startswith("sha256=")
    assert len(readbacks(runner)) == 1
    assert readbacks(runner)[0][1] is None
    payload = issue_create_result_to_dict(result)
    rendered = render_issue_create_result(result)
    assert payload["readback_verified"] is True
    assert payload["readback_reason"] == "readback-verified"
    assert "Read-back verified: yes" in rendered
    assert "Read-back reason: readback-verified" in rendered


@pytest.mark.parametrize(
    "process, reason",
    (
        (IssueCreateProcessResult(1, "", "network"), IssueCreateReasonCode.READBACK_COMMAND_FAILED),
        (IssueCreateProcessResult(None, timed_out=True), IssueCreateReasonCode.READBACK_TIMEOUT),
        (IssueCreateProcessResult(None, interrupted=True), IssueCreateReasonCode.READBACK_INTERRUPTED),
        (IssueCreateProcessResult(0, "{", ""), IssueCreateReasonCode.READBACK_MALFORMED),
        (IssueCreateProcessResult(0, "[]", ""), IssueCreateReasonCode.READBACK_MALFORMED),
    ),
)
def test_readback_failures_preserve_confirmed_creation(process, reason):
    runner = Runner(readback=process)
    result = execute_issue_creation(request(), runner, Confirm())
    assert result.reason_code == reason
    assert result.exit_code == IssueCreateExitCode.READBACK_FAILURE
    assert result.reason_codes == (reason, IssueCreateReasonCode.CREATE_CONFIRMED)
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.mutation_performed is True
    assert result.created_issue_number == 700
    assert result.readback_attempted is True
    assert result.readback_verified is False
    assert result.readback_reason == reason.value
    assert result.retry_allowed is False
    assert "do not retry or mutate automatically" in result.recovery_evidence[0]
    assert len(creates(runner)) == 1
    assert len(readbacks(runner)) == 1


@pytest.mark.parametrize(
    "changes",
    (
        {"number": 701},
        {"url": "https://github.com/other/repo/issues/700"},
        {"url": "https://github.com/Blummer92/agent-os/issues/701"},
        {"number": True},
    ),
)
def test_readback_identity_mismatch_fails_closed(changes):
    process = readback_process(**changes)
    result = execute_issue_creation(request(), Runner(readback=process), Confirm())
    expected = (
        IssueCreateReasonCode.READBACK_MALFORMED
        if changes.get("number") is True
        else IssueCreateReasonCode.READBACK_IDENTITY_MISMATCH
    )
    assert result.reason_code == expected
    assert result.mutation_state == MutationState.CONFIRMED
    assert result.readback_verified is False


@pytest.mark.parametrize("field", ("title", "body"))
def test_readback_content_mismatch_fails_closed(field):
    process = readback_process(**{field: "unexpected persisted content"})
    result = execute_issue_creation(request(), Runner(readback=process), Confirm())
    assert result.reason_code == IssueCreateReasonCode.READBACK_CONTENT_MISMATCH
    assert result.mutation_performed is True
    assert result.readback_verified is False


@pytest.mark.parametrize(
    "labels",
    (
        [],
        [{"name": "unexpected"}],
        [{"name": label} for label in validation().draft.proposed_labels] + [
            {"name": validation().draft.proposed_labels[0]}
        ],
    ),
)
def test_readback_label_mismatch_including_duplicates(labels):
    result = execute_issue_creation(
        request(), Runner(readback=readback_process(labels=labels)), Confirm()
    )
    assert result.reason_code == IssueCreateReasonCode.READBACK_LABEL_MISMATCH
    assert result.mutation_performed is True
    assert result.readback_verified is False


@pytest.mark.parametrize(
    "labels",
    (None, ["label"], [{"name": None}], [{}]),
)
def test_readback_malformed_label_shape_fails_closed(labels):
    result = execute_issue_creation(
        request(), Runner(readback=readback_process(labels=labels)), Confirm()
    )
    assert result.reason_code == IssueCreateReasonCode.READBACK_MALFORMED
    assert result.mutation_performed is True


def test_readback_diagnostics_do_not_expose_submitted_content():
    base = validation()
    protected = replace(
        base,
        draft=replace(
            base.draft,
            title="private title",
            body="private body\nsecond line",
            proposed_labels=("private-label",),
        ),
    )
    escaped_body = json.dumps(protected.draft.body, ensure_ascii=False)[1:-1]
    diagnostic = (
        "private title\nprivate-label\nprivate body\nsecond line\n" + escaped_body
    )
    result = execute_issue_creation(
        request(result=protected),
        Runner(readback=IssueCreateProcessResult(1, diagnostic, diagnostic)),
        Confirm(),
    )
    combined = render_issue_create_result(result) + json.dumps(
        issue_create_result_to_dict(result), ensure_ascii=False
    )
    for value in (
        "private title",
        "private-label",
        "private body",
        "second line",
        escaped_body,
    ):
        assert value not in combined
    assert result.readback_output_digest.startswith("sha256=")
    assert "[REDACTED]" in result.readback_sanitized_stderr


def test_failed_or_uncertain_create_never_reads_back_or_corrects():
    for create in (
        IssueCreateProcessResult(1, "", "failed"),
        IssueCreateProcessResult(0, "created", ""),
    ):
        runner = Runner(create=create)
        result = execute_issue_creation(request(), runner, Confirm())
        assert result.mutation_state != MutationState.CONFIRMED
        assert readbacks(runner) == []
        assert result.readback_attempted is False

    runner = Runner(readback=readback_process(title="mismatch"))
    result = execute_issue_creation(request(), runner, Confirm())
    assert result.reason_code == IssueCreateReasonCode.READBACK_CONTENT_MISMATCH
    assert len(readbacks(runner)) == 1
    commands = [call[0][1:3] for call in runner.calls if len(call[0]) >= 3]
    assert ("issue", "edit") not in commands
    assert ("issue", "close") not in commands
    assert ("issue", "delete") not in commands


def test_success_parsing_precedes_sensitive_output_redaction():
    issue_url = "https://github.com/Blummer92/agent-os/issues/700"
    baseline = validation()
    protected = replace(
        baseline,
        draft=replace(baseline.draft, body=issue_url),
    )
    runner = Runner(create=IssueCreateProcessResult(0, issue_url + "\n", ""))
    result = execute_issue_creation(request(result=protected), runner, Confirm())
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.created_issue_url == issue_url
    assert result.created_issue_number == 700
    assert issue_url not in result.sanitized_stdout
    assert "[REDACTED]" in result.sanitized_stdout


def test_success_url_is_reconstructed_from_validated_target():
    raw = "https://GITHUB.COM/blummer92/AGENT-OS/issues/700"
    result = execute_issue_creation(
        request(), Runner(create=IssueCreateProcessResult(0, raw + "\n", "")), Confirm()
    )
    assert result.reason_code == IssueCreateReasonCode.CREATE_CONFIRMED
    assert result.created_issue_url == (
        "https://github.com/Blummer92/agent-os/issues/700"
    )


@pytest.mark.parametrize(
    "url",
    (
        "https://user@github.com/Blummer92/agent-os/issues/700",
        "https://user:password@github.com/Blummer92/agent-os/issues/700",
        "https://github.com:443/Blummer92/agent-os/issues/700",
        "https://github.com%2f@evil.example/Blummer92/agent-os/issues/700",
        "https://github.com/Blummer92/agent-os/issues/%37%30%30",
        "https://github.com/Blummer92/agent-os/issues/0700",
        "https://github.com/Blummer92/agent-os/issues/700\x00",
    ),
)
def test_noncanonical_success_urls_are_uncertain_and_not_exposed(url):
    result = execute_issue_creation(
        request(), Runner(create=IssueCreateProcessResult(0, url + "\n", "")), Confirm()
    )
    assert result.reason_code == IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT
    assert result.mutation_state == MutationState.UNCERTAIN
    assert result.created_issue_url is None
    assert "user:password@" not in render_issue_create_result(result)


def test_zero_exit_valid_url_with_incomplete_stdin_is_uncertain():
    expected = len(validation().draft.body.encode("utf-8"))
    process = IssueCreateProcessResult(
        0,
        "https://github.com/Blummer92/agent-os/issues/700\n",
        "",
        stdin_bytes_expected=expected,
        stdin_bytes_written=expected - 1,
        stdin_delivery_completed=False,
        stdin_error="BrokenPipeError",
    )
    result = execute_issue_creation(request(), Runner(create=process), Confirm())
    assert result.reason_code == IssueCreateReasonCode.STDIN_DELIVERY_INCOMPLETE
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.stdin_bytes_expected == expected
    assert result.stdin_bytes_written == expected - 1
    assert result.stdin_delivery_completed is False
    combined = render_issue_create_result(result) + json.dumps(
        issue_create_result_to_dict(result)
    )
    assert validation().draft.body not in combined
    assert not result.retry_allowed


@pytest.mark.parametrize(
    "actions, close_error, expected_written, completed, error_type",
    (
        ((6,), None, 6, True, ""),
        ((BrokenPipeError(),), None, 0, False, "BrokenPipeError"),
        ((2, BrokenPipeError()), None, 2, False, "BrokenPipeError"),
        ((OSError(5, "write failed"),), None, 0, False, "OSError"),
        ((6,), OSError(5, "close failed"), 6, False, "OSError"),
    ),
)
def test_subprocess_runner_records_stdin_delivery(
    monkeypatch, actions, close_error, expected_written, completed, error_type
):
    stdin = _Stdin(actions, close_error=close_error)
    monkeypatch.setattr(issue_create_module.shutil, "which", lambda _: "/opt/bin/gh")
    monkeypatch.setattr(
        issue_create_module.subprocess,
        "Popen",
        lambda *args, **kwargs: _Process(stdin),
    )
    result = SubprocessGhRunner().run(
        ("/opt/bin/gh", "issue", "create"), input_text="abcdef"
    )
    assert result.stdin_bytes_expected == 6
    assert result.stdin_bytes_written == expected_written
    assert result.stdin_delivery_completed is completed
    assert error_type in result.stdin_error


@pytest.mark.parametrize(
    "process, reason, code",
    (
        (IssueCreateProcessResult(1, "", "network"), IssueCreateReasonCode.COMMAND_FAILED, 76),
        (IssueCreateProcessResult(None, timed_out=True), IssueCreateReasonCode.COMMAND_TIMEOUT, 77),
        (IssueCreateProcessResult(None, interrupted=True), IssueCreateReasonCode.COMMAND_INTERRUPTED, 77),
        (IssueCreateProcessResult(0, "created\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "https://github.com/Blummer92/agent-os/issues/1\nhttps://github.com/Blummer92/agent-os/issues/1\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "https://github.com/Blummer92/agent-os/issues/1?x=1\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "http://github.com/Blummer92/agent-os/issues/1\n", ""), IssueCreateReasonCode.MALFORMED_SUCCESS_OUTPUT, 78),
        (IssueCreateProcessResult(0, "https://github.com/other/repo/issues/1\n", ""), IssueCreateReasonCode.WRONG_TARGET_SUCCESS_OUTPUT, 79),
    ),
)
def test_uncertain_results(process, reason, code):
    result = execute_issue_creation(request(), Runner(create=process), Confirm())
    assert result.reason_code == reason and result.exit_code == code
    assert IssueCreateReasonCode.MUTATION_UNCERTAIN in result.reason_codes
    assert result.mutation_state == MutationState.UNCERTAIN
    assert not result.mutation_performed and not result.retry_allowed


@pytest.mark.parametrize(
    "overrides, reason",
    (
        ({("gh", "--version"): IssueCreateProcessResult(1, "", "missing")}, IssueCreateReasonCode.GH_UNAVAILABLE),
        ({("gh", "issue", "create", "--help"): IssueCreateProcessResult(0, "--repository --title --body-file --label\n", "")}, IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED),
        ({("gh", "issue", "view", "--help"): IssueCreateProcessResult(0, "--repo\n", "")}, IssueCreateReasonCode.GH_CAPABILITY_UNSUPPORTED),
        ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(4, "", "no auth")}, IssueCreateReasonCode.AUTHENTICATION_UNAVAILABLE),
        ({("gh", "auth", "status", "--active", "--hostname", "github.com"): IssueCreateProcessResult(0, "Logged in to github.com account one\nLogged in to github.com account two\n", "")}, IssueCreateReasonCode.ACCOUNT_AMBIGUOUS_OR_MISMATCHED),
    ),
)
def test_capability_auth(overrides, reason):
    runner = Runner(overrides=overrides)
    plan, failure = plan_issue_creation(request(), runner)
    assert plan is None and failure.reason_code == reason
    assert creates(runner) == []


@pytest.mark.parametrize(
    "payload",
    (
        {"nameWithOwner": "other/repo", "url": "https://github.com/other/repo", "hasIssuesEnabled": True, "isArchived": False},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": True, "isArchived": True},
        {"nameWithOwner": "Blummer92/agent-os", "url": "https://github.com/Blummer92/agent-os", "hasIssuesEnabled": False, "isArchived": False},
    ),
)
def test_repository_metadata(payload):
    command = (
        "gh", "repo", "view", "github.com/Blummer92/agent-os", "--json",
        "nameWithOwner,url,hasIssuesEnabled,isArchived",
    )
    plan, failure = plan_issue_creation(
        request(), Runner(overrides={command: IssueCreateProcessResult(0, json.dumps(payload), "")})
    )
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.TARGET_MISMATCHED


@pytest.mark.parametrize("raw_payload", ("[]", "\"scalar\"", "null"))
def test_repository_metadata_non_object_fails_closed(raw_payload):
    command = (
        "gh", "repo", "view", "github.com/Blummer92/agent-os", "--json",
        "nameWithOwner,url,hasIssuesEnabled,isArchived",
    )
    runner = Runner(overrides={command: IssueCreateProcessResult(0, raw_payload, "")})
    plan, failure = plan_issue_creation(request(), runner)
    assert plan is None
    assert failure.reason_code == IssueCreateReasonCode.TARGET_INVALID_OR_AMBIGUOUS
    assert creates(runner) == []


def test_redaction_unicode_cli_static(monkeypatch, capsys, tmp_path):
    secret = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
    base = validation()
    protected = replace(
        base, draft=replace(
            base.draft, title="private title", body="private body",
            proposed_labels=("private-label",),
        )
    )
    diagnostic = (
        f"Authorization: Basic abc\nBearer abc.def\ntoken={secret}\n"
        "password=hunter2\nhttps://u:p@example.com/\n"
        "private title\nprivate-label\nprivate body"
    )
    result = execute_issue_creation(
        request(result=protected),
        Runner(create=IssueCreateProcessResult(1, secret, diagnostic)), Confirm()
    )
    combined = render_issue_create_result(result) + json.dumps(
        issue_create_result_to_dict(result)
    )
    for value in (
        secret, "abc.def", "hunter2", "u:p@", "private title",
        "private-label", "private body",
    ):
        assert value not in combined
    assert "TRUNCATED" in sanitize_diagnostic_text(
        "public\n" + "x" * 5000, limit=100
    )
    unicode_result = replace(
        base, draft=replace(base.draft, body=base.draft.body + "\nRésumé — 東京")
    )
    plan, error = plan_issue_creation(request(result=unicode_result), Runner())
    assert error is None and "東京" in plan.body
    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")
    assert issue_create_cli.main(
        ["--input", str(malformed), "--target", "Blummer92/agent-os"]
    ) == 64
    capsys.readouterr()
    cli_runner = Runner()
    monkeypatch.setattr(issue_create_cli, "SubprocessGhRunner", lambda: cli_runner)
    assert issue_create_cli.main([
        "--input", str(FIXTURE), "--target", "Blummer92/agent-os",
        "--issue-form", str(FORM), "--label-map", str(MAP), "--format", "json",
    ]) == IssueCreateExitCode.CONFIRMATION
    assert creates(cli_runner) == []
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["account_identity"] == "tester"
    assert cli_payload["gh_version"] == "gh version 2.80.0"
    assert cli_payload["gh_executable_identity"].startswith("gh sha256=")
    assert cli_payload["required_capability_decision"].startswith("supported:")
    assert cli_payload["optional_metadata_decision"] == "none-requested"

    private_runner = Runner(executable="/secret/private/tools/gh")
    private_plan, private_error = plan_issue_creation(
        request(result=protected), private_runner
    )
    assert private_error is None
    monkeypatch.setattr("builtins.input", lambda _: "cancel")
    confirmation = issue_create_cli._PromptConfirmation().confirm(private_plan)
    assert confirmation is not None and not confirmation.confirmed
    prompt_output = capsys.readouterr().err
    for expected in (
        "Authenticated account: tester",
        "GitHub CLI version: gh version 2.80.0",
        "GitHub CLI executable: gh sha256=",
        "Required capability: supported:",
        "Optional metadata: none-requested",
    ):
        assert expected in prompt_output
    for sensitive in (
        "/secret/private/tools/gh",
        "private title",
        "private body",
        "private-label",
    ):
        assert sensitive not in prompt_output
    source = inspect.getsource(SubprocessGhRunner.run)
    module = Path(inspect.getsourcefile(SubprocessGhRunner)).read_text(encoding="utf-8")
    assert "subprocess.Popen" in source and "shell=False" in source
    for forbidden in (
        "shell=True", "os.system", "gh auth token", "--show-token", "gh auth refresh",
    ):
        assert forbidden not in module
    assert 'env.pop("GH_REPO"' in module and 'env.pop("GH_HOST"' in module
