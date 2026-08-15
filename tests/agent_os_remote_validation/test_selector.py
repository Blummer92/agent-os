from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from itertools import permutations
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import (
    MAX_PLAN_COMMANDS,
    MAX_PLAN_STRING_LENGTH,
    PRE_PR_PER_COMMAND_TIMEOUT_SECONDS,
    PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS,
    PrePrValidationPlan,
    PrePrValidationSubject,
    SelectionInput,
    compute_command_set_digest,
    deserialize_pre_pr_validation_subject,
    load_rule_map,
    pre_pr_validation_plan_id,
    pre_pr_validation_subject_id,
    select_pre_pr_validation_plan,
    select_validation_plan,
    serialize_pre_pr_validation_plan,
    serialize_pre_pr_validation_subject,
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
    rules["command_coverage"] = []
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


# --- Positive-PR characterization (#723 regression guard) ---------------------
POSITIVE_PR_GOLDEN = {
    "static": (
        "static",
        (),
        ("profile.documentation-static",),
        "9715a2ba3b1b7c2ad8ea0a7d4eed78cd572d7161ca5b9115dc7f41ce69d1ccc6",
        "validation-plan:"
        "577d0214ac14911fd06f7f7c6293c35e54865ce5abcb741bf46343ff872c2546",
    ),
    "focused": (
        "focused",
        ("python -m pytest tests/agent_os_issue_acceptance",),
        ("profile.focused-package",),
        "500ab081d9fd660f55429483dece9c170a7a942248fb7a4d1443c32b457cf3b5",
        "validation-plan:"
        "ce62f16c71f7d87524796bb3852f7979ffce689421339dc2ac4da9d872280efe",
    ),
    "aggregate": (
        "aggregate",
        ("python -m pytest",),
        ("profile.aggregate-configuration",),
        "e05f8317cfacd9ba8ebec4a2141aba7aa8437e15b0ae56c64d3280fb1a9526e2",
        "validation-plan:"
        "3872524b39655f6690455391dc66b5600a6990f5bb00fd508d04df16a4c8977c",
    ),
    "unknown_executable": (
        "aggregate",
        ("python -m pytest",),
        ("profile.aggregate-unmapped-executable",),
        "e05f8317cfacd9ba8ebec4a2141aba7aa8437e15b0ae56c64d3280fb1a9526e2",
        "validation-plan:"
        "515c31935690d46cec98ca20757087ac584107ef74412db44aba432f19339770",
    ),
    "ambiguous": (
        "manual-review",
        (),
        ("rule.ambiguous",),
        "unavailable",
        "validation-plan:"
        "22006c2c9df13ebf862332af354746bf771bdfeaeed3dabcf62c929e710101c0",
    ),
}


@pytest.mark.parametrize("case", sorted(POSITIVE_PR_GOLDEN))
def test_positive_pr_selection_and_identity_are_unchanged(case: str) -> None:
    profile, commands, reasons, digest, identity = POSITIVE_PR_GOLDEN[case]
    plan = _select(_input(_fixtures()[case]))
    assert plan.profile == profile
    assert plan.commands == commands
    assert plan.reason_codes == reasons
    assert plan.command_set_digest == digest
    assert validate_validation_plan(plan) == ()
    assert validation_plan_id(plan) == identity


def test_positive_pr_focused_payload_is_byte_stable() -> None:
    plan = _select(_input(_fixtures()["focused"]))
    payload = serialize_validation_plan(plan)
    assert json.dumps(payload, sort_keys=True, separators=(",", ":")) == (
        '{"base_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        '"command_set_digest":'
        '"500ab081d9fd660f55429483dece9c170a7a942248fb7a4d1443c32b457cf3b5",'
        '"commands":["python -m pytest tests/agent_os_issue_acceptance"],'
        '"execution_authorized":false,'
        '"head_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
        '"profile":"focused","pull_request":368,'
        '"reason_codes":["profile.focused-package"],'
        '"remote_build_required":true,"repository":"Blummer92/agent-os",'
        '"schema_name":"agent-os-validation-plan","schema_version":"1.0",'
        '"selector_version":"1.0.0","side_effects_performed":false}'
    )


def test_unrelated_scheduler_paths_keep_the_package_rule() -> None:
    plan = _select(_input(["08_Tooling/workflow-scheduler/src/runtime.py"]))
    assert plan.profile == "focused"
    assert plan.commands == ("python -m pytest 08_Tooling/workflow-scheduler/tests",)
    assert validation_plan_id(plan) == (
        "validation-plan:"
        "6a4cd85d9acab71dee7a4baf3b6b9fa45328551b9e4c597dddbdf7b300f9aaef"
    )


# --- Pre-PR validation subject and plan (#723 / candidate #726) ---------------

PILOT_COMMAND = (
    "python -m pytest "
    "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
)
PILOT_PATH = "08_Tooling/workflow-scheduler/tests/test_concrete_runtime_adapters.py"
PILOT_SHA = "df2d7d61db66d0835ed4ca6c9ec6d3fdcf85f465"
PILOT_FORBIDDEN = (".github/workflows", "cloudbuild.yaml", "scripts/validate-all.sh")


def _subject(**overrides: object) -> PrePrValidationSubject:
    values: dict[str, object] = {
        "invocation_id": "invocation:726:0001",
        "base_sha": PILOT_SHA,
        "branch": "agent/723-pre-pr-validation-planning",
        "expected_source_sha": PILOT_SHA,
        "tested_sha": PILOT_SHA,
        "allowed_files": (PILOT_PATH,),
        "forbidden_paths": PILOT_FORBIDDEN,
        "required_command_identities": (PILOT_COMMAND,),
        "approval_id": "approval:398:0001",
        "approval_revision": 1,
        "projection_id": "projection:407:0001",
        "implementation_contract_fingerprint": "c" * 64,
    }
    values.update(overrides)
    return PrePrValidationSubject(**values)  # type: ignore[arg-type]


def test_exact_pilot_rule_owns_its_path_over_the_package_prefix() -> None:
    plan = _select(_input([PILOT_PATH]))
    assert plan.profile == "focused"
    assert plan.commands == (PILOT_COMMAND,)
    assert plan.reason_codes == ("profile.focused-package",)
    assert validate_validation_plan(plan) == ()


def test_valid_pre_pr_subject_binds_candidate_726() -> None:
    subject = _subject()
    assert subject.schema_name == "agent-os-pre-pr-validation-subject"
    assert subject.schema_version == "1.0"
    assert subject.repository == "Blummer92/agent-os"
    assert subject.issue_number == 726
    assert subject.base_branch == "main"
    assert subject.execution_mode == "validation-only"
    payload = serialize_pre_pr_validation_subject(subject)
    assert "pull_request" not in payload
    assert payload["required_command_identities"] == [PILOT_COMMAND]
    assert pre_pr_validation_subject_id(subject).startswith(
        "pre-pr-validation-subject:"
    )


def test_pre_pr_plan_is_deterministic_and_non_authorizing() -> None:
    subject = _subject()
    first = select_pre_pr_validation_plan(subject, RULES)
    second = select_pre_pr_validation_plan(subject, RULES)
    assert first == second
    assert first.profile == "focused"
    assert first.commands == (PILOT_COMMAND,)
    assert first.reason_codes == ("profile.focused-package",)
    assert first.selector_version == "1.0.0"
    assert first.command_set_digest == compute_command_set_digest(
        "1.0.0", (PILOT_COMMAND,)
    )
    assert first.per_command_timeout_seconds == PRE_PR_PER_COMMAND_TIMEOUT_SECONDS
    assert first.total_validation_timeout_seconds == (
        PRE_PR_TOTAL_VALIDATION_TIMEOUT_SECONDS
    )
    payload = serialize_pre_pr_validation_plan(first)
    assert payload["remote_build_required"] is False
    assert payload["execution_authorized"] is False
    assert payload["merge_authorized"] is False
    assert payload["side_effects_performed"] is False
    assert payload["subject_id"] == pre_pr_validation_subject_id(subject)
    assert json.dumps(payload, sort_keys=True, separators=(",", ":")) == json.dumps(
        serialize_pre_pr_validation_plan(second), sort_keys=True, separators=(",", ":")
    )


def test_pre_pr_identity_is_domain_separated_and_stable() -> None:
    plan = select_pre_pr_validation_plan(_subject(), RULES)
    identity = pre_pr_validation_plan_id(plan)
    assert identity == pre_pr_validation_plan_id(plan)
    assert identity.startswith("pre-pr-validation-plan:")
    assert identity == (
        "pre-pr-validation-plan:"
        "4198425ecf4f50d3ce2fc24caf0a2c9c5505357e0f8449bfe8dd61265e743199"
    )


def test_pre_pr_semantic_change_changes_plan_id() -> None:
    original = select_pre_pr_validation_plan(_subject(), RULES)
    changed = select_pre_pr_validation_plan(
        _subject(invocation_id="invocation:726:0002"), RULES
    )
    assert pre_pr_validation_plan_id(original) != pre_pr_validation_plan_id(changed)


# --- Candidate-bound pre-PR compatibility (#1030) -----------------------------


def _candidate_subject(**overrides: object) -> PrePrValidationSubject:
    values: dict[str, object] = {
        "issue_number": 754,
        "invocation_id": "invocation:754:0001",
        "base_sha": "a" * 40,
        "branch": "agent/754-validation-packet",
        "expected_source_sha": "d" * 40,
        "tested_sha": "e" * 40,
        "allowed_files": (PILOT_PATH,),
        "forbidden_paths": PILOT_FORBIDDEN,
        "required_command_identities": (PILOT_COMMAND,),
        "approval_id": "approval:754:0001",
        "approval_revision": 1,
        "projection_id": "projection:754:0001",
        "implementation_contract_fingerprint": "f" * 64,
        "candidate_bound": True,
    }
    values.update(overrides)
    return PrePrValidationSubject(**values)  # type: ignore[arg-type]


def test_candidate_bound_non_726_subject_preserves_distinct_sha_roles() -> None:
    subject = _candidate_subject()
    assert subject.candidate_bound is True
    assert subject.issue_number == 754
    assert subject.expected_source_sha == "d" * 40
    assert subject.tested_sha == "e" * 40
    assert subject.expected_source_sha != subject.tested_sha


def test_candidate_bound_serialization_and_round_trip_are_exact() -> None:
    subject = _candidate_subject()
    payload = serialize_pre_pr_validation_subject(subject)
    assert payload["candidate_bound"] is True
    assert payload["issue_number"] == 754
    assert payload["repository"] == "Blummer92/agent-os"
    assert payload["base_branch"] == "main"
    assert payload["branch"] == "agent/754-validation-packet"
    assert payload["expected_source_sha"] == "d" * 40
    assert payload["tested_sha"] == "e" * 40
    assert payload["allowed_files"] == [PILOT_PATH]
    assert payload["forbidden_paths"] == list(PILOT_FORBIDDEN)
    assert payload["required_command_identities"] == [PILOT_COMMAND]

    reconstructed = deserialize_pre_pr_validation_subject(payload)
    assert reconstructed == subject
    assert serialize_pre_pr_validation_subject(reconstructed) == payload
    assert pre_pr_validation_subject_id(reconstructed) == pre_pr_validation_subject_id(subject)


def test_legacy_726_serialization_omits_candidate_bound() -> None:
    payload = serialize_pre_pr_validation_subject(_subject())
    assert "candidate_bound" not in payload


def test_non_726_requires_explicit_candidate_bound_mode() -> None:
    with pytest.raises(ValueError, match="bound validation-only candidate issue"):
        _subject(issue_number=754)


def test_deserialization_rejects_missing_required_field() -> None:
    payload = serialize_pre_pr_validation_subject(_subject())
    del payload["repository"]
    with pytest.raises(ValueError, match="payload fields drift"):
        deserialize_pre_pr_validation_subject(payload)


def test_deserialization_rejects_unexpected_field() -> None:
    payload = serialize_pre_pr_validation_subject(_subject())
    payload["unexpected"] = "value"
    with pytest.raises(ValueError, match="payload fields drift"):
        deserialize_pre_pr_validation_subject(payload)


def test_deserialization_rejects_explicit_false_candidate_bound() -> None:
    payload = serialize_pre_pr_validation_subject(_subject())
    payload["candidate_bound"] = False
    with pytest.raises(TypeError, match="exactly true"):
        deserialize_pre_pr_validation_subject(payload)


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_deserialization_rejects_non_boolean_candidate_bound(value: object) -> None:
    payload = serialize_pre_pr_validation_subject(_subject())
    payload["candidate_bound"] = value
    with pytest.raises(TypeError, match="exactly true"):
        deserialize_pre_pr_validation_subject(payload)


@pytest.mark.parametrize("value", [0, 1, "true", None])
def test_constructor_rejects_non_exact_bool_candidate_bound(value: object) -> None:
    with pytest.raises(TypeError, match="candidate_bound"):
        _subject(candidate_bound=value)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"issue_number": 725}, ValueError),
        ({"issue_number": 0}, TypeError),
        ({"issue_number": True}, TypeError),
        ({"issue_number": "726"}, TypeError),
        ({"invocation_id": ""}, ValueError),
        ({"invocation_id": "-leading-dash"}, ValueError),
        ({"invocation_id": "has space"}, ValueError),
        ({"invocation_id": None}, TypeError),
        ({"approval_id": "bad\x00id"}, ValueError),
        ({"approval_revision": 0}, TypeError),
        ({"approval_revision": 1.0}, TypeError),
        ({"projection_id": None}, TypeError),
        ({"implementation_contract_fingerprint": "c" * 63}, ValueError),
        ({"implementation_contract_fingerprint": "C" * 64}, ValueError),
        ({"base_sha": "d" * 39}, ValueError),
        ({"base_sha": PILOT_SHA.upper()}, ValueError),
        ({"expected_source_sha": None}, TypeError),
    ],
)
def test_invalid_pre_pr_identifiers_fail_closed(
    overrides: dict[str, object],
    error: type[Exception],
) -> None:
    with pytest.raises(error):
        _subject(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"tested_sha": "e" * 40},
        {"branch": "main"},
        {"branch": "Main"},
        {"branch": "master"},
        {"branch": "refs/heads/../main"},
        {"branch": "agent/bad branch"},
        {"base_branch": "develop"},
        {"repository": "other/repo"},
        {"execution_mode": "standard"},
        {"schema_version": "2.0"},
    ],
)
def test_pre_pr_identity_drift_fails_closed_at_construction(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        _subject(**overrides)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "other/repo"),
        ("branch", "main"),
        ("tested_sha", "e" * 40),
        ("expected_source_sha", "not-a-sha"),
        ("base_branch", "develop"),
        ("execution_mode", "standard"),
    ],
)
def test_pre_pr_selector_rechecks_bypassed_bindings(field: str, value: str) -> None:
    subject = _subject()
    object.__setattr__(subject, field, value)
    with pytest.raises(ValueError):
        select_pre_pr_validation_plan(subject, RULES)


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_files": ()},
        {"allowed_files": (PILOT_PATH, "00_Governance")},
        {"allowed_files": (PILOT_PATH, PILOT_PATH)},
        {"allowed_files": ("b.py", "a.py")},
        {"allowed_files": ("08_Tooling", PILOT_PATH)},
        {"allowed_files": ("/absolute/path.py",)},
        {"allowed_files": ("../escape.py",)},
        {"allowed_files": ("bad\x00path.py",)},
        {"allowed_files": [PILOT_PATH]},
        {"forbidden_paths": ()},
        {"forbidden_paths": ("cloudbuild.yaml", ".github/workflows")},
        {"forbidden_paths": ("08_Tooling",)},
        {"required_command_identities": ()},
        {"required_command_identities": (PILOT_COMMAND, PILOT_COMMAND)},
        {"required_command_identities": ("echo\x00unsafe",)},
        {"required_command_identities": [PILOT_COMMAND]},
    ],
)
def test_pre_pr_canonical_tuples_fail_closed(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        _subject(**overrides)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"per_command_timeout_seconds": 31}, ValueError),
        ({"total_validation_timeout_seconds": 301}, ValueError),
        ({"per_command_timeout_seconds": 0}, TypeError),
        ({"total_validation_timeout_seconds": -1}, TypeError),
        ({"per_command_timeout_seconds": 30.0}, TypeError),
        (
            {"per_command_timeout_seconds": 30, "total_validation_timeout_seconds": 10},
            ValueError,
        ),
    ],
)
def test_pre_pr_timeout_ceilings_are_enforced(
    overrides: dict[str, object],
    error: type[Exception],
) -> None:
    subject = _subject()
    valid = select_pre_pr_validation_plan(subject, RULES)
    values: dict[str, object] = {
        "selector_version": valid.selector_version,
        "subject": subject,
        "commands": valid.commands,
        "command_set_digest": valid.command_set_digest,
        "reason_codes": valid.reason_codes,
    }
    values.update(overrides)
    with pytest.raises(error):
        PrePrValidationPlan(**values)  # type: ignore[arg-type]


