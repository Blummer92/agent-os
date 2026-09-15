from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
    validate_validation_plan,
)


def test_notion_read_focused_profile_preserves_root_import_boundary() -> None:
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
        "PYTHONPATH=src:. python -m pytest tests/agent_os_notion_read_request",
    )
    assert plan.reason_codes == ("profile.focused-package",)
    assert validate_validation_plan(plan) == ()
