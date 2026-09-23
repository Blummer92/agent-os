from pathlib import Path


def test_projection_consumer_does_not_stringify_detail_items():
    source = Path("08_Tooling/workflow-scheduler/src/workflow_scheduler/planning/projection_consumer.py").read_text(encoding="utf-8")
    assert 'tuple(str(item) for item in self.details)' not in source