def test_pre_pr_selector_fails_closed_on_scope_and_command_drift() -> None:
    with pytest.raises(ValueError, match="partial focused coverage"):
        select_pre_pr_validation_plan(
            _subject(allowed_files=(PILOT_PATH, "assets/example.bin")), RULES
        )
    with pytest.raises(ValueError, match="focused coverage"):
        select_pre_pr_validation_plan(
            _subject(allowed_files=("pyproject.toml",)), RULES
        )
    with pytest.raises(ValueError, match="command identity drift"):
        select_pre_pr_validation_plan(
            _subject(required_command_identities=("python -m pytest",)), RULES
        )
    with pytest.raises(ValueError, match="rule map is not usable"):
        select_pre_pr_validation_plan(_subject(), {"bad": "map"})
    with pytest.raises(ValueError, match="repository drift"):
        rules = copy.deepcopy(RULES)
        rules["repository"] = "other/repo"
        select_pre_pr_validation_plan(_subject(), rules)
    with pytest.raises(TypeError, match="exact PrePrValidationSubject"):
        select_pre_pr_validation_plan(object(), RULES)


def test_pre_pr_ambiguous_ownership_fails_closed() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"].append(
        {
            "name": "conflicting-pilot-owner",
            "exact_paths": [PILOT_PATH],
            "commands": ["python -m pytest tests/other.py"],
        }
    )
    with pytest.raises(ValueError, match="ambiguous focused coverage"):
        select_pre_pr_validation_plan(_subject(), rules)


