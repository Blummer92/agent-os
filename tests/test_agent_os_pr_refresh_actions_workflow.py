from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"


def _refresh_job(text: str) -> str:
    marker = "  refresh_pr:\n"
    assert marker in text
    return text.split(marker, 1)[1]


def test_refresh_job_is_job_level_least_privilege_and_keeps_ingress_baseline() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    top_permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in top_permissions
    assert "id-token: write" in top_permissions
    assert "contents: write" not in top_permissions
    assert "issues: write" not in top_permissions

    job = _refresh_job(text)
    permissions = job.split("permissions:", 1)[1].split("steps:", 1)[0]
    assert "contents: write" in permissions
    assert "issues: write" in permissions
    assert "pull-requests: read" in permissions
    assert "id-token: write" not in permissions
    assert "actions: write" not in permissions
    assert "workflows: write" not in permissions


def test_refresh_job_uses_only_finite_runner_and_no_gce_fallback() -> None:
    job = _refresh_job(WORKFLOW.read_text(encoding="utf-8"))
    assert "pr_branch_refresh_actions_runner" in job
    assert "--event \"$GITHUB_EVENT_PATH\"" in job
    assert "--repository \"$GITHUB_REPOSITORY\"" in job
    assert "--run-attempt \"$GITHUB_RUN_ATTEMPT\"" in job
    assert "GITHUB_TOKEN: ${{ github.token }}" in job
    assert "fetch-depth: 0" in job
    assert "gcloud" not in job
    assert "google-github-actions" not in job
    assert "update_ref" not in job
    assert "git push --force" not in job
    assert "secrets." not in job


def test_refresh_job_does_not_accept_authority_from_comment_text() -> None:
    job = _refresh_job(WORKFLOW.read_text(encoding="utf-8"))
    assert "branch_refresh_authorized=" not in job
    assert "label_write_authorized=" not in job
    assert "authorization_id=" not in job
    assert "--force" not in job
    assert "refspec" not in job
