"""#2135: a changed test path must always be executed before its PR merges.

The original form of this guard asserted that every example `tests/` path
matched an entry in `aggregate_prefixes`. That is a proxy for the real
criterion, and it is a proxy that cannot be satisfied without deleting focused
validation: `aggregate_prefixes` is evaluated *before* `focused_rules`, so the
blanket `tests/` entry it forced also swallowed `tests/agent_os_issue_acceptance/`
and every other focused owner rooted under `tests/`, silently breaking nineteen
selector contracts on `main`.

#2135's acceptance criterion is "a newly added test file is always executed by
some lane before its PR merges", so that is what this pins -- against the real
selector rather than against a string prefix. A focused command that runs the
changed test satisfies it exactly as well as the aggregate does.
"""
from pathlib import Path

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
)

ROOT = Path(__file__).resolve().parents[1]
RULES = load_rule_map()

EXAMPLES = (
    # Root test file owned by no focused rule.
    "tests/test_new_regression.py",
    # Unmapped test subpackage -- the #2048 shape that reached main unrun.
    "tests/agent_os_candidate_packet/test_new_regression.py",
    # Test inside a package that a focused rule already executes.
    "tests/agent_os_issue_acceptance/test_new_regression.py",
)


def _plan_for(path: str):
    return select_validation_plan(
        SelectionInput(
            repository=RULES["repository"],
            pull_request=2135,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=(path,),
        ),
        RULES,
    )


def _executes(commands: tuple[str, ...], path: str) -> bool:
    for command in commands:
        if command == RULES["aggregate_command"]:
            return True
        target = command.removeprefix("python -m pytest ").strip()
        if target == command:
            continue
        if path == target or path.startswith(target.rstrip("/") + "/"):
            return True
    return False


def test_every_root_test_change_is_executed_by_its_selected_profile():
    for path in EXAMPLES:
        plan = _plan_for(path)
        assert plan.profile in {"focused", "aggregate"}, (
            f"{path} selected non-executing profile {plan.profile!r}"
        )
        assert _executes(plan.commands, path), (
            f"{path} selected commands {plan.commands!r}, none of which execute it"
        )


def test_unmapped_test_paths_still_fall_back_to_the_aggregate():
    """The two shapes no focused rule owns must reach the full suite."""
    for path in EXAMPLES[:2]:
        plan = _plan_for(path)
        assert plan.profile == "aggregate", path
        assert plan.commands == (RULES["aggregate_command"],), path
