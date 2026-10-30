"""Workflow wiring tests for the production merge-admission caller (#3463).

The ``merge_admission`` job in ``agent-os-governed-invocation.yml`` is the
production caller of ``merge_applicability``. These tests pin its shape
from the workflow text, following the refresh-job test pattern:

- owner-only, issue-comment admission guard;
- read-only job permissions (no write permission anywhere in the job);
- candidate step first, dispatch step second, both on the SAME transport
  file, writing distinct receipt files in the same directory;
- no merge-API call in the job;
- the summary program reports both receipts, and the artifact step
  publishes every JSON receipt in the job directory.
"""
import json
import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
TRANSPORT = "$RUNNER_TEMP/agent-os-merge-admission/transport.json"


def _merge_job(text: str) -> str:
    marker = "  merge_admission:\n"
    assert marker in text
    rest = text.split(marker, 1)[1]
    next_job = re.search(r"^  [A-Za-z_][\w-]*:\n", rest, re.MULTILINE)
    return rest[: next_job.start()] if next_job else rest


def _summary_program(job: str) -> str:
    step = job.split("- name: Publish merge-admission evidence summary", 1)[1]
    body = step.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(body)


def _render_summary(tmp_path: Path, candidate: object | None, dispatch: object | None) -> str:
    runner_temp = tmp_path / "runner"
    (runner_temp / "agent-os-merge-admission").mkdir(parents=True)
    if candidate is not None:
        (runner_temp / "agent-os-merge-admission" / "receipt.json").write_text(
            json.dumps(candidate), encoding="utf-8"
        )
    if dispatch is not None:
        (runner_temp / "agent-os-merge-admission" / "dispatch_receipt.json").write_text(
            json.dumps(dispatch), encoding="utf-8"
        )
    step_summary = tmp_path / "summary.md"
    step_summary.write_text("", encoding="utf-8")
    namespace = {"__name__": "__main__", "os": __import__("os")}
    environ = {
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_STEP_SUMMARY": str(step_summary),
    }
    import os as _os

    saved = {key: _os.environ.get(key) for key in environ}
    _os.environ.update(environ)
    try:
        exec(compile(_summary_program(_merge_job(WORKFLOW.read_text(encoding="utf-8"))), "<merge-summary>", "exec"), namespace)
    finally:
        for key, value in saved.items():
            if value is None:
                _os.environ.pop(key, None)
            else:
                _os.environ[key] = value
    return step_summary.read_text(encoding="utf-8")


def test_merge_admission_job_is_owner_only_and_read_only() -> None:
    job = _merge_job(WORKFLOW.read_text(encoding="utf-8"))
    condition = job.split("\n    if:", 1)[1].split("\n", 1)[0]
    assert "github.event.issue.pull_request == null" in condition
    assert "github.event.comment.user.id == 32861845" in condition
    assert "startsWith(github.event.comment.body, '/agent-os merge-admit ')" in condition
    permissions = job.split("permissions:", 1)[1].split("steps:", 1)[0]
    for permission in ("contents: read", "issues: read", "pull-requests: read", "checks: read", "statuses: read"):
        assert permission in permissions
    assert ": write" not in permissions
    assert "actions: write" not in job
    assert "workflows: write" not in job


def test_merge_admission_job_calls_candidate_then_dispatch_on_same_transport() -> None:
    job = _merge_job(WORKFLOW.read_text(encoding="utf-8"))
    candidate = job.index("scripts.agent_os_issue_acceptance.merge_admission_actions")
    dispatch = job.index("scripts.agent_os_issue_acceptance.merge_applicability")
    assert candidate < dispatch, "dispatch step must run after the candidate step"
    assert job.count(TRANSPORT) >= 2, "both steps must use the same transport file"
    assert "--output \"$RUNNER_TEMP/agent-os-merge-admission/receipt.json\"" in job
    assert "--output \"$RUNNER_TEMP/agent-os-merge-admission/dispatch_receipt.json\"" in job
    # The dispatch step carries the same read-only token as the candidate
    # step and performs no merge: no merge-API invocation pattern appears.
    for pattern in ("pulls.merge", ".merge(", "gh pr merge", "merge_commit_sha"):
        assert pattern not in job, pattern
    assert "GITHUB_TOKEN" in job


def test_merge_admission_summary_reports_both_receipts(tmp_path: Path) -> None:
    candidate = {
        "status": "blocked",
        "reason_codes": ["approval-and-applicability-evidence-not-wired"],
        "authorization_source_status": "current",
    }
    dispatch = {
        "status": "applicable",
        "merge_authorized": True,
        "reason_codes": [],
        "canonical_applicability_evaluated": True,
    }
    summary = _render_summary(tmp_path, candidate, dispatch)
    assert "Candidate merge authorized: False" in summary
    assert "Dispatch merge authorized: True" in summary
    assert "Canonical applicability evaluated: True" in summary
    assert "performs no merge" in summary


def test_merge_admission_summary_fails_closed_when_dispatch_receipt_missing(tmp_path: Path) -> None:
    summary = _render_summary(tmp_path, {"status": "blocked", "reason_codes": [], "authorization_source_status": "current"}, None)
    assert "Dispatch evidence missing; fail closed." in summary


def test_merge_admission_artifacts_publish_all_receipt_json() -> None:
    job = _merge_job(WORKFLOW.read_text(encoding="utf-8"))
    artifact = job.split("- name: Publish bounded merge-admission receipt artifacts", 1)[1]
    assert "path: ${{ runner.temp }}/agent-os-merge-admission/*.json" in artifact
    assert "retention-days: 7" in artifact
