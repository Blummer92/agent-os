"""#2626: a new Issue Acceptance production module must reach its architecture guard.

PR #2613 (`primary_pr_creation_admission.py`) reached validation without a
`DOMAIN_RULES` registration and failed with "must have exactly one
architecture-domain classification; found none". The former #2619 materialization
contract was retired by #2926 after its live invariants moved into the canonical
primary-PR admission owner.

The governed path is already correct: the canonical selector maps this file
family to the package-level focused command, and that command contains
`test_architecture_boundaries.py`. What was missing is coverage proving it for a
*new production module*, which is the shape that actually failed. The existing
#2287 fixture only covers an existing test file.
"""

from itertools import permutations

from scripts.agent_os_issue_acceptance import __name__ as _issue_acceptance_package  # noqa: F401
from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
    validate_validation_plan,
)

from tests.agent_os_issue_acceptance.test_architecture_boundaries import (
    _classification_violations,
)


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
PACKAGE_COMMAND = "python -m pytest tests/agent_os_issue_acceptance"
GUARD = "tests/agent_os_issue_acceptance/test_architecture_boundaries.py"
RULES = load_rule_map()


def _select(paths: tuple[str, ...]):
    return select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=2626,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            changed_files=paths,
        ),
        RULES,
    )


def test_2613_new_production_module_selects_the_guard_carrying_command() -> None:
    plan = _select(
        (
            "scripts/agent_os_issue_acceptance/primary_pr_creation_admission.py",
            "tests/agent_os_issue_acceptance/test_primary_pr_creation_admission.py",
        )
    )
    assert plan.profile == "focused"
    assert plan.commands == (PACKAGE_COMMAND,)
    assert plan.reason_codes == ("profile.focused-package",)
    assert validate_validation_plan(plan) == ()


def test_production_module_without_any_focused_test_still_selects_the_guard() -> None:
    """The omission shape: a module added with no matching focused test file."""
    plan = _select(("scripts/agent_os_issue_acceptance/unregistered_new_surface.py",))
    assert plan.profile == "focused"
    assert plan.commands == (PACKAGE_COMMAND,)


def test_selected_command_covers_the_architecture_boundary_guard() -> None:
    """The selected command is a directory that contains the guard module."""
    selected_directory = PACKAGE_COMMAND.rsplit(" ", 1)[-1]
    assert GUARD.startswith(selected_directory + "/")


def test_unregistered_production_module_is_reported_by_that_guard() -> None:
    """Closing the chain: the guard the command runs does reject the omission."""
    violations = _classification_violations(("unregistered_new_surface",))
    assert len(violations) == 1
    assert "must have exactly one architecture-domain classification" in violations[0]
    assert "Register it in DOMAIN_RULES" in violations[0]


def test_selection_is_deterministic_across_changed_file_order() -> None:
    paths = (
        "scripts/agent_os_issue_acceptance/primary_pr_creation_admission.py",
        "tests/agent_os_issue_acceptance/test_primary_pr_creation_admission.py",
    )
    outcomes = {_select(tuple(order)) for order in permutations(paths)}
    assert len(outcomes) == 1
