from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-issue-label-apply-dry-run.yml"


def test_dry_run_workflow_has_expected_read_only_triggers_and_inputs():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "types: [opened, edited, reopened]" in content
    assert "workflow_dispatch:" in content
    assert "issue_number:" in content
    assert "required: true" in content
    assert "labeled" not in content
    assert "unlabeled" not in content


def test_dry_run_workflow_uses_minimal_permissions_and_per_issue_concurrency():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "contents: read" in content
    assert "issues: read" in content
    assert "issues: write" not in content
    assert "agent-os-issue-label-dry-run-${{" in content
    assert "cancel-in-progress: true" in content


def test_dry_run_workflow_uses_shared_environment_after_checkout():
    content = WORKFLOW.read_text(encoding="utf-8")
    checkout = content.index("uses: actions/checkout@v4")
    shared_setup = content.index("uses: ./.github/actions/setup-python-dev")
    assert checkout < shared_setup
    assert "uses: actions/setup-python@v5" not in content
    assert "python -m pip install -r requirements-dev.txt" not in content


def test_dry_run_workflow_uses_fixture_testable_payload_resolver():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m scripts.agent_os_issue_labels.workflow_payload" in content
    assert "--event-name" in content
    assert "--event-path" in content
    assert "--manual-issue-number" in content
    assert "steps.resolve.outputs.status == 'pass'" in content
    assert "steps.resolve.outputs.status != 'pass'" in content
    assert "payload-summary.txt" in content


def test_dry_run_workflow_refetches_issue_and_repository_labels():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "github.rest.issues.get" in content
    assert "github.rest.issues.listLabelsForRepo" in content
    assert "RESOLVED_ISSUE_NUMBER" in content
    assert "context.payload.issue" not in content


def test_dry_run_workflow_calls_planner_and_publishes_audit_summary():
    content = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m scripts.agent_os_issue_labels.plan_cli" in content
    assert "--available-labels" in content
    assert "--issue-number" in content
    assert "--event-type" in content
    assert "--commit-sha" in content
    assert "GITHUB_STEP_SUMMARY" in content


def test_dry_run_workflow_contains_no_label_mutation_path():
    content = WORKFLOW.read_text(encoding="utf-8")
    forbidden = [
        "addLabels",
        "removeLabel",
        "setLabels",
        "gh issue edit",
        "issues: write",
        "add-label",
        "remove-label",
        "set-label",
    ]
    for pattern in forbidden:
        assert pattern not in content
