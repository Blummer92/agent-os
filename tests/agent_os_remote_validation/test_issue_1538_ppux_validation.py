from __future__ import annotations

from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
PPUX = "08_Tooling/instructional-materials-coach/picture-perfect-coach/"
PY_COACH = "08_Tooling/instructional-materials-coach/"
PPUX_COMMAND = f"cd {PPUX.rstrip('/')} && npm run check"
PY_COMMAND = "python -m pytest 08_Tooling/instructional-materials-coach/tests"


def _select(paths: list[str]):
    return select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=1538,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            changed_files=tuple(paths),
        ),
        load_rule_map(),
    )


def test_ppux_ts_source_selects_typescript_validation() -> None:
    plan = _select([PPUX + "src/App.tsx"])
    assert plan.profile == "focused"
    assert plan.commands == (PPUX_COMMAND,)
    assert plan.head_sha == HEAD_SHA
    assert plan.execution_authorized is False
    assert plan.side_effects_performed is False


def test_ppux_test_selects_typescript_validation() -> None:
    plan = _select([PPUX + "src/App.test.tsx"])
    assert plan.commands == (PPUX_COMMAND,)


def test_ppux_package_and_guard_changes_select_typescript_validation() -> None:
    for path in (PPUX + "package.json", PPUX + "scripts/guard-boundaries.mjs"):
        assert _select([path]).commands == (PPUX_COMMAND,)


def test_unrelated_instructional_materials_python_change_stays_python_only() -> None:
    plan = _select([PY_COACH + "src/instructional_materials_coach/cli.py"])
    assert plan.profile == "focused"
    assert plan.commands == (PY_COMMAND,)
    assert PPUX_COMMAND not in plan.commands


def test_mixed_ppux_and_python_change_preserves_both_validation_families() -> None:
    plan = _select(
        [
            PPUX + "src/App.tsx",
            PY_COACH + "src/instructional_materials_coach/cli.py",
        ]
    )
    assert plan.profile == "focused"
    assert plan.commands == tuple(sorted((PPUX_COMMAND, PY_COMMAND)))
    assert plan.reason_codes == ("profile.focused-union",)


def test_new_source_sha_changes_exact_head_identity() -> None:
    first = _select([PPUX + "src/App.tsx"])
    second = select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=1538,
            base_sha=BASE_SHA,
            head_sha="c" * 40,
            changed_files=(PPUX + "src/App.tsx",),
        ),
        load_rule_map(),
    )
    assert first.head_sha != second.head_sha
    assert first.command_set_digest == second.command_set_digest


def test_ppux_readme_change_remains_in_ppux_lane() -> None:
    plan = _select([PPUX + "README.md"])
    assert plan.commands == (PPUX_COMMAND,)
