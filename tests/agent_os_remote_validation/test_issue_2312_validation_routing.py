"""#2312 regressions for canonical validation routing of the first-run surface.

PR #2312 produced a green Agent OS Validation Gate that executed zero tests. The
selector was correct: it fell back to ``aggregate`` with
``profile.aggregate-unmapped-executable`` because the changed
``08_Tooling/agent-os-execution-service/**`` and ``**/agent_os_remote_validation/**``
paths had no focused rule. On a Draft pull-request event the aggregate lane is
deliberately deferred, so "run everything" became "run nothing".

These tests pin the repaired rule-map coverage and the rule-map -> CI-executor
contract that made the gap invisible. They add no selector, profile, or executor.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
)

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rule_map()

BASE_SHA = "ceb6e9801999ee44faaffbf754bb3ba1a3abb4e1"
HEAD_SHA = "93fa074dd39d46d38538b3b2a9d82ad3797631ec"

EXECUTION_SERVICE_COMMAND = "python -m pytest 08_Tooling/agent-os-execution-service/tests"
WORKFLOW_SCHEDULER_COMMAND = "python -m pytest 08_Tooling/workflow-scheduler/tests"
REMOTE_VALIDATION_COMMAND = "python -m pytest tests/agent_os_remote_validation"

# The exact changed-path set of PR #2312 at head 93fa074.
PR_2312_PATHS = (
    "08_Tooling/agent-os-execution-service/docs/FIRST_RUN_VALIDATION_START.md",
    "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/candidate_environment_provenance.py",
    "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/first_run_validation_entrypoint.py",
    "08_Tooling/agent-os-execution-service/tests/test_candidate_environment_provenance.py",
    "08_Tooling/agent-os-execution-service/tests/test_first_run_validation_entrypoint.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/first_run_dev_validation_gce.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/first_run_validation_gce.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/first_run_validation_observation.py",
    "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/gce_gcloud_adapter.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_dev_validation_gce.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_validation_gce.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_validation_observation.py",
    "08_Tooling/workflow-scheduler/tests/test_first_run_validation_profile_match.py",
    "scripts/agent_os_remote_validation/evidence_bundle.py",
    "tests/agent_os_remote_validation/test_pre_pr_evidence_bundle.py",
)


def _plan(*paths: str):
    return select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=2312,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            changed_files=tuple(paths),
        ),
        RULES,
    )


def _ci_executor():
    """Load the bounded CI executor exactly as the workflow step loads it."""
    spec = importlib.util.spec_from_file_location(
        "_issue_2312_ci_validation", ROOT / "scripts/agent_os_ci_validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


# --- 1. the exact #2312 surface no longer yields a zero-command false green ---


def test_pr_2312_changed_set_selects_attributable_focused_commands() -> None:
    plan = _plan(*PR_2312_PATHS)

    assert plan.profile == "focused"
    assert plan.reason_codes == ("profile.focused-union",)
    assert set(plan.commands) == {
        EXECUTION_SERVICE_COMMAND,
        WORKFLOW_SCHEDULER_COMMAND,
        REMOTE_VALIDATION_COMMAND,
    }
    # The regression being pinned: never again the deferred-aggregate false green.
    assert plan.profile != "aggregate"
    assert "profile.aggregate-unmapped-executable" not in plan.reason_codes
    assert plan.commands, "a focused plan must carry at least one attributable command"


@pytest.mark.parametrize(
    "path, expected_command",
    [
        (
            "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/first_run_validation_entrypoint.py",
            EXECUTION_SERVICE_COMMAND,
        ),
        (
            "08_Tooling/agent-os-execution-service/tests/test_first_run_validation_entrypoint.py",
            EXECUTION_SERVICE_COMMAND,
        ),
        (
            "08_Tooling/agent-os-execution-service/docs/FIRST_RUN_VALIDATION_START.md",
            EXECUTION_SERVICE_COMMAND,
        ),
        ("scripts/agent_os_remote_validation/evidence_bundle.py", REMOTE_VALIDATION_COMMAND),
        (
            "tests/agent_os_remote_validation/test_pre_pr_evidence_bundle.py",
            REMOTE_VALIDATION_COMMAND,
        ),
    ],
)
def test_each_previously_unmapped_path_now_maps_to_one_focused_command(
    path: str, expected_command: str
) -> None:
    plan = _plan(path)

    assert plan.profile == "focused"
    assert plan.commands == (expected_command,)


# --- 2. the obligation is deterministic ---


def test_focused_selection_is_deterministic_and_order_independent() -> None:
    forward = _plan(*PR_2312_PATHS)
    reverse = _plan(*reversed(PR_2312_PATHS))

    assert forward.profile == reverse.profile
    assert forward.commands == reverse.commands
    assert forward.reason_codes == reverse.reason_codes
    assert forward.command_set_digest == reverse.command_set_digest
    # Repeated planning of the same input is byte-stable.
    assert _plan(*PR_2312_PATHS).command_set_digest == forward.command_set_digest


def test_single_rule_match_reports_focused_package_not_union() -> None:
    plan = _plan(
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/authorization.py"
    )

    assert plan.reason_codes == ("profile.focused-package",)


# --- 3. the rule-map -> CI-executor contract that hid this gap ---


def test_every_focused_rule_command_is_resolvable_by_the_bounded_ci_executor() -> None:
    """A rule-map command the executor cannot resolve is a latent broken lane."""
    executor = _ci_executor()
    unresolvable = []
    for rule in RULES["focused_rules"]:
        for command in rule["commands"]:
            try:
                executor._resolve_command(command)
            except ValueError:
                unresolvable.append((rule["name"], command))
    assert not unresolvable, f"rule-map commands missing from the CI executor: {unresolvable}"


def test_aggregate_command_is_resolvable_by_the_bounded_ci_executor() -> None:
    executor = _ci_executor()
    argv, _ = executor._resolve_command(RULES["aggregate_command"])
    assert argv == ("python", "-m", "pytest")


def test_every_focused_rule_command_target_exists_in_the_repository() -> None:
    for rule in RULES["focused_rules"]:
        for command in rule["commands"]:
            if not command.startswith("python -m pytest "):
                continue
            target = command.removeprefix("python -m pytest ").strip()
            assert (ROOT / target).exists(), (
                f"focused rule {rule['name']!r} targets a missing path: {target}"
            )


# --- 4. unrelated existing classifications are unchanged ---


@pytest.mark.parametrize(
    "path, expected_profile, expected_commands",
    [
        (
            "scripts/agent_os_issue_acceptance/models.py",
            "focused",
            ("python -m pytest tests/agent_os_issue_acceptance",),
        ),
        (
            "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/dev_validation.py",
            "focused",
            (WORKFLOW_SCHEDULER_COMMAND,),
        ),
        (
            "08_Tooling/notion-navigation-client/src/x.py",
            "focused",
            ("python -m pytest 08_Tooling/notion-navigation-client/tests",),
        ),
        (".github/workflows/agent-os-validation.yml", "aggregate", ("python -m pytest",)),
        ("requirements-dev.txt", "aggregate", ("python -m pytest",)),
        ("pytest.ini", "aggregate", ("python -m pytest",)),
    ],
)
def test_unrelated_path_classifications_are_unchanged(
    path: str, expected_profile: str, expected_commands: tuple[str, ...]
) -> None:
    plan = _plan(path)

    assert plan.profile == expected_profile
    assert plan.commands == expected_commands


def test_new_prefixes_never_shadow_aggregate_configuration_triggers() -> None:
    """Config/workflow aggregate triggers still win over the new focused rules."""
    plan = _plan(
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/authorization.py",
        "requirements-dev.txt",
    )

    assert plan.profile == "aggregate"
    assert plan.reason_codes == ("profile.aggregate-configuration",)


# --- 5. documentation-only behaviour is unchanged ---


def test_governance_documentation_only_change_remains_static() -> None:
    plan = _plan("00_Governance/write-authorization-policy.md")

    assert plan.profile == "static"
    assert plan.commands == ()
    assert plan.reason_codes == ("profile.documentation-static",)


def test_execution_service_documentation_is_attributable_not_static() -> None:
    """08_Tooling docs sit outside documentation_prefixes, so they carry tests."""
    plan = _plan("08_Tooling/agent-os-execution-service/docs/FIRST_RUN_VALIDATION_START.md")

    assert plan.profile == "focused"
    assert plan.commands == (EXECUTION_SERVICE_COMMAND,)


# --- 6. unknown / malformed paths still fail safe ---


def test_unmapped_executable_still_falls_back_to_aggregate() -> None:
    plan = _plan("scripts/some_brand_new_unmapped_package/module.py")

    assert plan.profile == "aggregate"
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_unmapped_non_executable_still_requires_manual_review() -> None:
    plan = _plan("some/unmapped/asset.bin")

    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.reason_codes == ("rule.ambiguous",)


def test_partially_mapped_change_set_does_not_silently_drop_the_unmapped_path() -> None:
    """One unmapped executable must still force the conservative aggregate fallback."""
    plan = _plan(
        "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/authorization.py",
        "scripts/some_brand_new_unmapped_package/module.py",
    )

    assert plan.profile == "aggregate"
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_empty_changed_file_set_fails_closed() -> None:
    plan = _plan()

    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("metadata.empty-changed-files",)
