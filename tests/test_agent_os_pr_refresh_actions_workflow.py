import json
import re
import textwrap
from pathlib import Path

import pytest

from scripts.agent_os_issue_labels.pr_branch_refresh_actions import _TRIGGER

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"

_ADMISSION_LITERAL = re.compile(
    r"startsWith\(github\.event\.comment\.body, '(?P<prefix>[^']*)'\)"
)


def _refresh_job(text: str) -> str:
    marker = "  refresh_pr:\n"
    assert marker in text
    return text.split(marker, 1)[1]


def _admission_prefix() -> str:
    """Return the literal the refresh job's YAML admission guard tests against."""
    condition = _refresh_job(WORKFLOW.read_text(encoding="utf-8")).split("\n    if:", 1)[1]
    condition = condition.split("\n", 1)[0]
    match = _ADMISSION_LITERAL.search(condition)
    assert match is not None, "refresh admission must use a startsWith prefilter"
    return match.group("prefix")


def _summary_program() -> str:
    """Extract the executable body of the 'Publish bounded refresh summary' step."""
    job = _refresh_job(WORKFLOW.read_text(encoding="utf-8"))
    step = job.split("- name: Publish bounded refresh summary", 1)[1]
    body = step.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(body)


def _render_summary(tmp_path: Path, result: object | None) -> str:
    """Run the workflow's real summary program against one bounded result payload."""
    runner_temp = tmp_path / "runner"
    (runner_temp / "agent-os-refresh").mkdir(parents=True)
    if result is not None:
        (runner_temp / "agent-os-refresh" / "result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )
    step_summary = tmp_path / "summary.md"
    step_summary.write_text("", encoding="utf-8")
    namespace = {
        "__name__": "__main__",
        "os": __import__("os"),
    }
    environ = {
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_STEP_SUMMARY": str(step_summary),
    }
    import os as _os

    saved = {key: _os.environ.get(key) for key in environ}
    _os.environ.update(environ)
    try:
        exec(compile(_summary_program(), "<refresh-summary>", "exec"), namespace)
    finally:
        for key, value in saved.items():
            if value is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = value
    return step_summary.read_text(encoding="utf-8")


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
    assert "pull-requests: write" in permissions
    assert "pull-requests: read" not in permissions
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


# --- #1875: one canonical trigger grammar -----------------------------------


def test_refresh_admission_carries_no_operand_parsing_semantics() -> None:
    """The YAML guard must not encode the operand boundary the canonical parser owns."""
    prefix = _admission_prefix()
    assert prefix == "/agent-os refresh-pr"
    assert not prefix.endswith(" "), (
        "a trailing space makes the YAML guard decide where the operand begins, "
        "duplicating scripts/agent_os_issue_labels/pr_branch_refresh_actions.py"
    )


@pytest.mark.parametrize(
    "body",
    [
        "/agent-os refresh-pr 1",
        "/agent-os refresh-pr 1619",
        "/agent-os refresh-pr 1849",
        "/agent-os refresh-pr 999999",
    ],
)
def test_admission_admits_everything_the_canonical_parser_accepts(body: str) -> None:
    """Admission must never reject a trigger the canonical grammar would accept."""
    assert _TRIGGER.fullmatch(body) is not None
    assert body.startswith(_admission_prefix())


@pytest.mark.parametrize(
    "body",
    [
        "/agent-os refresh-pr 1619 ",
        "/agent-os refresh-pr 1619\n",
        "/agent-os refresh-pr 1619 please retry",
        "/agent-os refresh-pr abc",
        "/agent-os refresh-pr 0",
        "/agent-os refresh-pr",
    ],
)
def test_canonically_rejected_triggers_still_reach_the_canonical_parser(body: str) -> None:
    """Rejected triggers must be admitted so they produce a precise terminal reason."""
    assert _TRIGGER.fullmatch(body) is None
    assert body.startswith(_admission_prefix()), (
        "a trigger the canonical parser rejects must still be admitted, otherwise it "
        "persists with no traceable invocation evidence (#1875)"
    )


# --- #1875: bounded terminal presentation -----------------------------------


def test_summary_surfaces_preserved_receipt_when_publication_fails(tmp_path: Path) -> None:
    """A converged refresh must stay attributable behind a publication failure."""
    rendered = _render_summary(
        tmp_path,
        {
            "status": "needs-decision",
            "reason_codes": [
                "authorization.receipt-publication-failed",
                "authorization.receipt-publication-http-403",
            ],
            "mutation_count": 1,
            "authorization_receipt_published": False,
            "receipt_publication_http_status": 403,
            "refresh_receipt": {
                "status": "converged",
                "reason_codes": ["refresh.branch-updated"],
                "new_head_sha": "a" * 40,
            },
        },
    )
    assert "Status: `needs-decision`" in rendered
    assert "Receipt publication HTTP status: `403`" in rendered
    assert "Underlying refresh status: `converged`" in rendered
    assert "Underlying refresh reasons: `refresh.branch-updated`" in rendered
    assert f"Refreshed head SHA: `{'a' * 40}`" in rendered


def test_summary_reports_precise_rejected_trigger_reason(tmp_path: Path) -> None:
    rendered = _render_summary(
        tmp_path,
        {
            "status": "blocked",
            "reason_codes": ["operation-not-requested"],
            "mutation_count": 0,
            "authorization_receipt_published": False,
            "refresh_receipt": None,
        },
    )
    assert "Status: `blocked`" in rendered
    assert "Reasons: `operation-not-requested`" in rendered
    assert "Underlying refresh receipt: `unavailable`" in rendered


def test_summary_does_not_leak_unbounded_receipt_fields(tmp_path: Path) -> None:
    """Only bounded whitelisted receipt fields may be rendered."""
    rendered = _render_summary(
        tmp_path,
        {
            "status": "needs-decision",
            "reason_codes": ["authorization.receipt-publication-failed"],
            "mutation_count": 1,
            "authorization_receipt_published": False,
            "refresh_receipt": {
                "status": "converged",
                "reason_codes": ["refresh.branch-updated"],
                "new_head_sha": "not-a-sha",
                "token": "ghp_should_never_be_rendered",
                "authorization_body": "arbitrary owner comment text",
            },
        },
    )
    assert "ghp_should_never_be_rendered" not in rendered
    assert "arbitrary owner comment text" not in rendered
    assert "not-a-sha" not in rendered


def test_summary_still_reports_missing_result_evidence(tmp_path: Path) -> None:
    rendered = _render_summary(tmp_path, None)
    assert "Result evidence unavailable; manual review required." in rendered


def test_summary_step_always_runs_and_evidence_is_uploaded() -> None:
    job = _refresh_job(WORKFLOW.read_text(encoding="utf-8"))
    summary_step = job.split("- name: Publish bounded refresh summary", 1)[1]
    assert "if: ${{ always() }}" in summary_step.split("run:", 1)[0]
    assert "upload-artifact" in job
    assert "if-no-files-found: warn" in job