"""#3751 regression: Apps Script placement-transport conformance must be selected.

Issue #3751 recorded that a change under
``08_Tooling/instructional-materials-coach/apps-script/`` had no focused rule,
so the governed validation selector could never choose an executable Node
conformance route: ``.gs`` files are neither documentation nor executable
suffixes, so the selection fell to ``manual-review`` (fail closed) instead of
running the transport's Node conformance suite.

These tests pin the repaired contract end to end:

- an ``apps-script/`` runtime (``.gs``) or conformance (``.mjs``) change selects
  a focused plan whose exact command is the Node conformance suite, bound to
  the pull-request head SHA;
- the selected command resolves inside the bounded CI executor (no shell), so
  selection can never outpace executability;
- the bounded executor refuses to execute a plan whose head SHA does not match
  the expected PR head, so execution evidence stays head-bound;
- removing the route must not silently pass: without the rule the same change
  falls back to ``manual-review``, which the validation workflow fails closed
  on, instead of producing a green focused or static plan.
"""
from __future__ import annotations

import copy
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
)

ROOT = Path(__file__).resolve().parents[2]
RULES = load_rule_map()

BASE_SHA = "9902344a309c0b8e52a5d4c80cb9cd29d85882ca"
HEAD_SHA = "f1c2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0"

APPS_SCRIPT_RULE_NAME = "apps-script-conformance"
TRANSPORT_GS = "08_Tooling/instructional-materials-coach/apps-script/VisualPlacementTransport.gs"
CONFORMANCE_MJS = (
    "08_Tooling/instructional-materials-coach/apps-script/test/"
    "visual-placement-transport.conformance.test.mjs"
)
NODE_CONFORMANCE_COMMAND = (
    "cd 08_Tooling/instructional-materials-coach && node --test "
    "apps-script/test/visual-placement-transport.conformance.test.mjs"
)


def _ci_executor():
    module_path = ROOT / "scripts/agent_os_ci_validation.py"
    spec = importlib.util.spec_from_file_location("agent_os_ci_validation", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan(*paths: str, rules=RULES):
    return select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=3751,
            base_sha=BASE_SHA,
            head_sha=HEAD_SHA,
            changed_files=tuple(paths),
        ),
        rules,
    )


def test_transport_runtime_change_selects_the_node_conformance_command():
    plan = _plan(TRANSPORT_GS)
    assert plan.profile == "focused"
    assert plan.commands == (NODE_CONFORMANCE_COMMAND,)
    assert plan.head_sha == HEAD_SHA


def test_conformance_file_change_selects_the_node_conformance_command():
    plan = _plan(CONFORMANCE_MJS)
    assert plan.profile == "focused"
    assert plan.commands == (NODE_CONFORMANCE_COMMAND,)


def test_apps_script_change_unions_with_the_coach_python_rule():
    plan = _plan(
        TRANSPORT_GS,
        "08_Tooling/instructional-materials-coach/src/instructional_materials_coach/lesson_content_result.py",
    )
    assert plan.profile == "focused"
    assert NODE_CONFORMANCE_COMMAND in plan.commands
    assert "python -m pytest 08_Tooling/instructional-materials-coach/tests" in plan.commands


def test_missing_route_fails_closed_on_apps_script_changes():
    rules_without_route = copy.deepcopy(RULES)
    rules_without_route["focused_rules"] = [
        rule
        for rule in rules_without_route["focused_rules"]
        if rule["name"] != APPS_SCRIPT_RULE_NAME
    ]
    plan = _plan(TRANSPORT_GS, rules=rules_without_route)
    assert plan.profile == "manual-review"
    assert NODE_CONFORMANCE_COMMAND not in plan.commands


def test_selected_command_resolves_in_the_bounded_ci_executor():
    module = _ci_executor()
    argv, cwd = module._resolve_command(NODE_CONFORMANCE_COMMAND)
    assert argv == (
        "node",
        "--test",
        "apps-script/test/visual-placement-transport.conformance.test.mjs",
    )
    assert cwd == ROOT / "08_Tooling/instructional-materials-coach"


def test_bounded_executor_keeps_execution_evidence_head_bound():
    module = _ci_executor()
    plan = _plan(TRANSPORT_GS)
    with pytest.raises(ValueError, match="validation plan head does not match expected PR head"):
        module.execute_focused(plan, expected_head_sha="0" * 40)


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime is unavailable")
def test_selected_node_conformance_route_executes_green():
    result = subprocess.run(
        ("node", "--test", "apps-script/test/visual-placement-transport.conformance.test.mjs"),
        cwd=ROOT / "08_Tooling/instructional-materials-coach",
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
