from __future__ import annotations

import pytest

from workflow_scheduler.governance.dev_validation import (
    REPOSITORY,
    build_dev_validation_request,
    validation_argv,
)
from workflow_scheduler.governance.dev_validation_profiles import (
    PROFILE_CATALOG,
    RunnerKind,
    canonical_profile_id,
    get_profile,
    profile_argv,
    project_selector_requirements,
)

SHA = "a" * 40
BRANCH = "agent/1566-reusable-dev-validation-profiles"


def request(profile_id: str):
    return build_dev_validation_request(
        repository=REPOSITORY,
        issue_number=1566,
        branch=BRANCH,
        source_sha=SHA,
        validation_id=profile_id,
    )


def test_known_profile_resolves_to_finite_runner_and_fixed_targets() -> None:
    profile = get_profile("pr-remediation")
    assert profile.runner_kind is RunnerKind.PYTEST_TARGETS
    assert profile.fixed_targets == ("tests/agent_os_pr_remediation",)
    assert profile_argv("pr-remediation") == (
        "python", "-m", "pytest", "tests/agent_os_pr_remediation"
    )


def test_unknown_or_malformed_profile_fails_closed() -> None:
    for profile_id in ("unknown", "../escape", "x;echo", "", "UPPER"):
        with pytest.raises(ValueError):
            request(profile_id)


def test_caller_has_no_target_module_script_env_or_cwd_surface() -> None:
    built = request("pr-remediation")
    assert set(built.to_dict()) == {
        "repository", "issue_number", "branch", "source_sha", "validation_id",
        "profile_id", "request_id", "execution_authorized", "scheduler_invoked",
        "publication_invoked", "merge_authorized",
    }
    assert validation_argv(built) == profile_argv("pr-remediation")


def test_protected_or_malformed_branch_is_rejected() -> None:
    for branch in ("main", "agent/main", "agent/../main", "agent/x//y"):
        with pytest.raises(ValueError):
            build_dev_validation_request(
                repository=REPOSITORY,
                issue_number=1566,
                branch=branch,
                source_sha=SHA,
                validation_id="pr-remediation",
            )


def test_exact_sha_is_required() -> None:
    for sha in ("A" * 40, "a" * 39, "main"):
        with pytest.raises(ValueError):
            build_dev_validation_request(
                repository=REPOSITORY,
                issue_number=1566,
                branch=BRANCH,
                source_sha=sha,
                validation_id="pr-remediation",
            )


def test_request_identity_is_deterministic_and_bound_to_canonical_profile() -> None:
    first = request("remote-validation")
    alias = request("remote-validation-suite")
    assert first.profile_id == alias.profile_id == "remote-validation"
    assert first.request_id == alias.request_id
    assert validation_argv(first) == validation_argv(alias)


def test_existing_four_identities_have_stable_compatibility_aliases() -> None:
    assert canonical_profile_id("remote-validation-suite") == "remote-validation"
    assert canonical_profile_id("instructional-materials-current-curriculum-suite") == "instructional-materials-current-curriculum"
    assert canonical_profile_id("ppux-picture-perfect-ts-vitest") == "picture-perfect"
    assert canonical_profile_id("semantic-ownership-advisory") == "semantic-ownership-advisory"


def test_initial_reusable_package_profiles_exist() -> None:
    assert {"pr-remediation", "workflow-scheduler", "issue-acceptance"}.issubset(PROFILE_CATALOG)


def test_selector_projection_is_deterministic_and_deduplicated() -> None:
    left = project_selector_requirements([
        "workflow-scheduler-concrete-runtime-adapters",
        "issue-acceptance",
        "workflow-scheduler",
    ])
    right = project_selector_requirements([
        "workflow-scheduler",
        "workflow-scheduler-concrete-runtime-adapters",
        "issue-acceptance",
        "workflow-scheduler",
    ])
    assert left == right == ("issue-acceptance", "workflow-scheduler")


def test_selector_projection_fails_closed_for_unmapped_requirement() -> None:
    with pytest.raises(ValueError, match="profile-unavailable"):
        project_selector_requirements(["navigation-registry"])


def test_selector_projection_does_not_accept_command_text() -> None:
    with pytest.raises(ValueError, match="profile-unavailable"):
        project_selector_requirements(["python -m pytest tests/agent_os_issue_acceptance"])


def test_profile_requests_are_non_authorizing() -> None:
    payload = request("workflow-scheduler").to_dict()
    assert payload["execution_authorized"] is False
    assert payload["scheduler_invoked"] is False
    assert payload["publication_invoked"] is False
    assert payload["merge_authorized"] is False
