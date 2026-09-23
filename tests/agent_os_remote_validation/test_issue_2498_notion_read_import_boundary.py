import importlib.util
import os
from pathlib import Path

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
    validate_validation_plan,
)

ROOT = Path(__file__).resolve().parents[2]


def test_notion_read_focused_profile_keeps_bounded_executor_command() -> None:
    plan = select_validation_plan(
        SelectionInput(
            repository="Blummer92/agent-os",
            pull_request=2497,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=(
                "scripts/agent_os_notion_read_request/notion_read_catalog.json",
            ),
        ),
        load_rule_map(),
    )

    assert plan.profile == "focused"
    assert plan.commands == (
        "python -m pytest tests/agent_os_notion_read_request",
    )
    assert plan.reason_codes == ("profile.focused-package",)
    assert validate_validation_plan(plan) == ()


def _load_ci_validation():
    spec = importlib.util.spec_from_file_location(
        "agent_os_ci_validation_2498", ROOT / "scripts" / "agent_os_ci_validation.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bounded_executor_supplies_root_src_import_path() -> None:
    """Root-scoped bounded commands resolve ``src`` exactly like validate-all.sh.

    ``navigation_registry`` is supplied by the executor's import path rather than a
    bare ``-e .`` editable, which the frozen dependency-source contract rejects as
    an unsupported source indirection.
    """
    module = _load_ci_validation()
    root_env = module._command_env(module.ROOT)
    assert root_env["PYTHONPATH"].split(os.pathsep)[0] == str(module.ROOT / "src")


def test_bounded_executor_leaves_non_root_commands_unchanged() -> None:
    module = _load_ci_validation()
    capture_dir = module.ROOT / "08_Tooling/instructional-materials-coach/capture"
    assert module._command_env(capture_dir).get("PYTHONPATH") == os.environ.get(
        "PYTHONPATH"
    )


def test_dev_requirements_keep_declared_src_editable_only() -> None:
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8").splitlines()
    assert "-e ./src" in requirements
    assert "-e ." not in requirements
