"""D07 Track A: focused selection for the 10 unmapped Python test dirs (G2/G3).

Fail-first coverage for the smallest legitimate mapping of the 10
``08_Tooling/*/tests`` directories (55 files) that the D05/D07 audit found
unmapped at main ``fd59a3cc``. Each directory gets one focused rule whose
prefix owns the whole directory (the same whole-directory-owner precedent as
``execution-service``, ``workflow-scheduler`` and ``navigation-registry``) and
one command of the existing form
``python -m pytest 08_Tooling/<dir>/tests`` -- the exact per-suite invocation
``scripts/validate-all.sh`` runs, minus the ``--cov`` aggregate-only flags.

Whole-directory ownership is load-bearing, not incidental: the #4030 class
(exec-service + memory-manager) includes a ``data/*.json`` file, which only a
whole-directory prefix covers. A ``src/``+``tests/``-only prefix would leave
the data file uncovered and the set would still fall through to aggregate.

Consequences pinned here on purpose:
- A docs-only change inside a newly owned directory (e.g. its README.md)
  selects that directory's focused suite, exactly as a README change inside
  the already-owned execution-service directory does. It never triggers the
  full aggregate suite.
- G1 ``workspace-automation-builder`` stays UNMAPPED by explicit decision:
  it has no Python tests (``.gs``/``.js`` only) and no focused Python command
  exists for it, so it still fails closed to ``manual-review`` /
  ``rule.ambiguous``. See TRACK_A_PREFLIGHT.md.
"""
from __future__ import annotations

import copy

import pytest

from agent_os_execution_service.command_planning import _COMMAND_REGISTRY
from scripts.agent_os_remote_validation import (
    SelectionInput,
    compute_command_set_digest,
    load_rule_map,
    select_validation_plan,
    validate_validation_plan,
)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
RULES = load_rule_map()

# (rule name, directory, representative production file, representative test file,
#  focused command, canonical single-command digest for selector 1.0.0)
D07_PYTHON_DIRS: tuple[tuple[str, str, str, str, str, str], ...] = (
    (
        "agent-memory-context-manager",
        "08_Tooling/agent-memory-context-manager",
        "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/lesson_retrieval_orchestrator.py",
        "08_Tooling/agent-memory-context-manager/tests/test_lesson_retrieval_orchestrator.py",
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests",
        "2a2e26f0e59a1395a1b3c110107e1ca72c44d9a12965b556dc58953d9288103b",
    ),
    (
        "dashboard-migration-verification",
        "08_Tooling/dashboard-migration-verification",
        "08_Tooling/dashboard-migration-verification/scripts/validate_changes.py",
        "08_Tooling/dashboard-migration-verification/tests/test_validate_changes.py",
        "python -m pytest 08_Tooling/dashboard-migration-verification/tests",
        "ec55b238ddc52b5cc8fc08a2760bc734bbf9374ae3e4074d568719386ad6132c",
    ),
    (
        "notion-compute-decision-writer",
        "08_Tooling/notion-compute-decision-writer",
        "08_Tooling/notion-compute-decision-writer/src/notion_compute_decision_writer/writer.py",
        "08_Tooling/notion-compute-decision-writer/tests/test_writer.py",
        "python -m pytest 08_Tooling/notion-compute-decision-writer/tests",
        "37a1477e26553e54597134e3f4d7a38bc726cf296b15e2dc43eb4d30ff04a68c",
    ),
    (
        "notion-operational-guidance-writer",
        "08_Tooling/notion-operational-guidance-writer",
        "08_Tooling/notion-operational-guidance-writer/src/notion_operational_guidance_writer/writer.py",
        "08_Tooling/notion-operational-guidance-writer/tests/test_writer.py",
        "python -m pytest 08_Tooling/notion-operational-guidance-writer/tests",
        "11470e1584f7e3dbb82abb54871ef6e7d6789cd09ce07101e1d2d8e3ad1ee4e2",
    ),
    (
        "reusable-capability-registry",
        "08_Tooling/reusable-capability-registry",
        "08_Tooling/reusable-capability-registry/src/reusable_capability_registry/discovery.py",
        "08_Tooling/reusable-capability-registry/tests/test_discovery.py",
        "python -m pytest 08_Tooling/reusable-capability-registry/tests",
        "4004d1815590533d8b605c8f1d4f63b677e0c01c0b27e2b7abdf9ae04bf2a625",
    ),
    (
        "visual-asset-drive-writer",
        "08_Tooling/visual-asset-drive-writer",
        "08_Tooling/visual-asset-drive-writer/src/visual_asset_drive_writer/writer.py",
        "08_Tooling/visual-asset-drive-writer/tests/test_writer.py",
        "python -m pytest 08_Tooling/visual-asset-drive-writer/tests",
        "28573785d7f88a3aa5a5ca7c28d99d6ecc051ab9b9da7b7c378cd8f54a22816b",
    ),
    (
        "visual-asset-ingestion-coordinator",
        "08_Tooling/visual-asset-ingestion-coordinator",
        "08_Tooling/visual-asset-ingestion-coordinator/src/visual_asset_ingestion_coordinator/coordinator.py",
        "08_Tooling/visual-asset-ingestion-coordinator/tests/test_coordinator.py",
        "python -m pytest 08_Tooling/visual-asset-ingestion-coordinator/tests",
        "4dfc6c34019c6192d2abe4002c487767760a8cef4ce709244f1027a205dad811",
    ),
    (
        "visual-asset-intake",
        "08_Tooling/visual-asset-intake",
        "08_Tooling/visual-asset-intake/src/visual_asset_intake/intake.py",
        "08_Tooling/visual-asset-intake/tests/test_intake.py",
        "python -m pytest 08_Tooling/visual-asset-intake/tests",
        "92e3839a8d8d2d4db9c1db22c45cddc5607a2cb081df06fffde5dcf49897e7ba",
    ),
    (
        "visual-asset-notion-writer",
        "08_Tooling/visual-asset-notion-writer",
        "08_Tooling/visual-asset-notion-writer/src/visual_asset_notion_writer/writer.py",
        "08_Tooling/visual-asset-notion-writer/tests/test_writer.py",
        "python -m pytest 08_Tooling/visual-asset-notion-writer/tests",
        "ae4952931d41d154a9f9e9a9c96ab9d745ad696ed77800b118c73c423b68e9c3",
    ),
    (
        "visual-asset-routing",
        "08_Tooling/visual-asset-routing",
        "08_Tooling/visual-asset-routing/src/visual_asset_routing/routing.py",
        "08_Tooling/visual-asset-routing/tests/test_routing.py",
        "python -m pytest 08_Tooling/visual-asset-routing/tests",
        "fb714a6ced836838fe070790d024b5ab945c9533eba685aa597128f4b679af6a",
    ),
)