def test_pre_pr_plan_serialization_rejects_bypassed_invariants() -> None:
    plan = select_pre_pr_validation_plan(_subject(), RULES)
    for field, value in (
        ("execution_authorized", True),
        ("merge_authorized", True),
        ("side_effects_performed", True),
        ("remote_build_required", True),
        ("profile", "aggregate"),
        ("command_set_digest", "0" * 64),
        ("reason_codes", ("rule.ambiguous",)),
        ("per_command_timeout_seconds", 31),
    ):
        mutated = select_pre_pr_validation_plan(_subject(), RULES)
        object.__setattr__(mutated, field, value)
        with pytest.raises(ValueError, match="invalid pre-PR validation plan"):
            serialize_pre_pr_validation_plan(mutated)
        with pytest.raises(ValueError, match="invalid pre-PR validation plan"):
            pre_pr_validation_plan_id(mutated)
    with pytest.raises(TypeError, match="exact PrePrValidationPlan"):
        serialize_pre_pr_validation_plan(plan.subject)


def test_pre_pr_plan_and_subject_are_immutable() -> None:
    plan = select_pre_pr_validation_plan(_subject(), RULES)
    with pytest.raises(FrozenInstanceError):
        plan.profile = "aggregate"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan.subject.branch = "main"  # type: ignore[misc]


