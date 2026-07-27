from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import (
    MAX_PLAN_COMMANDS,
    MAX_PLAN_STRING_LENGTH,
    SelectionInput,
    compute_command_set_digest,
    load_rule_map,
    select_validation_plan,
    serialize_validation_plan,
    validate_validation_plan,
    validation_plan_id,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
FIXTURES = Path(__file__).with_name("fixtures") / "selector_cases.yml"
RULES = load_rule_map()


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


def _select(value: SelectionInput, rules: dict[str, object] | None = None):
    return select_validation_plan(value, rules or RULES)


def test_documentation_only_is_static_and_zero_build() -> None:
    plan = _select(_input(_fixtures()["static"]))
    assert plan.profile == "static"
    assert plan.commands == ()
    assert plan.remote_build_required is False
    assert plan.execution_authorized is False
    assert plan.side_effects_performed is False
    assert validate_validation_plan(plan) == ()


def test_mapped_package_is_focused() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    assert plan.profile == "focused"
    assert plan.commands == (
        "python -m pytest tests/agent_os_issue_acceptance",
    )
    assert plan.reason_codes == ("profile.focused-package",)
    assert plan.remote_build_required is True
    assert validate_validation_plan(plan) == ()


def test_workflow_change_is_aggregate() -> None:
    plan = _select(_input(_fixtures()["aggregate"]))
    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-configuration",)
    assert validate_validation_plan(plan) == ()


def test_unknown_executable_fails_safe_to_aggregate() -> None:
    plan = _select(_input(_fixtures()["unknown_executable"]))
    assert plan.profile == "aggregate"
    assert plan.reason_codes == (
        "profile.aggregate-unmapped-executable",
    )


def test_ambiguous_non_executable_routes_to_manual_review() -> None:
    plan = _select(_input(_fixtures()["ambiguous"]))
    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.command_set_digest == "unavailable"
    assert validate_validation_plan(plan) == ()


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"repository": "other/repo"}, "identity.repository-mismatch"),
        ({"pull_request": 0}, "metadata.malformed"),
        ({"pull_request": True}, "metadata.malformed"),
        ({"base_sha": ""}, "identity.base-sha-missing"),
        ({"head_sha": ""}, "identity.head-sha-missing"),
        ({"selector_version": "2.0.0"}, "rule.version-unsupported"),
    ],
)
def test_invalid_identity_fails_closed(
    overrides: dict[str, object],
    reason: str,
) -> None:
    plan = _select(_input(["README.md"], **overrides))
    assert plan.profile == "manual-review"
    assert plan.reason_codes == (reason,)
    assert plan.remote_build_required is False
    assert validate_validation_plan(plan) == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": None},
        {"base_sha": None},
        {"head_sha": None},
        {"selector_version": None},
        {"changed_files": (None,)},
    ],
)
def test_malformed_runtime_types_do_not_raise(
    overrides: dict[str, object],
) -> None:
    plan = _select(_input(["README.md"], **overrides))
    assert plan.profile == "manual-review"
    assert plan.remote_build_required is False


def test_empty_changed_files_fail_closed() -> None:
    plan = _select(_input([]))
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("metadata.empty-changed-files",)


def test_malformed_rule_map_fails_closed() -> None:
    plan = _select(_input(_fixtures()["focused"]), {"bad": "map"})
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_repeated_input_is_deterministic() -> None:
    value = _input(_fixtures()["focused"])
    assert _select(value) == _select(value)


def test_rule_or_command_change_changes_digest() -> None:
    value = _input(_fixtures()["focused"])
    original = _select(value)
    rules = copy.deepcopy(RULES)
    rules["focused_rules"][0]["commands"] = [
        "python -m pytest tests/agent_os_issue_acceptance -q"
    ]
    changed = _select(value, rules)
    assert original.command_set_digest != changed.command_set_digest


def test_public_digest_matches_selector_and_binds_exact_order() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    assert plan.command_set_digest == compute_command_set_digest(
        plan.selector_version, plan.commands
    )
    assert compute_command_set_digest("1.0.0", ("one", "two")) != (
        compute_command_set_digest("1.0.0", ("two", "one"))
    )


