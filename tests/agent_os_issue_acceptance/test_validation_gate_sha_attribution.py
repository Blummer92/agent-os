"""Behavior-first SHA-attribution regression coverage for #1270/#1641/#1642.

The validation summary must expose distinct pull-request-head, workflow-run, and
actual tested-checkout identities without freezing arbitrary presentation syntax.
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


def test_summary_reports_distinct_pr_head_workflow_run_and_tested_sha_sources():
    content = _content()
    step = _summary_step()

    assert "github.event.pull_request.head.sha" in content
    assert "PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in content
    assert 'tested_sha="$(git rev-parse HEAD)"' in step

    pr_head_lines = _lines_using("PR_HEAD_SHA")
    workflow_run_lines = _lines_using("$GITHUB_SHA")
    tested_checkout_lines = _lines_using("$tested_sha")

    assert pr_head_lines, "summary must report the pull-request head identity"
    assert workflow_run_lines, "summary must report the workflow-run commit identity"
    assert tested_checkout_lines, "summary must report the actual tested checkout identity"
    assert set(pr_head_lines).isdisjoint(workflow_run_lines)
    assert set(pr_head_lines).isdisjoint(tested_checkout_lines)
    assert set(workflow_run_lines).isdisjoint(tested_checkout_lines)

    assert all("$GITHUB_SHA" not in line and "$tested_sha" not in line for line in pr_head_lines)
    assert all("PR_HEAD_SHA" not in line and "$tested_sha" not in line for line in workflow_run_lines)
    assert all("PR_HEAD_SHA" not in line and "$GITHUB_SHA" not in line for line in tested_checkout_lines)

    # The historical ambiguous single-commit attribution must not return.
    assert 'echo "- Commit: \\`$GITHUB_SHA\\`"' not in step


def test_summary_uses_event_specific_identity_labels_without_inventing_merge_semantics():
    step = _summary_step()

    assert 'if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then' in step
    assert "Pull request head SHA" in step

    assert 'if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]; then' in step
    assert 'if [ "$DISPATCH_MODE" = "final-candidate" ]; then' in step
    assert "Admitted candidate SHA" in step
    assert "DISPATCH_HEAD_SHA: ${{ steps.candidate.outputs.head_sha }}" in step
    assert "Dispatch mode" in step

    # Dispatch and future push events must never be described as PR merge identity.
    assert "Checked-out (merge) SHA" not in step
    assert "Head SHA (pull request head)" not in step


def test_summary_is_future_push_compatible_without_pr_only_identity_requirements():
    step = _summary_step()

    assert "Workflow run SHA" in step
    assert "Tested checkout SHA" in step
    assert "Event" in step

    # Generic run/tested identity reporting sits outside PR/dispatch conditionals,
    # so a future push: main trigger can use it without fabricating PR semantics.
    workflow_run = step.index("Workflow run SHA")
    tested_checkout = step.index("Tested checkout SHA")
    pr_conditional = step.index('if [ "$GITHUB_EVENT_NAME" = "pull_request" ]; then')
    dispatch_conditional = step.index('if [ "$GITHUB_EVENT_NAME" = "workflow_dispatch" ]; then')
    assert workflow_run < pr_conditional
    assert tested_checkout < pr_conditional
    assert workflow_run < dispatch_conditional
    assert tested_checkout < dispatch_conditional


def test_sha_attribution_contract_does_not_freeze_unrelated_workflow_semantics():
    """#1641 keeps admission, concurrency, triggers, and permissions with their owners."""
    content = _content()

    assert "name: Agent OS Validation Gate" in content
    assert "name: Run aggregate validation" in content
    assert "contents: read" in content
    assert "pull-requests: read" in content
    assert "contents: write" not in content
    assert "pull-requests: write" not in content

    assert "github.event_name == 'pull_request' && github.event.pull_request.number || github.run_id" in content
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in content
    assert "final-candidate dispatch SHA $GITHUB_SHA does not match admitted candidate $EXPECTED_HEAD_SHA" in content
    assert content.count("./scripts/validate-all.sh") == 1
