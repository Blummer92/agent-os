"""Behavior-first SHA-attribution regression coverage for #1270/#1642.

The validation summary must expose distinct pull-request-head and workflow-run
commit identities without freezing presentation wording. Event-specific wording
and the actual tested-checkout identity are owned by #1641.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _summary_step() -> str:
    content = _content()
    start = content.index("- name: Publish validation summary")
    return content[start:]


def _echo_lines() -> tuple[str, ...]:
    return tuple(
        line.strip()
        for line in _summary_step().splitlines()
        if line.strip().startswith('echo "- ')
    )


def _lines_using(source: str) -> tuple[str, ...]:
    return tuple(line for line in _echo_lines() if source in line)


def test_summary_reports_distinct_pr_head_and_workflow_run_sha_sources():
    content = _content()
    step = _summary_step()

    assert "github.event.pull_request.head.sha" in content
    assert "PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in content

    pr_head_lines = _lines_using("PR_HEAD_SHA")
    workflow_run_lines = _lines_using("$GITHUB_SHA")

    assert pr_head_lines, "summary must report the pull-request head identity"
    assert workflow_run_lines, "summary must report the workflow-run commit identity"
    assert set(pr_head_lines).isdisjoint(workflow_run_lines)
    assert all("$GITHUB_SHA" not in line for line in pr_head_lines)
    assert all("PR_HEAD_SHA" not in line for line in workflow_run_lines)

    # The historical ambiguous single-commit attribution must not return.
    assert 'echo "- Commit: \\`$GITHUB_SHA\\`"' not in step


def test_sha_attribution_contract_does_not_freeze_unrelated_workflow_semantics():
    """#1642 leaves checkout/concurrency/event policy to their canonical owners."""
    content = _content()

    assert "name: Agent OS Validation Gate" in content
    assert "name: Run aggregate validation" in content
    assert "contents: read" in content
    assert "pull-requests: read" in content
    assert "contents: write" not in content
    assert "pull-requests: write" not in content