@pytest.mark.parametrize(
    "changed,reason",
    [
        ({"command_set_digest": "0" * 64}, "plan.command-digest"),
        ({"commands": ("one", "one")}, "plan.commands-duplicate"),
        ({"commands": ()}, "plan.executable-commands"),
        ({"remote_build_required": False}, "plan.executable-remote-build"),
        ({"execution_authorized": True}, "plan.execution-authorized"),
        ({"side_effects_performed": True}, "plan.side-effects"),
        ({"reason_codes": ("rule.ambiguous",)}, "plan.reason-profile"),
    ],
)
def test_plan_mutations_fail_closed(changed: dict[str, object], reason: str) -> None:
    plan = _select(_input(_fixtures()["focused"]))
    mutated = replace(plan, **changed)
    assert reason in validate_validation_plan(mutated)


def test_command_mutation_and_reordering_fail_digest_validation() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    mutated = replace(plan, commands=(plan.commands[0] + " -q",))
    assert "plan.command-digest" in validate_validation_plan(mutated)

    aggregate = replace(
        plan,
        commands=("first", "second"),
        command_set_digest=compute_command_set_digest(
            plan.selector_version, ("first", "second")
        ),
    )
    reordered = replace(aggregate, commands=("second", "first"))
    assert "plan.command-digest" in validate_validation_plan(reordered)


def test_static_and_manual_review_invariants_fail_closed() -> None:
    static = _select(_input(_fixtures()["static"]))
    assert "plan.static-commands" in validate_validation_plan(
        replace(static, commands=("echo unsafe",))
    )

    manual = _select(_input(_fixtures()["ambiguous"]))
    assert "plan.manual-review-digest" in validate_validation_plan(
        replace(manual, command_set_digest="0" * 64)
    )


def test_bounds_and_control_characters_fail_closed() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    too_many = tuple(f"command-{index}" for index in range(MAX_PLAN_COMMANDS + 1))
    assert "plan.commands-limit" in validate_validation_plan(
        replace(
            plan,
            commands=too_many,
            command_set_digest=compute_command_set_digest(plan.selector_version, too_many),
        )
    )
    assert "plan.command-invalid" in validate_validation_plan(
        replace(
            plan,
            commands=("x" * (MAX_PLAN_STRING_LENGTH + 1),),
            command_set_digest=compute_command_set_digest(
                plan.selector_version, ("x" * (MAX_PLAN_STRING_LENGTH + 1),)
            ),
        )
    )
    assert "plan.command-invalid" in validate_validation_plan(
        replace(
            plan,
            commands=("echo\x00secret",),
            command_set_digest=compute_command_set_digest(
                plan.selector_version, ("echo\x00secret",)
            ),
        )
    )


def test_canonical_serialization_and_plan_id_are_deterministic() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    first = serialize_validation_plan(plan)
    second = serialize_validation_plan(plan)
    assert first == second
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    )
    assert validation_plan_id(plan) == validation_plan_id(plan)
    assert validation_plan_id(plan).startswith("validation-plan:")


def test_semantic_change_changes_plan_id() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    changed_commands = (plan.commands[0] + " -q",)
    changed = replace(
        plan,
        commands=changed_commands,
        command_set_digest=compute_command_set_digest(
            plan.selector_version, changed_commands
        ),
    )
    assert validate_validation_plan(changed) == ()
    assert validation_plan_id(plan) != validation_plan_id(changed)


def test_invalid_plan_cannot_be_serialized_or_identified() -> None:
    plan = replace(
        _select(_input(_fixtures()["focused"])),
        command_set_digest="0" * 64,
    )
    with pytest.raises(ValueError, match="invalid validation plan"):
        serialize_validation_plan(plan)
    with pytest.raises(ValueError, match="invalid validation plan"):
        validation_plan_id(plan)


def test_selection_performs_no_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    value = _input(_fixtures()["focused"])

    def fail_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("selection attempted file I/O")

    monkeypatch.setattr(Path, "read_text", fail_read)
    plan = select_validation_plan(value, RULES)
    assert plan.profile == "focused"
    assert validate_validation_plan(plan) == ()


def test_plan_is_immutable() -> None:
    plan = _select(_input(_fixtures()["static"]))
    with pytest.raises(FrozenInstanceError):
        plan.profile = "aggregate"  # type: ignore[misc]


