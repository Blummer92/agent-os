from pathlib import Path


def test_repository_state_evidence_does_not_stringify_detail_items():
    source = Path("scripts/agent_os_execution_capabilities/models.py").read_text(encoding="utf-8")
    assert 'tuple(str(item) for item in self.details)' not in source
