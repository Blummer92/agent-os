import copy

from scripts.agent_os_remote_validation import SelectionInput, load_rule_map, select_validation_plan


def _input():
    return SelectionInput(repository="Blummer92/agent-os", pull_request=1, base_sha="a"*40, head_sha="b"*40, changed_files=("tests/agent_os_issue_acceptance/test_records.py",))


def test_empty_focused_command_fails_closed_at_rule_boundary():
    rules = copy.deepcopy(load_rule_map())
    rules["focused_rules"][0]["commands"] = [""]
    plan = select_validation_plan(_input(), rules)
    assert plan.profile == "manual-review"
    assert plan.reason_codes == ("rule.ambiguous",)


def test_empty_rule_name_fails_closed_at_rule_boundary():
    rules = copy.deepcopy(load_rule_map())
    rules["focused_rules"][0]["name"] = ""
    plan = select_validation_plan(_input(), rules)
    assert plan.profile == "manual-review"
