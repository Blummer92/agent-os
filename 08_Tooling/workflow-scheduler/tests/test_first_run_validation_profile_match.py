"""#1972 regressions for exact fixed validation-profile matching.

The canonical #1985 PR-less plan may execute only when it maps to exactly one
existing fixed validation profile the current GCE dev-validation runner already
owns. Anything else fails closed instead of becoming a new command surface.
"""
from __future__ import annotations


import pytest

from scripts.agent_os_remote_validation import (
    PrePrValidationPlan,
    PrePrValidationSubject,
    compute_command_set_digest,
)
from workflow_scheduler.governance.dev_validation import VALIDATION_REGISTRY
from workflow_scheduler.governance.dev_validation_profiles import profile_argv
from workflow_scheduler.governance.first_run_validation_observation import (
    FIRST_RUN_SUPPORTED_VALIDATION_IDS,
    FirstRunValidationObservationError,
    resolve_fixed_first_run_validation_id,
)

SELECTOR_VERSION = "1.0.0"
BASE_SHA = "b" * 40
HEAD_SHA = "a" * 40
CONTRACT = "1" * 64
PROJECTION_ID = "projection:" + "2" * 64
APPROVAL_ID = "approval:" + "4" * 64


def _subject(commands: tuple[str, ...]) -> PrePrValidationSubject:
    return PrePrValidationSubject(
        repository="Blummer92/agent-os",
        issue_number=1972,
        invocation_id="pre-pr-1972",
        base_branch="main",
        base_sha=BASE_SHA,
        branch="agent/1972-first-run-host-composition",
        expected_source_sha=HEAD_SHA,
        tested_sha=HEAD_SHA,
        allowed_files=("08_Tooling/workflow-scheduler/src",),
        forbidden_paths=(".github/workflows",),
        required_command_identities=commands,
        approval_id=APPROVAL_ID,
        approval_revision=1,
        projection_id=PROJECTION_ID,
        implementation_contract_fingerprint=CONTRACT,
        expected_changed_paths=("08_Tooling/workflow-scheduler/src",),
        candidate_bound=True,
    )


def _plan(*commands: str) -> PrePrValidationPlan:
    return PrePrValidationPlan(
        subject=_subject(tuple(commands)),
        selector_version=SELECTOR_VERSION,
        commands=tuple(commands),
        command_set_digest=compute_command_set_digest(SELECTOR_VERSION, tuple(commands)),
        reason_codes=("profile.focused-package",),
    )


def test_supported_ids_are_exactly_the_existing_fixed_runner_registry() -> None:
    assert FIRST_RUN_SUPPORTED_VALIDATION_IDS == tuple(sorted(VALIDATION_REGISTRY))


@pytest.mark.parametrize("validation_id", sorted(VALIDATION_REGISTRY))
def test_each_existing_fixed_profile_resolves_to_itself(validation_id: str) -> None:
    plan = _plan(" ".join(profile_argv(validation_id)))

    assert resolve_fixed_first_run_validation_id(plan) == validation_id


@pytest.mark.parametrize(
    "commands",
    [
        ("python -m pytest tests/agent_os_remote_validation", "python -m pytest tests"),
        ("python -m pytest tests/agent_os_remote_validation --maxfail=1",),
        ("python -m pytest tests/agent_os_issue_acceptance",),
        ("bash -c curl-evil",),
        ("python -m pytest tests/agent_os_remote_validation/extra",),
    ],
)
def test_unsupported_validation_plan_fails_closed(commands: tuple[str, ...]) -> None:
    with pytest.raises(FirstRunValidationObservationError):
        resolve_fixed_first_run_validation_id(_plan(*commands))


def test_non_plan_input_fails_closed() -> None:
    for value in (None, {}, "remote-validation-suite", 1972):
        with pytest.raises(FirstRunValidationObservationError, match="validation-plan-malformed"):
            resolve_fixed_first_run_validation_id(value)


def test_profile_catalog_entries_outside_the_fixed_runner_are_rejected() -> None:
    # 'issue-acceptance' and 'pr-remediation' exist in the profile catalog but the
    # existing fixed GCE dev-validation runner does not execute them. First-run
    # must not widen that runner's surface.
    for profile_id in ("issue-acceptance", "pr-remediation", "visual-asset-sheets-smoke"):
        plan = _plan(" ".join(profile_argv(profile_id)))
        with pytest.raises(
            FirstRunValidationObservationError, match="validation-profile-unsupported"
        ):
            resolve_fixed_first_run_validation_id(plan)


def test_resolution_is_bound_to_the_plan_command_not_a_caller_label() -> None:
    remote = _plan(" ".join(profile_argv("remote-validation-suite")))
    materials = _plan(
        " ".join(profile_argv("instructional-materials-current-curriculum-suite"))
    )

    assert resolve_fixed_first_run_validation_id(remote) == "remote-validation-suite"
    assert (
        resolve_fixed_first_run_validation_id(materials)
        == "instructional-materials-current-curriculum-suite"
    )
    # The plan's own profile label is a fixed canonical constant; it carries no
    # caller-selectable runner identity, so resolution can only follow the command.
    assert remote.profile == materials.profile