CLS_CASES = (
    (
        "tests/test_curriculum_pipeline_boundaries.py",
        "python -m pytest tests/test_curriculum_pipeline_boundaries.py",
    ),
    (
        "tests/test_curriculum_language_system.py",
        "python -m pytest tests/test_curriculum_language_system.py",
    ),
    (
        "tests/test_teacher_modeling_workflows.py",
        "python -m pytest tests/test_teacher_modeling_workflows.py",
    ),
)


@pytest.mark.parametrize(("path", "command"), CLS_CASES)
def test_exact_cls_path_selects_only_its_command(path: str, command: str) -> None:
    plan = _select(_input([path]))
    assert plan.profile == "focused"
    assert plan.commands == (command,)
    assert plan.reason_codes == ("profile.focused-package",)
    assert validate_validation_plan(plan) == ()


@pytest.mark.parametrize(
    "paths",
    [
        [CLS_CASES[0][0], CLS_CASES[1][0]],
        [CLS_CASES[0][0], CLS_CASES[2][0]],
        [CLS_CASES[1][0], CLS_CASES[2][0]],
        [case[0] for case in CLS_CASES],
    ],
)
def test_exact_cls_path_unions_are_deterministic(paths: list[str]) -> None:
    expected = tuple(sorted(command for path, command in CLS_CASES if path in paths))
    forward = _select(_input(paths))
    reverse = _select(_input(list(reversed(paths))))
    assert forward.profile == "focused"
    assert forward.commands == expected
    assert forward.reason_codes == ("profile.focused-union",)
    assert reverse == forward


def test_exact_path_lookalike_retains_aggregate_fallback() -> None:
    lookalike = "tests/test_curriculum_pipeline_boundaries.py.lookalike.py"
    plan = _select(_input([lookalike]))
    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_exact_and_prefix_surfaces_remain_distinct() -> None:
    exact = _select(_input([CLS_CASES[0][0]]))
    prefix = _select(_input(["tests/agent_os_issue_acceptance/test_records.py"]))
    assert exact.commands == (CLS_CASES[0][1],)
    assert prefix.commands == ("python -m pytest tests/agent_os_issue_acceptance",)


def test_old_prefix_only_rule_maps_remain_valid() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"] = [
        {
            "name": "legacy-prefix",
            "prefixes": ["legacy/"],
            "commands": ["python -m pytest legacy/tests"],
        }
    ]
    plan = _select(_input(["legacy/module.py"]), rules)
    assert plan.profile == "focused"
    assert plan.commands == ("python -m pytest legacy/tests",)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda rule: rule.update({"prefixes": [], "exact_paths": []}),
        lambda rule: rule.update({"exact_paths": "not-a-list"}),
        lambda rule: rule.update({"exact_paths": [""]}),
        lambda rule: rule.update({"exact_paths": ["bad\x00path"]}),
    ],
)
def test_malformed_matching_surfaces_fail_closed(mutator) -> None:
    rules = copy.deepcopy(RULES)
    rule = rules["focused_rules"][0]
    mutator(rule)
    plan = _select(_input(_fixtures()["focused"]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_same_path_with_different_command_sets_fails_closed() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"].extend(
        [
            {
                "name": "conflicting-exact-owner",
                "exact_paths": [CLS_CASES[0][0]],
                "commands": ["python -m pytest tests/other.py"],
            }
        ]
    )
    plan = _select(_input([CLS_CASES[0][0]]), rules)
    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.reason_codes == ("rule.ambiguous",)


def test_same_path_duplicate_ownership_with_same_commands_is_stable() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"].append(
        {
            "name": "equivalent-exact-owner",
            "exact_paths": [CLS_CASES[0][0]],
            "commands": [CLS_CASES[0][1]],
        }
    )
    plan = _select(_input([CLS_CASES[0][0]]), rules)
    assert plan.profile == "focused"
    assert plan.commands == (CLS_CASES[0][1],)


def test_different_paths_with_different_rules_form_bounded_union() -> None:
    paths = [CLS_CASES[0][0], "tests/agent_os_issue_acceptance/test_records.py"]
    plan = _select(_input(paths))
    assert plan.profile == "focused"
    assert plan.commands == tuple(
        sorted(
            (
                CLS_CASES[0][1],
                "python -m pytest tests/agent_os_issue_acceptance",
            )
        )
    )
    assert plan.reason_codes == ("profile.focused-union",)
