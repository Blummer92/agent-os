from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rc6-technical-pilot.yml"


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_manual_only_and_uses_exact_frozen_sha_input():
    content = _content()

    assert "name: RC6 Technical Pilot" in content
    assert "workflow_dispatch:" in content
    assert "frozen_sha:" in content
    assert "ca980c38d74b8d3ab30ca67461a9f576281edc75" in content
    assert "ref: ${{ inputs.frozen_sha }}" in content
    assert "pull_request:" not in content
    assert "push:" not in content
    assert "schedule:" not in content


def test_workflow_separates_runner_source_from_frozen_tested_checkout():
    content = _content()

    assert content.count("uses: actions/checkout@v4") == 2
    assert "path: frozen-repo" in content
    assert "persist-credentials: false" in content
    assert "./.github/actions/setup-python-dev" in content
    assert "--repository-root frozen-repo" in content
    assert '--runner-sha "$runner_sha"' in content


def test_workflow_has_read_only_permissions_and_no_mutation_commands():
    content = _content()

    assert "permissions:\n  contents: read" in content
    forbidden = [
        "contents: write",
        "issues: write",
        "pull-requests: write",
        "statuses: write",
        "checks: write",
        "gh issue edit",
        "gh issue close",
        "gh pr edit",
        "gh pr merge",
        "git push",
        "git commit",
        "notion",
        "gcloud",
        "gsutil",
    ]
    for token in forbidden:
        assert token not in content


def test_workflow_runs_focused_tests_uploads_artifacts_and_publishes_summary():
    content = _content()

    assert "python -m pytest tests/rc6_technical_pilot" in content
    assert "python -m scripts.agent_os_rc6_technical_pilot.cli" in content
    assert "actions/upload-artifact@v4" in content
    assert "rc6-technical-pilot-${{ inputs.frozen_sha }}" in content
    assert "GITHUB_STEP_SUMMARY" in content
    assert "rc6-technical-pilot.json" in content
    assert "rc6-technical-pilot.md" in content
    assert "exit_code" in content
