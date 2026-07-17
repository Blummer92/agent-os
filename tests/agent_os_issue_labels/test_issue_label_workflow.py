from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-issue-label-report.yml"


def test_report_only_workflow_exists_and_calls_checker():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "issues:" in content
    assert "workflow_dispatch:" in content
    assert "contents: read" in content
    assert "issues: read" in content
    assert "python -m scripts.agent_os_issue_labels.cli" in content
    assert "GITHUB_STEP_SUMMARY" in content


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
