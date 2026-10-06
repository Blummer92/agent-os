from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "agent-os-shadow-navigation.yml"
ACTION = REPO_ROOT / ".github" / "actions" / "agent-os-shadow-navigation" / "action.yml"


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return yaml.load(stream, Loader=yaml.BaseLoader)


def test_shadow_navigation_workflow_is_manual_and_read_only():
    document = _load_yaml(WORKFLOW)

    assert "workflow_dispatch" in document["on"]
    assert document["permissions"] == {
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
    }


def test_shadow_navigation_action_wraps_existing_shadow_runner():
    document = _load_yaml(ACTION)
    steps = document["runs"]["steps"]
    run_body = "\n".join(step.get("run", "") for step in steps)

    assert "python scripts/agent-os-shadow-run.py" in run_body
    assert "--campaign-id" in run_body
    assert "--output" in run_body
    assert "gh issue edit" not in run_body
    assert "gh pr edit" not in run_body
    assert "curl -X POST" not in run_body
    assert "curl -X PATCH" not in run_body
    assert "curl -X DELETE" not in run_body
