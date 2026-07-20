from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-issue-acceptance-report.yml"


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_report_only_acceptance_workflow_exists_and_calls_checker():
    content = _content()

    assert "Agent OS Issue Acceptance Report" in content
    assert "pull_request:" in content
    assert "workflow_dispatch:" in content
    assert "actions/checkout@v4" in content
    assert "actions/setup-python@v5" in content
    assert "python -m scripts.agent_os_issue_acceptance.cli" in content
    assert "GITHUB_STEP_SUMMARY" in content


def test_report_only_acceptance_workflow_uses_read_permissions():
    content = _content()

    assert "contents: read" in content
    assert "issues: read" in content
    assert "pull-requests: read" in content

    forbidden = [
        "contents: " + "write",
        "issues: " + "write",
        "pull-requests: " + "write",
        "statuses: " + "write",
        "checks: " + "write",
        "actions: " + "write",
    ]
    for pattern in forbidden:
        assert pattern not in content


def test_report_only_acceptance_workflow_has_no_mutation_paths():
    content = _content()

    forbidden = [
        "gh issue " + "edit",
        "gh issue " + "close",
        "gh pr " + "edit",
        "gh pr " + "merge",
        "add-" + "label",
        "remove-" + "label",
        "set-" + "label",
        "github.rest.issues." + "addLabels",
        "github.rest.issues." + "removeLabel",
        "github.rest.issues." + "setLabels",
        "github.rest.issues." + "update",
        "github.rest.pulls." + "update",
        "branch-" + "protection",
        "updateBranch" + "Protection",
    ]
    for pattern in forbidden:
        assert pattern not in content


def test_report_only_acceptance_workflow_collects_local_fixtures():
    content = _content()

    assert "tmp/agent_os_issue_acceptance_report/issue.md" in content
    assert "tmp/agent_os_issue_acceptance_report/pr_body.md" in content
    assert "tmp/agent_os_issue_acceptance_report/changed_files.txt" in content
    assert "tmp/agent_os_issue_acceptance_report/diff.patch" in content
    assert "gh pr view" in content
    assert "gh issue view" in content
    assert "parse_linked_issue_result" in content
    assert "LinkedIssueParseStatus.RESOLVED" in content
    assert "from scripts.agent_os_issue_acceptance.parse_pr import parse_linked_issue\n" not in content


def test_report_only_acceptance_workflow_bounds_issue_lookup_to_resolved_result():
    content = _content()

    assert "result = parse_linked_issue_result(" in content
    assert "if result.status == LinkedIssueParseStatus.RESOLVED:" in content
    assert "print(result.issue_number or \"\")" in content
    assert "else:\n              print(\"\")" in content
    assert 'if [ -n "$linked_issue" ]; then' in content
    assert 'gh issue view "$linked_issue"' in content


def test_report_only_acceptance_workflow_tolerates_unreadable_linked_issue():
    content = _content()

    assert 'gh issue view "$linked_issue"' in content
    assert 'gh issue view "$linked_issue" --json body --jq' in content
    assert '> "$out/issue.md" || :' in content


def test_report_only_acceptance_workflow_publishes_report_without_gating():
    content = _content()

    assert "set +e" in content
    assert "PIPESTATUS[0]" in content
    assert "checker_exit_code=" in content
    assert "exit 0" in content
    assert "Report-only boundary" in content


def test_report_only_acceptance_workflow_declares_pr_number_dispatch_input():
    content = _content()

    assert "pr_number:" in content
    assert "PR_NUMBER: ${{ github.event.pull_request.number || inputs.pr_number }}" in content


def test_report_only_acceptance_workflow_routes_missing_pr_number_to_manual_review():
    content = _content()

    assert 'if [ -z "${PR_NUMBER:-}" ]; then' in content
    assert "Manual workflow dispatch did not provide a pull request number." in content
    assert (
        "This report-only workflow should route missing pull request context "
        "to manual review or fail according to IA2 semantics."
    ) in content


def test_report_only_acceptance_workflow_tolerates_malformed_diff_payload():
    content = _content()

    assert 'gh pr diff "$PR_NUMBER" --patch > "$out/diff.patch" || :' in content
    assert ': > "$out/issue.md"' in content
    assert ': > "$out/pr_body.md"' in content
    assert ': > "$out/pr_title.txt"' in content
    assert ': > "$out/changed_files.txt"' in content
    assert ': > "$out/diff.patch"' in content
