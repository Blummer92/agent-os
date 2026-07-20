from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
FIXTURES = Path(__file__).with_name("fixtures") / "selector_cases.yml"


def _input(paths: list[str], **overrides: object) -> SelectionInput:
    values = {
        "repository": "Blummer92/agent-os",
        "pull_request": 368,
        "base_sha": BASE_SHA,
        "head_sha": HEAD_SHA,
        "changed_files": tuple(paths),
    }
    values.update(overrides)
    return SelectionInput(**values)


def _fixtures() -> dict[str, list[str]]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_documentation_only_is_static_and_zero_build() -> None:
    plan = select_validation_plan(_input(_fixtures()["static"]))
    assert plan.profile == "static"
    assert plan.commands == ()
    assert plan.remote_build_required is False
    assert plan.execution_authorized is False
    assert plan.side_effects_performed is False


def test_mapped_package_is_focused() -> None:
    plan = select_validation_plan(_input(_fixtures()["focused"]))
    assert plan.profile == "focused"
    assert plan.commands == ("python -m pytest tests/agent_os_issue_acceptance",)
    assert plan.reason_codes == ("profile.focused-package",)
    assert plan.remote_build_required is True


def test_workflow_change_is_aggregate() -> None:
    plan = select_validation_plan(_input(_fixtures()["aggregate"]))
    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-configuration",)


def test_unknown_executable_fails_safe_to_aggregate() -> None:
    plan = select_validation_plan(_input(_fixtures()["unknown_executable"]))
    assert plan.profile == "aggregate"
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_ambiguous_non_executable_routes_to_manual_review() -> None:
    plan = select_validation_plan(_input(_fixtures()["ambiguous"]))
    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.command_set_digest == "unavailable"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"repository": "other/repo"}, "identity.repository-mismatch"),
        ({"pull_request": 0}, "metadata.malformed"),
        ({"base_sha": ""}, "identity.base-sha-missing"),
        ({"head_sha": ""}, "identity.head-sha-missing"),
        ({"selector_version": "2.0.0"}, "rule.version-unsupported"),
    ],
)
def test_invalid_identity_fails_closed(overrides: dict[str, object], reason: str) -> None:
    plan = select_validation_plan(_input(["README.md"], **overrides))
    assert plan.profile == "manual-review"
    assert plan.reason_codes == (reason,)
    assert plan.remote_build_required is False


def test_empty_changed_files_fail_closed() -> None:
    plan = select_validation_plan(_input([]))
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("metadata.empty-changed-files",)


def test_repeated_input_is_deterministic() -> None:
    value = _input(_fixtures()["focused"])
    assert select_validation_plan(value) == select_validation_plan(value)


def test_rule_or_command_change_changes_digest() -> None:
    value = _input(_fixtures()["focused"])
    original = select_validation_plan(value)
    rules = load_rule_map()
    rules["focused_rules"][0]["commands"] = ["python -m pytest tests/agent_os_issue_acceptance -q"]
    changed = select_validation_plan(value, rules)
    assert original.command_set_digest != changed.command_set_digest


def test_plan_is_immutable() -> None:
    plan = select_validation_plan(_input(_fixtures()["static"]))
    with pytest.raises(FrozenInstanceError):
        plan.profile = "aggregate"  # type: ignore[misc]