EXECUTION_SERVICE_COMMAND = "python -m pytest 08_Tooling/agent-os-execution-service/tests"
PR4030_CLASS_FILES = (
    "08_Tooling/agent-memory-context-manager/data/lesson_applicability.v1.json",
    "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/lesson_applicability.py",
    "08_Tooling/agent-memory-context-manager/src/agent_memory_context_manager/notion_learning_projection.py",
    "08_Tooling/agent-memory-context-manager/tests/test_lesson_applicability.py",
    "08_Tooling/agent-memory-context-manager/tests/test_lesson_applicability_invariance.py",
    "08_Tooling/agent-os-execution-service/src/agent_os_execution_service/lesson_learning_loop.py",
    "08_Tooling/agent-os-execution-service/tests/test_lesson_applicability_hints.py",
)
PR4030_CLASS_DIGEST = "586d20b352b4d60f1ba77e9e5409f26b1e08e3004301720d82eb16a25e0359d0"
AMCM_ROUTING_UNION_DIGEST = "bc68f53cadbcbaf4f17ec6c571cbb904ec0ef1d1c65ab4a953f7a7ecb472df7b"
ALL_TEN_UNION_DIGEST = "0ad218224ed89da45ee2c87f266f088c02b014ea7ba37e273d913fd6e0383e76"


def _input(paths: list[str] | tuple[str, ...]) -> SelectionInput:
    return SelectionInput(
        repository="Blummer92/agent-os",
        pull_request=4030,
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        changed_files=tuple(paths),
    )


def _assert_focused_single(
    paths: list[str] | tuple[str, ...], command: str, digest: str
) -> None:
    plan = select_validation_plan(_input(paths), RULES)
    assert plan.profile == "focused"
    assert plan.commands == (command,)
    assert plan.reason_codes == ("profile.focused-package",)
    assert plan.command_set_digest == digest
    assert plan.command_set_digest == compute_command_set_digest(
        "1.0.0", (command,)
    )
    assert plan.remote_build_required is True
    assert validate_validation_plan(plan) == ()


