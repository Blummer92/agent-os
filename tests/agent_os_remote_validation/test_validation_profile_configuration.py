from pathlib import Path

from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan


ROOT = Path(__file__).resolve().parents[2]
RULES = load_rule_map()


def _input(path: str) -> SelectionInput:
    return SelectionInput(
        repository="Blummer92/agent-os",
        pull_request=1271,
        base_sha="a" * 40,
        head_sha="b" * 40,
        changed_files=(path,),
    )


def test_every_declared_aggregate_path_exists_in_repository() -> None:
    for path in RULES["aggregate_paths"]:
        assert (ROOT / path).is_file(), f"aggregate path does not exist: {path}"


def test_requirements_dev_selects_aggregate_without_changing_aggregate_identity() -> None:
    plan = select_validation_plan(_input("requirements-dev.txt"), RULES)

    assert plan.profile == "aggregate"
    assert plan.commands == ("python -m pytest",)
    assert plan.reason_codes == ("profile.aggregate-configuration",)