def test_pre_pr_selection_performs_no_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    subject = _subject()

    def fail_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("pre-PR selection attempted file I/O")

    monkeypatch.setattr(Path, "read_text", fail_read)
    plan = select_pre_pr_validation_plan(subject, RULES)
    assert plan.commands == (PILOT_COMMAND,)


# --- Exact-over-prefix precedence semantics (#723 review H1/B2) ---------------
SCHEDULER_PACKAGE_COMMAND = "python -m pytest 08_Tooling/workflow-scheduler/tests"
SCHEDULER_SIBLING_PATH = "08_Tooling/workflow-scheduler/src/runtime.py"


def test_mixed_exact_and_prefix_paths_form_a_safe_superset_union() -> None:
    # #729: explicit coverage proves the broader package command already
    # executes the narrower exact-path command, so the narrow command is
    # suppressed from the focused union rather than run twice.
    paths = [PILOT_PATH, SCHEDULER_SIBLING_PATH]
    plan = _select(_input(paths))
    assert plan.profile == "focused"
    assert plan.reason_codes == ("profile.focused-union",)
    assert plan.commands == (SCHEDULER_PACKAGE_COMMAND,)
    assert PILOT_COMMAND.startswith(SCHEDULER_PACKAGE_COMMAND)
    assert plan.remote_build_required is True
    assert validate_validation_plan(plan) == ()
    assert plan.command_set_digest == compute_command_set_digest(
        "1.0.0", (SCHEDULER_PACKAGE_COMMAND,)
    )
    assert plan.command_set_digest == (
        "3097113361d5a7559dba62f28f8aeea873f6ad5011536e29a9837e1352d40250"
    )
    assert validation_plan_id(plan) == (
        "validation-plan:"
        "980493f198e70547c4edebf55414e2fd1e1fa31a895437e826b9e4546dc787fb"
    )
    assert serialize_validation_plan(plan) == serialize_validation_plan(_select(_input(paths)))


