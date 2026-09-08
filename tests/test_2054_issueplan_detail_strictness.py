from pathlib import Path


def test_issueplan_current_state_does_not_stringify_detail_items():
    source = Path("scripts/agent_os_issue_acceptance/issueplan_current_state.py").read_text(encoding="utf-8")
    assert 'tuple(str(item) for item in self.details)' not in source