@pytest.mark.parametrize(
    "rule_name,directory,source_file,test_file,command,digest",
    D07_PYTHON_DIRS,
    ids=[row[0] for row in D07_PYTHON_DIRS],
)
def test_d07_production_only_change_selects_focused_suite(
    rule_name: str,
    directory: str,
    source_file: str,
    test_file: str,
    command: str,
    digest: str,
) -> None:
    _assert_focused_single([source_file], command, digest)


@pytest.mark.parametrize(
    "rule_name,directory,source_file,test_file,command,digest",
    D07_PYTHON_DIRS,
    ids=[row[0] for row in D07_PYTHON_DIRS],
)
def test_d07_test_only_change_selects_focused_suite(
    rule_name: str,
    directory: str,
    source_file: str,
    test_file: str,
    command: str,
    digest: str,
) -> None:
    _assert_focused_single([test_file], command, digest)


@pytest.mark.parametrize(
    "rule_name,directory,source_file,test_file,command,digest",
    D07_PYTHON_DIRS,
    ids=[row[0] for row in D07_PYTHON_DIRS],
)
def test_d07_mixed_production_and_test_change_selects_one_focused_suite(
    rule_name: str,
    directory: str,
    source_file: str,
    test_file: str,
    command: str,
    digest: str,
) -> None:
    _assert_focused_single([source_file, test_file], command, digest)


@pytest.mark.parametrize(
    "rule_name,directory,source_file,test_file,command,digest",
    D07_PYTHON_DIRS,
    ids=[row[0] for row in D07_PYTHON_DIRS],
)
def test_d07_directory_pyproject_change_selects_focused_suite_not_aggregate(
    rule_name: str,
    directory: str,
    source_file: str,
    test_file: str,
    command: str,
    digest: str,
) -> None:
    # A per-directory pyproject.toml is NOT the root aggregate path
    # ``pyproject.toml``; the owning directory's focused rule covers it.
    _assert_focused_single([f"{directory}/pyproject.toml"], command, digest)


def test_d07_memory_manager_data_file_selects_focused_suite() -> None:
    _assert_focused_single(
        ["08_Tooling/agent-memory-context-manager/data/lesson_applicability.v1.json"],
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests",
        "2a2e26f0e59a1395a1b3c110107e1ca72c44d9a12965b556dc58953d9288103b",
    )


def test_d07_pr4030_class_selects_both_focused_suites_as_union() -> None:
    plan = select_validation_plan(_input(PR4030_CLASS_FILES), RULES)
    assert plan.profile == "focused"
    assert plan.commands == (
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests",
        EXECUTION_SERVICE_COMMAND,
    )
    assert plan.reason_codes == ("profile.focused-union",)
    assert plan.command_set_digest == PR4030_CLASS_DIGEST
    assert plan.command_set_digest == compute_command_set_digest(
        "1.0.0", plan.commands
    )
    assert validate_validation_plan(plan) == ()


def test_d07_two_new_directories_select_focused_union() -> None:
    plan = select_validation_plan(
        _input(
            [
                "08_Tooling/agent-memory-context-manager/tests/test_lesson_retrieval_orchestrator.py",
                "08_Tooling/visual-asset-routing/tests/test_routing.py",
            ]
        ),
        RULES,
    )
    assert plan.profile == "focused"
    assert plan.commands == (
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests",
        "python -m pytest 08_Tooling/visual-asset-routing/tests",
    )
    assert plan.reason_codes == ("profile.focused-union",)
    assert plan.command_set_digest == AMCM_ROUTING_UNION_DIGEST
    assert validate_validation_plan(plan) == ()


def test_d07_all_ten_directories_select_focused_union() -> None:
    paths = [row[3] for row in D07_PYTHON_DIRS]
    plan = select_validation_plan(_input(paths), RULES)
    assert plan.profile == "focused"
    assert plan.commands == tuple(sorted(row[4] for row in D07_PYTHON_DIRS))
    assert plan.reason_codes == ("profile.focused-union",)
    assert plan.command_set_digest == ALL_TEN_UNION_DIGEST
    assert validate_validation_plan(plan) == ()


def test_d07_new_rules_are_registered_in_the_command_registry() -> None:
    for _rule_name, _directory, _source, _test, command, _digest in D07_PYTHON_DIRS:
        argv = _COMMAND_REGISTRY.get(command)
        assert argv == ("python", "-m", "pytest", command.split("pytest ", 1)[1]), command


def test_d07_docs_only_change_inside_owned_directory_runs_that_focused_suite() -> None:
    # Whole-directory ownership (the execution-service precedent): a README
    # change inside an owned directory runs that directory's focused suite,
    # never the full aggregate suite.
    _assert_focused_single(
        ["08_Tooling/agent-memory-context-manager/README.md"],
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests",
        "2a2e26f0e59a1395a1b3c110107e1ca72c44d9a12965b556dc58953d9288103b",
    )


