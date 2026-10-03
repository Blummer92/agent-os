from scripts.agent_os_remote_validation.main_health_recovery_authorization import (
    RECOVERY_AUTHORIZATION_SCHEMA,
    evaluate_recovery_authorization,
    recovery_issue_reference,
)

REPOSITORY = "Blummer92/agent-os"
OWNER = "Blummer92"
MAIN = "a" * 40
HEAD = "b" * 40
DETAILS = "https://github.com/Blummer92/agent-os/actions/runs/123/job/456"
PATHS = ("08_Tooling/instructional-materials-coach/tests/conftest.py",)


def _body(**overrides):
    payload = {
        "schema": RECOVERY_AUTHORIZATION_SCHEMA,
        "repository": REPOSITORY,
        "issue_number": 3270,
        "main_sha": MAIN,
        "pull_request": 3267,
        "head_sha": HEAD,
        "main_check_details_url": DETAILS,
        "repair_paths": list(PATHS),
        "authorized_by": OWNER,
    }
    payload.update(overrides)
    import json
    return "<!-- agent-os-main-health-recovery " + json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ) + " -->"


def _evaluate(body=None, **overrides):
    values = {
        "repository": REPOSITORY,
        "repository_owner": OWNER,
        "issue_number": 3270,
        "issue_author": OWNER,
        "current_main_sha": MAIN,
        "pull_request": 3267,
        "current_head_sha": HEAD,
        "main_check_details_url": DETAILS,
        "changed_files": PATHS,
    }
    values.update(overrides)
    return evaluate_recovery_authorization(_body() if body is None else body, **values)


def test_pr_body_requires_one_exact_recovery_issue_reference():
    assert recovery_issue_reference(
        "repair\n<!-- agent-os-main-health-recovery-issue:3270 -->"
    ) == 3270
    assert recovery_issue_reference("repair") is None
    assert recovery_issue_reference(
        "<!-- agent-os-main-health-recovery-issue:3270 -->"
        "<!-- agent-os-main-health-recovery-issue:3271 -->"
    ) is None


def test_exact_owner_authorization_admits_validation_recovery():
    result = _evaluate()
    assert result is not None
    assert result.issue_number == 3270
    assert result.main_sha == MAIN
    assert result.pull_request == 3267
    assert result.head_sha == HEAD
    assert result.repair_paths == PATHS


def test_new_incident_is_data_not_workflow_source_change():
    result = _evaluate(
        body=_body(
            issue_number=4000,
            pull_request=4001,
            head_sha="c" * 40,
            main_check_details_url="https://github.com/Blummer92/agent-os/actions/runs/999/job/888",
        ),
        issue_number=4000,
        pull_request=4001,
        current_head_sha="c" * 40,
        main_check_details_url="https://github.com/Blummer92/agent-os/actions/runs/999/job/888",
    )
    assert result is not None
    assert result.issue_number == 4000


def test_authorization_fails_closed_on_every_identity_drift():
    cases = (
        {"current_main_sha": "c" * 40},
        {"pull_request": 3268},
        {"current_head_sha": "c" * 40},
        {"main_check_details_url": "https://github.com/Blummer92/agent-os/actions/runs/124/job/456"},
        {"issue_author": "someone-else"},
        {"repository": "other/repo"},
        {"changed_files": ("README.md",)},
    )
    for overrides in cases:
        assert _evaluate(**overrides) is None, overrides


def test_payload_cannot_expand_scope_or_use_foreign_check():
    assert _evaluate(body=_body(repair_paths=["README.md"])) is None
    assert _evaluate(
        body=_body(
            main_check_details_url="https://github.com/other/repo/actions/runs/123/job/456"
        ),
        main_check_details_url="https://github.com/other/repo/actions/runs/123/job/456",
    ) is None


def test_malformed_or_duplicate_authorization_fails_closed():
    assert _evaluate(body="<!-- agent-os-main-health-recovery nope -->") is None
    assert _evaluate(body=_body() + _body()) is None
    assert _evaluate(body=_body(extra="not-allowed")) is None
