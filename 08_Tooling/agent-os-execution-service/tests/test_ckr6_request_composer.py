"""CKR6 pre-publication request composition: no authorization or GitHub I/O."""
from __future__ import annotations

import io
import json
import sys

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service.ckr6_request_composer import (
    ComposeBlocked,
    compose_request_comment,
    main,
)

REPO = "Blummer92/agent-os"
HEAD = "a7bcc953ca18f6c4256beee3ad287ed99f6621c7"
PR = 4092
PREFIX = f"PR #{PR} exact head {HEAD}: "


def payload(**updates):
    obj = {
        "operation": "issue-start", "repository": REPO, "issue_number": PR,
        "task_reference": PREFIX + "shadow-only evidence verification",
        "capability_keywords": ["trusted evidence bridge", "JUnit execution"],
        "canonical_rule_refs": [f"https://github.com/{REPO}/issues/3690"],
    }
    obj.update(updates)
    return obj


def test_valid_pr_comment_exact_roundtrip_without_authority():
    request = payload()
    command = compose_request_comment(request, pr_number=PR, head_sha=HEAD)
    assert command.startswith(bridge.COMMAND_PREFIX)
    assert json.loads(command[len(bridge.COMMAND_PREFIX):]) == request
    assert bridge.parse_envelope(
        json.loads(command[len(bridge.COMMAND_PREFIX):])
    ).issue_number == PR
    assert "mutation_admissible" not in command
    assert "merge_authorized" not in command


@pytest.mark.parametrize("size,admitted", [
    (511, True), (512, True), (513, False), (523, False),
])
def test_task_reference_canonical_field_bound(size, admitted):
    task = PREFIX + "x" * (size - len(PREFIX))
    if admitted:
        assert compose_request_comment(
            payload(task_reference=task), pr_number=PR, head_sha=HEAD,
        )
    else:
        with pytest.raises(ComposeBlocked, match="^envelope-field-oversized$"):
            compose_request_comment(
                payload(task_reference=task), pr_number=PR, head_sha=HEAD,
            )


@pytest.mark.parametrize("override,reason", [
    ({"issue_number": 4093}, "pr-target-mismatch"),
    ({"task_reference": "PR #4093 exact head " + HEAD}, "pr-reference-unbound-or-ambiguous"),
    ({"task_reference": PREFIX + "also PR #4093"}, "pr-reference-unbound-or-ambiguous"),
    ({"task_reference": "PR #4092 missing head"}, "pr-head-unbound-or-ambiguous"),
    ({"task_reference": PREFIX + HEAD}, "pr-head-unbound-or-ambiguous"),
    ({"task_reference": "PR #4092 exact head " + "f" * 40}, "pr-head-unbound-or-ambiguous"),
    ({"operation": "lesson-refinement", "revision": {}}, "envelope-invalid"),
    ({"unexpected_authority": True}, "envelope-invalid"),
    ({"capability_keywords": ["x" * 513]}, "envelope-field-oversized"),
])
def test_invalid_request_blocks_without_transforming_inputs(override, reason):
    req = payload(**override)
    snapshot = json.dumps(req, sort_keys=True)
    with pytest.raises(ComposeBlocked, match="^" + reason + "$"):
        compose_request_comment(req, pr_number=PR, head_sha=HEAD)
    assert json.dumps(req, sort_keys=True) == snapshot


def test_strict_pairing_and_head_format():
    for kwargs, reason in [
        ({"pr_number": PR}, "pr-binding-incomplete"),
        ({"head_sha": HEAD}, "pr-binding-incomplete"),
        ({"pr_number": True, "head_sha": HEAD}, "pr-number-invalid"),
        ({"pr_number": PR, "head_sha": "a" * 39}, "pr-head-invalid"),
    ]:
        with pytest.raises(ComposeBlocked, match="^" + reason + "$"):
            compose_request_comment(payload(), **kwargs)


def test_unbound_issue_comment_remains_allowed_without_claiming_pr():
    req = payload(issue_number=3690, task_reference="Issue #3690 bounded CKR6 diagnostics")
    assert compose_request_comment(req).startswith(bridge.COMMAND_PREFIX)


def test_comment_byte_budget_enforced_after_canonical_encoding():
    req = payload(
        capability_keywords=["x" * 500] * 20,
        target_path_hints=["y" * 500] * 20,
    )
    with pytest.raises(ComposeBlocked, match="^comment-oversized$"):
        compose_request_comment(req, pr_number=PR, head_sha=HEAD)


def test_cli_stdin_success_emits_one_command_and_no_other_lines(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload())))
    result = main(["--pr-number", str(PR), "--head-sha", HEAD])
    out = capsys.readouterr()
    assert result == 0 and out.err == ""
    assert out.out == compose_request_comment(
        payload(), pr_number=PR, head_sha=HEAD,
    ) + "\n"


@pytest.mark.parametrize("raw,reason", [
    ("{not json", "invalid-json"),
    ('{"operation":"issue-start","operation":"failed-repair"}', "duplicate-json-field"),
    ("[]", "envelope-invalid"),
    ('{"secret":"' + "S" * 70000 + '"}', "input-oversized"),
])
def test_cli_rejects_malformed_input_with_no_partial_output(
    monkeypatch, capsys, raw, reason,
):
    monkeypatch.setattr(sys, "stdin", io.StringIO(raw))
    assert main(["--pr-number", str(PR), "--head-sha", HEAD]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.strip() == "CKR6 request blocked: " + reason
    assert "S" * 100 not in output.err


def test_failed_repair_preserves_attempt_identity_without_claiming_grant():
    req = payload(
        operation="failed-repair", attempt_id="attempt-7",
        failed_hypothesis="retrieval was expected to succeed",
        result_summary="CI gate rejected head", repair_context="ci-diagnosis",
    )
    command = compose_request_comment(req, pr_number=PR, head_sha=HEAD)
    parsed = bridge.parse_envelope(
        json.loads(command[len(bridge.COMMAND_PREFIX):])
    )
    assert parsed.attempt_id == "attempt-7"
    assert parsed.operation == "failed-repair"


def test_nonboundary_learning_operation_is_not_a_mutation_request():
    request = {
        "operation": "lesson-refinement", "repository": REPO,
        "issue_number": PR, "task_reference": PREFIX + "lesson correction",
        "revision": {},
    }
    with pytest.raises(ComposeBlocked, match="^operation-not-boundary$"):
        compose_request_comment(request, pr_number=PR, head_sha=HEAD)