def test_d07_focused_change_does_not_pull_in_unrelated_suites() -> None:
    plan = select_validation_plan(
        _input(
            ["08_Tooling/agent-memory-context-manager/tests/test_lesson_retrieval_orchestrator.py"]
        ),
        RULES,
    )
    assert plan.commands == (
        "python -m pytest 08_Tooling/agent-memory-context-manager/tests",
    )
    assert EXECUTION_SERVICE_COMMAND not in plan.commands
    assert plan.commands != ("python -m pytest",)


def test_d07_aggregate_path_still_dominates_focused_change() -> None:
    plan = select_validation_plan(
        _input(
            [
                "08_Tooling/agent-memory-context-manager/tests/test_lesson_retrieval_orchestrator.py",
                "pyproject.toml",
            ]
        ),
        RULES,
    )
    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-configuration",)


def test_d07_unrelated_python_change_still_selects_aggregate() -> None:
    plan = select_validation_plan(_input(["scripts/agent_os_aggregate_gate.py"]), RULES)
    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_d07_docs_only_change_outside_owned_directories_stays_static() -> None:
    plan = select_validation_plan(_input(["docs/3486-ready-pr-validation-recovery.md"]), RULES)
    assert plan.profile == "static"
    assert plan.commands == ()
    assert plan.reason_codes == ("profile.documentation-static",)


def test_d07_workspace_automation_builder_still_fails_closed() -> None:
    # G1 is an explicit separate decision: no Python tests, no focused
    # Python command, so .gs/.js changes stay manual-review.
    for path in (
        "08_Tooling/workspace-automation-builder/apps-script/AppsScriptSyncSafetyBridge.gs",
        "08_Tooling/workspace-automation-builder/tests/validate-fixtures.test.js",
    ):
        plan = select_validation_plan(_input([path]), RULES)
        assert plan.profile == "manual-review"
        assert plan.commands == ()
        assert plan.command_set_digest == "unavailable"
        assert plan.reason_codes == ("rule.ambiguous",)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rule: rule.update({"commands": [""]}),
        lambda rule: rule.update({"commands": [123]}),
        lambda rule: rule.update({"prefixes": [], "exact_paths": []}),
        lambda rule: rule.update({"name": ""}),
    ],
    ids=["empty-command-string", "non-string-command", "no-owner", "empty-name"],
)
def test_d07_malformed_new_rule_fails_closed(mutation) -> None:
    rules = copy.deepcopy(RULES)
    target = next(
        rule for rule in rules["focused_rules"] if rule["name"] == "visual-asset-routing"
    )
    mutation(target)
    plan = select_validation_plan(
        _input(["08_Tooling/visual-asset-routing/tests/test_routing.py"]), rules
    )
    assert plan.profile == "manual-review"
    assert plan.commands == ()
    assert plan.command_set_digest == "unavailable"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_d07_empty_commands_list_degrades_to_aggregate_not_focused() -> None:
    # Pre-existing selector edge, NOT introduced by Track A: an empty commands
    # list passes _valid_focused_rule_map (vacuous truth on the string list),
    # so the path falls through to the aggregate fallback and the FULL suite
    # runs. That is fail-safe in the only sense that matters here -- it can
    # never claim a focused pass for a suite that did not run -- but it is
    # not manual-review. Track A does not tighten the shared validator (it
    # also gates pre-PR planning); the behavior is pinned here so any future
    # tightening is a deliberate, reviewed change. See TRACK_A_PREFLIGHT.md.
    rules = copy.deepcopy(RULES)
    target = next(
        rule for rule in rules["focused_rules"] if rule["name"] == "visual-asset-routing"
    )
    target["commands"] = []
    plan = select_validation_plan(
        _input(["08_Tooling/visual-asset-routing/tests/test_routing.py"]), rules
    )
    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-unmapped-executable",)


def test_d07_coverage_entry_referencing_unregistered_command_fails_closed() -> None:
    rules = copy.deepcopy(RULES)
    rules["command_coverage"] = [
        {
            "broader": "python -m pytest 08_Tooling/visual-asset-routing/tests",
            "subsumes": ["python -m pytest tests/not-registered.py"],
        }
    ]
    plan = select_validation_plan(
        _input(["08_Tooling/visual-asset-routing/tests/test_routing.py"]), rules
    )
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)
