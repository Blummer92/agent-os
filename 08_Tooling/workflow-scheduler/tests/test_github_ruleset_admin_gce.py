from __future__ import annotations

import pytest

from workflow_scheduler.governance.github_ruleset_admin_gce import ACTION, build_task, execute


class Adapter:
    def __init__(self):
        self.tasks = []

    def execute(self, task):
        self.tasks.append(task)
        return {"status": "success", "message": "ok", "output": {"mutation_attempted": True}}


def test_build_task_fixes_every_authorized_identity_except_fresh_prestate() -> None:
    digest = "a" * 64
    task = build_task(digest)
    assert task.type == "github_ruleset_admin"
    assert task.owner == "GitHub Service Agent"
    assert task.action == ACTION
    assert task.idempotency_key == "gh-admin1-1883"
    assert task.payload == {
        "action": ACTION,
        "repository_full_name": "Blummer92/agent-os",
        "ruleset_id": 19123362,
        "authorization_issue": 1883,
        "expected_prestate_sha256": digest,
    }


@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "a" * 65, "g" * 64, "a" * 63 + ";"])
def test_build_task_rejects_noncanonical_prestate(value: str) -> None:
    with pytest.raises(ValueError, match="64 lowercase hex"):
        build_task(value)


def test_execute_invokes_existing_adapter_exactly_once() -> None:
    adapter = Adapter()
    result = execute("b" * 64, adapter=adapter)
    assert result["status"] == "success"
    assert len(adapter.tasks) == 1
    assert adapter.tasks[0].payload["expected_prestate_sha256"] == "b" * 64
