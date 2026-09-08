from pathlib import Path


def test_single_issue_pilot_does_not_stringify_non_string_bounded_items():
    source = Path("08_Tooling/workflow-scheduler/src/workflow_scheduler/execution/single_issue_pilot.py").read_text(encoding="utf-8")
    assert 'tuple(str(item) for item in values)' not in source
