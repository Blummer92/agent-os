"""#1972 regressions for the trusted-host first-run validation composition.

These prove the composition order, the identity bindings that hold it together,
and that no caller-controlled argv, approval, authorization, runner identity,
Scheduler, publication, or retry path exists.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import agent_os_execution_service.first_run_validation_entrypoint as live
from agent_os_execution_service.first_run_validation_entrypoint import (
    FirstRunValidationCompositionError,
    FirstRunValidationIdentity,
    compose_first_run_validation,
)
from agent_os_execution_service.validation_lifecycle_evidence import (
    VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
)

SHA = "b" * 40
REPOSITORY = "Blummer92/agent-os"
ISSUE = 1972
SOURCE = Path(live.__file__).read_text(encoding="utf-8")


def test_identity_accepts_only_trusted_canonical_first_run_facts() -> None:
    identity = FirstRunValidationIdentity(
        repository=REPOSITORY, issue_number=ISSUE, candidate_sha=SHA
    )
    assert identity.candidate_sha == SHA

    for kwargs in (
        {"repository": "attacker/agent-os", "issue_number": ISSUE, "candidate_sha": SHA},
        {"repository": REPOSITORY, "issue_number": 0, "candidate_sha": SHA},
        {"repository": REPOSITORY, "issue_number": ISSUE, "candidate_sha": "B" * 40},
        {"repository": REPOSITORY, "issue_number": ISSUE, "candidate_sha": "b" * 39},
        {"repository": REPOSITORY, "issue_number": ISSUE, "candidate_sha": "; rm -rf /"},
    ):
        with pytest.raises(ValueError):
            FirstRunValidationIdentity(**kwargs)


def test_identity_carries_no_argv_approval_or_authority_fields() -> None:
    fields = set(FirstRunValidationIdentity.__dataclass_fields__)
    assert fields == {"repository", "issue_number", "candidate_sha"}

    result_fields = set(live.FirstRunValidationResult.__dataclass_fields__)
    for forbidden in ("argv", "command", "approval_decision", "authorizer", "runner_id"):
        assert forbidden not in result_fields


def test_result_envelope_is_pr_less_and_non_authorizing() -> None:
    result = live.FirstRunValidationResult(
        schema_version="1.0",
        repository=REPOSITORY,
        issue_number=ISSUE,
        candidate_sha=SHA,
        validation_id="remote-validation-suite",
        profile_id="remote-validation",
        dev_validation_request_id="dev-validation:" + "c" * 64,
        validation_plan_id="pre-pr-validation-plan:" + "d" * 64,
        validation_bundle_id="validation-evidence-bundle:" + "e" * 64,
        environment_provenance_id="pre-publication-evidence:" + "f" * 64,
        execution_packet_request_fingerprint="f" * 64,
        command_plan_id="validation-command-plan:" + "9" * 64,
        authorization_id="execution-authorization:" + "8" * 64,
        authorized_validation_request_id="authorized-validation-request:" + "7" * 64,
        source_capture_id="pre-publication-evidence:" + "6" * 64,
    )
    payload = result.to_dict()

    assert payload["pull_request"] is None
    for boundary in (
        "execution_authorized",
        "scheduler_invoked",
        "publication_invoked",
        "execution_lease_acquired",
        "resume_invoked",
        "retry_attempted",
        "merge_authorized",
        "github_writes_authorized",
    ):
        assert payload[boundary] is False


def test_composition_rejects_non_exact_inputs() -> None:
    identity = FirstRunValidationIdentity(
        repository=REPOSITORY, issue_number=ISSUE, candidate_sha=SHA
    )
    with pytest.raises(TypeError):
        compose_first_run_validation(
            {"candidate_sha": SHA},
            object(),
            run_fixed_validation=lambda request: {},
            run_authorized_validation=lambda payload: object(),
        )
    with pytest.raises(TypeError):
        compose_first_run_validation(
            identity,
            object(),
            run_fixed_validation=lambda request: {},
            run_authorized_validation=lambda payload: object(),
        )


def test_composition_calls_existing_owners_in_the_mandated_order() -> None:
    """The composition body must call each existing owner once, in chain order."""
    tree = ast.parse(SOURCE)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "compose_first_run_validation"
    )
    called = [
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    expected_order = [
        "prepare_fresh_pre_validation",
        "resolve_fixed_first_run_validation_id",
        "build_dev_validation_request",
        "run_fixed_validation",
        "observed_command_from_fixed_gce_evidence",
        "supplied_command_results_from_dev_validation",
        "build_pre_pr_validation_evidence_bundle",
        "build_candidate_environment_provenance",
        "prepare_execution_packet",
        "reacquire_execution_authorization",
        "build_first_run_authorized_validation_request",
        "run_authorized_validation",
    ]
    positions = [called.index(name) for name in expected_order]
    assert positions == sorted(positions), called
    for name in expected_order:
        assert called.count(name) == 1, f"{name} must be called exactly once"


def test_composition_defines_no_validation_command_or_runner_identity() -> None:
    for forbidden in (
        "subprocess",
        "shell=True",
        "shlex",
        "--command",
        "pip install",
        "gcloud",
        "os.system",
    ):
        assert forbidden not in SOURCE, forbidden


def test_composition_reaches_no_scheduler_publication_or_retry_owner() -> None:
    tree = ast.parse(SOURCE)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    for module in imported:
        assert "single_issue_pilot" not in module
        assert "handoff_publication" not in module
        assert "production_host_composition" not in module
        assert "governed_resume" not in module
        assert "lease" not in module

    for forbidden in (
        "run_single_issue_pilot",
        "publish_production_handoff",
        "acquire_lease",
        "run_gce_control_path",
    ):
        assert forbidden not in SOURCE, forbidden


def test_composition_contains_no_retry_loop() -> None:
    """Each existing owner is called exactly once; a retry needs a loop."""
    tree = ast.parse(SOURCE)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "compose_first_run_validation"
    )
    loops = [
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.While, ast.For, ast.AsyncFor))
    ]
    # The only iteration permitted is the bounded boundary-flag check over a
    # fixed literal tuple; nothing may iterate over a validation attempt.
    assert all(isinstance(node, ast.For) and isinstance(node.iter, ast.Tuple) for node in loops)
    assert not any(isinstance(node, ast.While) for node in loops)


def test_composition_can_only_build_a_pr_less_bundle() -> None:
    """No fabricated pull-request identity is reachable from the first-run lane."""
    assert "build_pre_pr_validation_evidence_bundle" in SOURCE
    # The PR-carrying builder is never imported, so a positive PR identity cannot
    # be constructed here even by mistake.
    assert "build_validation_evidence_bundle" not in SOURCE
    # And the composition still fails closed if the PR-less owner ever returned one.
    assert "bundle.pull_request is not None" in SOURCE
    assert "first-run-bundle-must-remain-pr-less" in SOURCE

    tree = ast.parse(SOURCE)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "build_pre_pr_validation_evidence_bundle" in imported_names
    assert "build_validation_evidence_bundle" not in imported_names


def test_seams_are_named_existing_owners_not_caller_commands() -> None:
    signature = inspect.signature(compose_first_run_validation)
    assert set(signature.parameters) == {
        "identity",
        "host_state",
        "run_fixed_validation",
        "run_authorized_validation",
    }
    for name in ("run_fixed_validation", "run_authorized_validation"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_host_state_carries_only_host_reacquired_truth() -> None:
    fields = set(live.FirstRunHostState.__dataclass_fields__)
    assert fields == {
        "provenance",
        "approval_decision",
        "candidate_inputs",
        "execution_candidate_packet",
        "candidate_runtime_inputs",
        "governed_projection",
        "repository_identity",
        "repository_evidence_type",
        "repository_state_evidence_id",
        "proposal_id",
        "repository_root",
        "lifecycle_policy",
        "authorization_transport",
        "evaluated_at",
        "projected_at",
    }
    for forbidden in ("argv", "command", "runner_id", "started_at", "completed_at"):
        assert forbidden not in fields


def test_identity_binding_rejects_drifted_host_state() -> None:
    """_bind_identity must reject any host state not bound to this candidate."""
    identity = FirstRunValidationIdentity(
        repository=REPOSITORY, issue_number=ISSUE, candidate_sha=SHA
    )

    class _Packet:
        phase = live.CandidatePacketPhase.EXECUTION_CANDIDATE
        candidate_sha = SHA
        issue_number = ISSUE

    class _Inputs:
        candidate_sha = SHA
        issue_number = ISSUE
        candidate_branch = "agent/1972-first-run-host-composition"

    class _Identity:
        owner = "Blummer92"
        repository = "agent-os"

    def _state(**overrides):
        base = {
            "repository_identity": _Identity(),
            "execution_candidate_packet": _Packet(),
            "candidate_inputs": _Inputs(),
            "candidate_runtime_inputs": _Inputs(),
        }
        base.update(overrides)
        return type("State", (), base)()

    live._bind_identity(identity, _state())

    class _WrongSha(_Inputs):
        candidate_sha = "a" * 40

    class _WrongIssue(_Inputs):
        issue_number = 1971

    class _WrongRepository:
        owner = "attacker"
        repository = "agent-os"

    class _WrongPhase(_Packet):
        phase = live.CandidatePacketPhase.APPROVAL_READY

    class _WrongBranch(_Inputs):
        candidate_branch = "agent/some-other-branch"

    for overrides, reason in (
        ({"candidate_inputs": _WrongSha()}, "candidate-sha-binding-mismatch"),
        ({"candidate_runtime_inputs": _WrongSha()}, "candidate-sha-binding-mismatch"),
        ({"candidate_inputs": _WrongIssue()}, "issue-binding-mismatch"),
        ({"repository_identity": _WrongRepository()}, "repository-binding-mismatch"),
        ({"execution_candidate_packet": _WrongPhase()}, "candidate-packet-phase-invalid"),
        ({"candidate_runtime_inputs": _WrongBranch()}, "candidate-branch-binding-mismatch"),
    ):
        with pytest.raises(FirstRunValidationCompositionError, match=reason):
            live._bind_identity(identity, _state(**overrides))


def _lifecycle_result(request_id: str, *, status=None, execution_authorized: bool = False):
    return live.ValidationLifecycleResult(
        schema_version=VALIDATION_LIFECYCLE_EVIDENCE_SCHEMA_VERSION,
        bundle_id="validation-lifecycle-bundle:" + "a" * 64,
        request_id=request_id,
        status=status or live.ValidationLifecycleTerminalStatus.SUCCEEDED,
        reason_codes=("lifecycle.succeeded",),
        execution_authorized=execution_authorized,
        side_effects_performed=False,
        evaluated_at="2026-09-12T14:00:00Z",
    )


@pytest.mark.parametrize(
    "capture, reason",
    [
        (object(), "first-run-capture-result-malformed"),
        ((None, "pre-publication-evidence:" + "6" * 64), "first-run-capture-result-malformed"),
        (("not-a-result", None), "first-run-capture-result-malformed"),
    ],
)
def test_malformed_terminal_capture_fails_closed(capture, reason) -> None:
    """The #1929/#1830 owner returns a (result, capture id) pair; anything else fails."""
    with pytest.raises(FirstRunValidationCompositionError, match=reason):
        live._consume_authorized_validation_capture(capture, expected_request_id="request-1972")