def test_mixed_exact_and_prefix_union_ignores_changed_file_order() -> None:
    paths = [PILOT_PATH, SCHEDULER_SIBLING_PATH, "tests/test_curriculum_language_system.py"]
    outcomes = {_select(_input(list(order))) for order in permutations(paths)}
    assert len(outcomes) == 1
    only = outcomes.pop()
    assert only.reason_codes == ("profile.focused-union",)
    assert only.commands == tuple(sorted(only.commands))


def test_exact_owner_masks_multiple_matching_prefix_rules() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"].append(
        {
            "name": "second-scheduler-prefix-owner",
            "prefixes": ["08_Tooling/workflow-scheduler/"],
            "commands": ["python -m pytest tests/other.py"],
        }
    )
    exact_owned = _select(_input([PILOT_PATH]), rules)
    assert exact_owned.profile == "focused"
    assert exact_owned.commands == (PILOT_COMMAND,)
    assert exact_owned.reason_codes == ("profile.focused-package",)

    prefix_only = _select(_input([SCHEDULER_SIBLING_PATH]), rules)
    assert prefix_only.profile == "manual-review"
    assert prefix_only.commands == ()
    assert prefix_only.reason_codes == ("rule.ambiguous",)


def test_multiple_exact_owners_still_fail_closed_as_ambiguous() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"].append(
        {
            "name": "conflicting-exact-pilot-owner",
            "exact_paths": [PILOT_PATH],
            "commands": ["python -m pytest tests/other.py"],
        }
    )
    plan = _select(_input([PILOT_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.reason_codes == ("rule.ambiguous",)


def test_multiple_prefix_owners_without_exact_owner_fail_closed() -> None:
    rules = copy.deepcopy(RULES)
    rules["focused_rules"].append(
        {
            "name": "conflicting-notion-prefix-owner",
            "prefixes": ["08_Tooling/notion-navigation-client/"],
            "commands": ["python -m pytest tests/other.py"],
        }
    )
    plan = _select(_input(["08_Tooling/notion-navigation-client/src/reader.py"]), rules)
    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.reason_codes == ("rule.ambiguous",)


@pytest.mark.parametrize(
    "paths",
    [
        [PILOT_PATH],
        [SCHEDULER_SIBLING_PATH],
        [PILOT_PATH, SCHEDULER_SIBLING_PATH],
    ],
)
def test_precedence_is_independent_of_rule_order(paths: list[str]) -> None:
    baseline = _select(_input(paths))
    count = len(RULES["focused_rules"])
    orders = [tuple(range(count))[offset:] + tuple(range(count))[:offset] for offset in range(count)]
    orders.append(tuple(reversed(range(count))))
    for order in orders:
        rules = copy.deepcopy(RULES)
        rules["focused_rules"] = [RULES["focused_rules"][index] for index in order]
        assert _select(_input(paths), rules) == baseline


@pytest.mark.parametrize("value", [True, False])
def test_boolean_approval_revision_is_rejected(value: bool) -> None:
    with pytest.raises(TypeError, match="approval_revision"):
        _subject(approval_revision=value)


@pytest.mark.parametrize("field", ["per_command_timeout_seconds", "total_validation_timeout_seconds"])
@pytest.mark.parametrize("value", [True, False])
def test_boolean_timeouts_are_rejected(field: str, value: bool) -> None:
    subject = _subject()
    valid = select_pre_pr_validation_plan(subject, RULES)
    values: dict[str, object] = {
        "selector_version": valid.selector_version,
        "subject": subject,
        "commands": valid.commands,
        "command_set_digest": valid.command_set_digest,
        "reason_codes": valid.reason_codes,
        field: value,
    }
    with pytest.raises(TypeError, match=field):
        PrePrValidationPlan(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False])
def test_boolean_issue_number_is_rejected(value: bool) -> None:
    with pytest.raises(TypeError, match="issue_number"):
        _subject(issue_number=value)


# --- Explicit command-coverage subsumption (#729) ------------------------------
ISSUE_ACCEPTANCE_COMMAND = "python -m pytest tests/agent_os_issue_acceptance"
ISSUE_ACCEPTANCE_PATH = "tests/agent_os_issue_acceptance/test_records.py"


def _coverage_rules(coverage: list[dict[str, object]]) -> dict[str, object]:
    rules = copy.deepcopy(RULES)
    rules["command_coverage"] = coverage
    return rules


def test_exact_only_narrow_selection_is_unaffected_by_coverage() -> None:
    plan = _select(_input([PILOT_PATH]))
    assert plan.profile == "focused"
    assert plan.commands == (PILOT_COMMAND,)
    assert plan.reason_codes == ("profile.focused-package",)


def test_broader_plus_narrower_suppresses_the_narrow_command() -> None:
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]))
    assert plan.profile == "focused"
    assert plan.commands == (SCHEDULER_PACKAGE_COMMAND,)
    assert PILOT_COMMAND not in plan.commands


