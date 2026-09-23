"""Static security contract for the authorized #2283 activation workflow."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-notion-read.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_issue_comment_only_and_owner_prefiltered() -> None:
    text = workflow_text()
    assert "issue_comment:" in text
    assert "types: [created]" in text
    assert "github.event.issue.pull_request == null" in text
    assert "github.event.comment.user.id == 32861845" in text
    assert "startsWith(github.event.comment.body, '/agent-os notion-read')" in text


def test_workflow_has_read_only_github_permissions_and_no_gcp_identity() -> None:
    text = workflow_text()
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    for forbidden in (
        "contents: write",
        "issues: write",
        "pull-requests: write",
        "actions: write",
        "id-token: write",
    ):
        assert forbidden not in permissions
    assert "google-github-actions" not in text
    assert "gcloud" not in text


def test_workflow_loads_catalog_for_normal_admission() -> None:
    text = workflow_text()
    assert "load_catalog" in text
    assert "catalog=load_catalog()" in text


def test_secret_is_exposed_only_to_post_admission_execution_steps() -> None:
    text = workflow_text()
    assert text.count("NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}") == 2
    admission_index = text.index("Admit bounded Notion read without credentials")
    first_secret_index = text.index("NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}")
    assert admission_index < first_secret_index
    assert "steps.admission.outputs.secret_dispatch_authorized == 'true'" in text[:first_secret_index]
    assert "--live-notion" in text[first_secret_index:]


def test_binding_verification_is_finite_and_separate_from_normal_dispatch() -> None:
    text = workflow_text()
    assert "VERIFICATION_REQUEST_ID" in text
    assert "admit_binding_verification_request" in text
    assert "steps.admission.outputs.binding_verification == 'true'" in text
    assert "scripts.agent_os_notion_read_request.binding_verification" in text


def test_workflow_publishes_only_bounded_result_artifacts() -> None:
    text = workflow_text()
    assert "retention-days: 7" in text
    assert "${{ runner.temp }}/agent-os-notion-read/*.json" in text
    assert "repository files" not in text
