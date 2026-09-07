import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-issue-label-report.yml"

_EXPRESSION = re.compile(r"\$\{\{(.+?)\}\}")


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML 1.1 resolves a bare `on:` key to the boolean True.
    return workflow.get("on", workflow.get(True))


def _lookup(context: dict, path: str):
    value = context
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _resolve(term: str, context: dict):
    term = term.strip()
    if term.startswith("'") and term.endswith("'"):
        return term[1:-1]
    return _lookup(context, term)


def _evaluate(expression: str, context: dict):
    """Evaluate the bounded GitHub expression forms this workflow uses.

    Supports `a || b` fallback chains and a single `x == 'y'` comparison, which is
    exactly what the concurrency contract relies on.
    """
    if "==" in expression:
        left, right = expression.split("==", 1)
        return _resolve(left, context) == _resolve(right, context)
    for term in expression.split("||"):
        resolved = _resolve(term, context)
        if resolved not in (None, "", False):
            return resolved
    return None


def _render(template: str, context: dict) -> str:
    return _EXPRESSION.sub(
        lambda match: str(_evaluate(match.group(1), context)), template
    )


def _issue_event(issue_number: int, run_id: int) -> dict:
    return {
        "github": {
            "event_name": "issues",
            "event": {"issue": {"number": issue_number}},
            "run_id": run_id,
        }
    }


def _dispatch_event(run_id: int) -> dict:
    return {
        "github": {"event_name": "workflow_dispatch", "event": {}, "run_id": run_id}
    }


def _group_for(context: dict) -> str:
    return _render(str(_load_workflow()["concurrency"]["group"]), context)


def _cancels_for(context: dict) -> bool:
    rendered = _render(
        str(_load_workflow()["concurrency"]["cancel-in-progress"]), context
    )
    return rendered == "True"


def test_report_only_workflow_exists_and_calls_checker():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "issues:" in content
    assert "workflow_dispatch:" in content
    assert "contents: read" in content
    assert "issues: read" in content
    assert "python -m scripts.agent_os_issue_labels.cli" in content
    assert "GITHUB_STEP_SUMMARY" in content


def test_report_only_workflow_uses_shared_environment_after_checkout():
    content = WORKFLOW.read_text(encoding="utf-8")
    checkout = content.index("uses: actions/checkout@v7")
    shared_setup = content.index("uses: ./.github/actions/setup-python-dev")
    assert checkout < shared_setup
    assert "uses: actions/setup-python@v6" not in content
    assert "python -m pip install -r requirements-dev.txt" not in content


def test_report_only_workflow_declares_same_issue_supersession_guard():
    concurrency = _load_workflow()["concurrency"]
    assert "agent-os-issue-label-report-" in str(concurrency["group"])
    assert "github.event.issue.number" in str(concurrency["group"])
    assert "github.run_id" in str(concurrency["group"])
    assert "github.event_name == 'issues'" in str(concurrency["cancel-in-progress"])


def test_successive_same_issue_events_share_one_supersession_lineage():
    opened = _group_for(_issue_event(2014, run_id=34079764741))
    labeled = _group_for(_issue_event(2014, run_id=34079765476))
    assert opened == labeled == "agent-os-issue-label-report-issues-2014"
    assert _cancels_for(_issue_event(2014, run_id=34079765476)) is True


def test_distinct_issues_never_cancel_each_other():
    assert _group_for(_issue_event(2014, run_id=1)) != _group_for(
        _issue_event(2018, run_id=2)
    )


def test_manual_dispatch_runs_never_collapse_one_another():
    first = _dispatch_event(run_id=101)
    second = _dispatch_event(run_id=102)
    assert _group_for(first) != _group_for(second)
    assert _group_for(first) == "agent-os-issue-label-report-workflow_dispatch-101"
    assert _cancels_for(first) is False


def test_manual_dispatch_never_shares_a_group_with_issue_event_runs():
    assert _group_for(_dispatch_event(run_id=2014)) != _group_for(
        _issue_event(2014, run_id=999)
    )


def test_supersession_guard_preserves_trigger_coverage():
    triggers = _triggers(_load_workflow())
    assert triggers["issues"]["types"] == [
        "opened",
        "edited",
        "reopened",
        "labeled",
        "unlabeled",
    ]
    assert "workflow_dispatch" in triggers


def test_report_only_workflow_has_no_label_mutation_paths():
    content = WORKFLOW.read_text(encoding="utf-8")
    forbidden = [
        "issues: write",
        "pull-requests: write",
        "gh issue edit",
        "gh pr edit",
        "add-label",
        "remove-label",
        "set-label",
        "github.rest.issues.addLabels",
        "github.rest.issues.removeLabel",
        "github.rest.issues.setLabels",
    ]
    for pattern in forbidden:
        assert pattern not in content