def test_unrelated_commands_survive_suppression() -> None:
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH, ISSUE_ACCEPTANCE_PATH]))
    assert plan.profile == "focused"
    assert plan.commands == tuple(
        sorted((SCHEDULER_PACKAGE_COMMAND, ISSUE_ACCEPTANCE_COMMAND))
    )
    assert PILOT_COMMAND not in plan.commands


def test_duplicate_coverage_declaration_fails_closed() -> None:
    rules = _coverage_rules(
        [
            {"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [PILOT_COMMAND]},
            {"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [PILOT_COMMAND]},
        ]
    )
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_duplicate_subsumed_command_within_one_entry_fails_closed() -> None:
    rules = _coverage_rules(
        [
            {
                "broader": SCHEDULER_PACKAGE_COMMAND,
                "subsumes": [PILOT_COMMAND, PILOT_COMMAND],
            }
        ]
    )
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_unknown_broader_command_in_coverage_fails_closed() -> None:
    rules = _coverage_rules(
        [{"broader": "python -m pytest not/registered", "subsumes": [PILOT_COMMAND]}]
    )
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_unknown_subsumed_command_in_coverage_fails_closed() -> None:
    rules = _coverage_rules(
        [
            {
                "broader": SCHEDULER_PACKAGE_COMMAND,
                "subsumes": ["python -m pytest not/registered"],
            }
        ]
    )
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_self_subsumption_fails_closed() -> None:
    rules = _coverage_rules(
        [{"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [SCHEDULER_PACKAGE_COMMAND]}]
    )
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_cyclic_coverage_fails_closed() -> None:
    rules = _coverage_rules(
        [
            {"broader": ISSUE_ACCEPTANCE_COMMAND, "subsumes": [SCHEDULER_PACKAGE_COMMAND]},
            {"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [ISSUE_ACCEPTANCE_COMMAND]},
        ]
    )
    plan = _select(
        _input([ISSUE_ACCEPTANCE_PATH, SCHEDULER_SIBLING_PATH]), rules
    )
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_ambiguous_conflicting_coverage_fails_closed() -> None:
    rules = _coverage_rules(
        [
            {"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [PILOT_COMMAND]},
            {"broader": ISSUE_ACCEPTANCE_COMMAND, "subsumes": [PILOT_COMMAND]},
        ]
    )
    plan = _select(
        _input([PILOT_PATH, SCHEDULER_SIBLING_PATH, ISSUE_ACCEPTANCE_PATH]), rules
    )
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


@pytest.mark.parametrize(
    "coverage",
    [
        [{"broader": SCHEDULER_PACKAGE_COMMAND}],
        [{"subsumes": [PILOT_COMMAND]}],
        [{"broader": 1, "subsumes": [PILOT_COMMAND]}],
        [{"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": PILOT_COMMAND}],
        [{"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": []}],
        [{"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [1]}],
        "not-a-list",
    ],
)
def test_malformed_coverage_command_lists_fail_closed(coverage: object) -> None:
    rules = _coverage_rules(coverage)  # type: ignore[arg-type]
    plan = _select(_input([PILOT_PATH, SCHEDULER_SIBLING_PATH]), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_coverage_declaration_order_does_not_affect_suppression() -> None:
    paths = [PILOT_PATH, SCHEDULER_SIBLING_PATH]
    forward = _coverage_rules(
        [{"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [PILOT_COMMAND]}]
    )
    same_relationship_restated = _coverage_rules(
        [{"broader": SCHEDULER_PACKAGE_COMMAND, "subsumes": [PILOT_COMMAND]}]
    )
    assert _select(_input(paths), forward) == _select(
        _input(list(reversed(paths))), same_relationship_restated
    )


def test_coverage_suppression_serialization_digest_and_identity_are_deterministic() -> None:
    paths = [PILOT_PATH, SCHEDULER_SIBLING_PATH]
    first = _select(_input(paths))
    second = _select(_input(list(reversed(paths))))
    assert first == second
    assert serialize_validation_plan(first) == serialize_validation_plan(second)
    assert first.command_set_digest == compute_command_set_digest(
        first.selector_version, first.commands
    )
    assert validation_plan_id(first) == validation_plan_id(second)


def test_coverage_selection_performs_no_file_io(monkeypatch: pytest.MonkeyPatch) -> None:
    value = _input([PILOT_PATH, SCHEDULER_SIBLING_PATH])

    def fail_read(*args: object, **kwargs: object) -> str:
        raise AssertionError("coverage selection attempted file I/O")

    monkeypatch.setattr(Path, "read_text", fail_read)
    plan = select_validation_plan(value, RULES)
    assert plan.commands == (SCHEDULER_PACKAGE_COMMAND,)


def test_pre_pr_frozen_binding_is_not_auto_suppressed() -> None:
    """Pre-PR command identities stay exact; coverage never widens or narrows them."""
    subject = _subject()
    with pytest.raises(ValueError, match="command identity drift"):
        select_pre_pr_validation_plan(
            _subject(required_command_identities=(SCHEDULER_PACKAGE_COMMAND,)), RULES
        )
    # The originally bound narrow command remains exact and valid.
    plan = select_pre_pr_validation_plan(subject, RULES)
    assert plan.commands == (PILOT_COMMAND,)
