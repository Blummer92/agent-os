from itertools import permutations

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
    validate_validation_plan,
    validation_plan_id,
)


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
COMMAND = "python -m pytest tests/agent_os_issue_labels"
RULES = load_rule_map()


def _select(paths: tuple[str, ...]):
    return select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=2287,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            changed_files=paths,
        ),
        RULES,
    )


def test_issue_label_source_and_tests_select_one_deduplicated_focused_command() -> None:
    paths = (
        "scripts/agent_os_issue_labels/pr_reconciler.py",
        "tests/agent_os_issue_labels/test_pr_reconciler.py",
    )
    plan = _select(paths)

    assert plan.profile == "focused"
    assert plan.commands == (COMMAND,)
    assert plan.reason_codes == ("profile.focused-package",)
    assert validate_validation_plan(plan) == ()


def test_2218_issue_label_caller_migration_shape_is_focused_when_bounded() -> None:
    paths = (
        "scripts/agent_os_issue_labels/pr_branch_refresh.py",
        "scripts/agent_os_issue_labels/pr_branch_refresh_authorization.py",
        "scripts/agent_os_issue_labels/pr_branch_refresh_operator.py",
        "tests/agent_os_issue_labels/lifecycle_admission.py",
        "tests/agent_os_issue_labels/test_2218_lifecycle_admission_caller_migration.py",
        "tests/agent_os_issue_labels/test_pr_branch_refresh.py",
        "tests/agent_os_issue_labels/test_pr_reconciler.py",
    )
    plan = _select(paths)

    assert plan.profile == "focused"
    assert plan.commands == (COMMAND,)
    assert plan.reason_codes == ("profile.focused-package",)


def test_2224_mixed_validation_workflow_shape_retains_aggregate_precedence() -> None:
    paths = (
        "scripts/agent_os_issue_labels/pr_branch_refresh.py",
        "tests/agent_os_issue_labels/test_pr_branch_refresh.py",
        "tests/test_agent_os_validation_workflow.py",
    )
    plan = _select(paths)

    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-configuration",)


def test_issue_label_plus_unknown_executable_fails_safe_to_aggregate() -> None:
    plan = _select(
        (
            "scripts/agent_os_issue_labels/checker.py",
            "scripts/unmapped_new_surface.py",
        )
    )

    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_issue_label_mapping_is_deterministic_across_changed_file_order() -> None:
    paths = (
        "scripts/agent_os_issue_labels/checker.py",
        "tests/agent_os_issue_labels/test_label_checker.py",
    )
    outcomes = {_select(tuple(order)) for order in permutations(paths)}

    assert len(outcomes) == 1
    plan = outcomes.pop()
    assert plan.commands == (COMMAND,)
    assert validation_plan_id(plan) == validation_plan_id(_select(paths))


def test_documentation_only_semantics_remain_static() -> None:
    plan = _select(("01_Shared_Standards/github/safe-implementation-lane.md",))

    assert plan.profile == "static"
    assert plan.commands == ()
    assert plan.reason_codes == ("profile.documentation-static",)


def test_existing_issue_acceptance_rule_remains_unchanged() -> None:
    plan = _select(("tests/agent_os_issue_acceptance/test_records.py",))

    assert plan.profile == "focused"
    assert plan.commands == ("python -m pytest tests/agent_os_issue_acceptance",)
    assert plan.reason_codes == ("profile.focused-package",)