def test_terminal_capture_must_be_request_bound_succeeded_and_non_authorizing() -> None:
    capture_id = "pre-publication-evidence:" + "6" * 64

    assert (
        live._consume_authorized_validation_capture(
            (_lifecycle_result("request-1972"), capture_id),
            expected_request_id="request-1972",
        )
        == capture_id
    )

    with pytest.raises(
        FirstRunValidationCompositionError, match="capture-request-binding-mismatch"
    ):
        live._consume_authorized_validation_capture(
            (_lifecycle_result("other-request"), capture_id),
            expected_request_id="request-1972",
        )

    with pytest.raises(FirstRunValidationCompositionError, match="not-succeeded:blocked"):
        live._consume_authorized_validation_capture(
            (
                _lifecycle_result(
                    "request-1972", status=live.ValidationLifecycleTerminalStatus.BLOCKED
                ),
                None,
            ),
            expected_request_id="request-1972",
        )

    with pytest.raises(FirstRunValidationCompositionError, match="capture-crossed-boundary"):
        live._consume_authorized_validation_capture(
            (_lifecycle_result("request-1972", execution_authorized=True), capture_id),
            expected_request_id="request-1972",
        )

    with pytest.raises(
        FirstRunValidationCompositionError, match="source-capture-identity-missing"
    ):
        live._consume_authorized_validation_capture(
            (_lifecycle_result("request-1972"), None),
            expected_request_id="request-1972",
        )


def test_host_main_fails_closed_without_separately_authorized_activation() -> None:
    with pytest.raises(
        FirstRunValidationCompositionError, match="first-run-host-state-activation-required"
    ):
        live.main(
            ["--repository", REPOSITORY, "--issue-number", str(ISSUE), "--candidate-sha", SHA]
        )


def test_host_main_accepts_only_the_fixed_selector_flags() -> None:
    for argv in (
        ["--repository", REPOSITORY, "--issue-number", str(ISSUE)],
        ["--candidate-sha", SHA],
        ["--repository", REPOSITORY, "--issue-number", str(ISSUE), "--candidate-sha", SHA, "--command", "x"],
    ):
        with pytest.raises(SystemExit):
            live.main(argv)
