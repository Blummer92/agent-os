import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _validate_job_header(content: str) -> str:
    start = content.index("  validate:\n")
    end = content.index("    runs-on:", start)
    return content[start:end]


def _ready_evidence_step(content: str) -> str:
    start = content.index("      - name: Reuse valid exact-head aggregate evidence")
    end = content.index("      - name: Check out repository", start)
    return content[start:end]


def test_ready_for_review_event_rechecks_exact_head_gate() -> None:
    content = _workflow()
    pull_request = content.index("pull_request:")
    push = content.index("push:")
    trigger_block = content[pull_request:push]
    assert "ready_for_review" in trigger_block


def test_ready_pull_request_aggregate_gate_is_not_profile_skippable() -> None:
    header = _validate_job_header(_workflow())
    assert "github.event.pull_request.draft == false" in header
    assert "needs.plan.outputs.profile" not in header


def test_draft_pull_request_still_defers_automatic_aggregate_cost() -> None:
    header = _validate_job_header(_workflow())
    assert "github.event.pull_request.draft == false" in header
    assert "github.event_name != 'pull_request'" in header


def test_aggregate_command_remains_the_authoritative_gate_command() -> None:
    content = _workflow()
    assert content.count("./scripts/validate-all.sh") == 1
    assert "name: Run aggregate validation" in content


def test_exact_head_final_candidate_dispatch_remains_available_for_drafts() -> None:
    content = _workflow()
    assert "workflow_dispatch:" in content
    assert 'echo "mode=final-candidate" >> "$GITHUB_OUTPUT"' in content
    assert 'if [ "$GITHUB_SHA" != "$EXPECTED_HEAD_SHA" ]' in content
    assert "dispatch the workflow on a ref resolving to the exact PR head" in content


def test_ready_event_does_not_cancel_equivalent_in_flight_same_pr_validation() -> None:
    content = _workflow()
    assert (
        "cancel-in-progress: ${{ github.event_name == 'pull_request' "
        "&& github.event.action != 'ready_for_review' }}"
    ) in content


def test_ready_event_queries_only_current_head_aggregate_check_evidence() -> None:
    step = _ready_evidence_step(_workflow())
    assert 'HEAD_SHA: ${{ github.event.pull_request.head.sha }}' in step
    assert '"/repos/$GITHUB_REPOSITORY/commits/$HEAD_SHA/check-runs?per_page=100"' in step
    assert 'select(.name == "Run aggregate validation")' in step
    assert "CURRENT_RUN_URL_FRAGMENT" in step
    assert "contains(env.CURRENT_RUN_URL_FRAGMENT)" in step


def test_historical_1904_shape_reuses_completed_exact_head_success() -> None:
    step = _ready_evidence_step(_workflow())
    assert 'any(.status == "completed" and .conclusion == "success") then "passed"' in step
    assert "passed)" in step
    assert "active|passed)" not in step
    assert 'echo "run_required=false" >> "$GITHUB_OUTPUT"' in step


def test_queued_or_in_progress_exact_head_aggregate_is_not_reusable_success() -> None:
    step = _ready_evidence_step(_workflow())
    assert 'any(.status == "queued" or .status == "in_progress") then "active"' in step
    assert "active|passed)" not in step
    assert 'active)' not in step
    assert 'echo "run_required=true" >> "$GITHUB_OUTPUT"' in step


def test_missing_failed_or_cancelled_current_head_evidence_requires_aggregate() -> None:
    step = _ready_evidence_step(_workflow())
    assert 'else "missing-or-nonpassing"' in step
    assert 'echo "run_required=true" >> "$GITHUB_OUTPUT"' in step
    assert '.conclusion == "failure"' not in step
    assert '.conclusion == "cancelled"' not in step


def test_new_sha_and_stale_older_sha_evidence_cannot_be_reused() -> None:
    step = _ready_evidence_step(_workflow())
    assert "commits/$HEAD_SHA/check-runs" in step
    assert "pulls/$PR_NUMBER/check-runs" not in step
    assert "head_branch" not in step


def test_ready_without_prior_aggregate_still_executes_authoritative_command() -> None:
    content = _workflow()
    aggregate = content.index("      - name: Run aggregate validation")
    summary = content.index("      - name: Publish validation summary", aggregate)
    aggregate_block = content[aggregate:summary]
    assert "steps.aggregate_evidence.outputs.run_required != 'false'" in aggregate_block
    assert "run: ./scripts/validate-all.sh" in aggregate_block


def test_ready_completed_evidence_reuse_skips_all_aggregate_execution_cost() -> None:
    content = _workflow()
    for step_name in (
        "Check out repository",
        "Verify aggregate checkout identity",
        "Set up Python",
        "Install validation dependencies",
        "Run aggregate validation",
    ):
        start = content.index(f"      - name: {step_name}", content.index("  validate:\n"))
        next_step = content.find("\n      - name:", start + 1)
        block = content[start : next_step if next_step != -1 else len(content)]
        assert "steps.aggregate_evidence.outputs.run_required != 'false'" in block


def test_manual_diagnostic_and_final_candidate_dispatch_do_not_use_ready_reuse_gate() -> None:
    step = _ready_evidence_step(_workflow())
    assert "github.event.action == 'ready_for_review'" in step
    assert "workflow_dispatch" not in step
    assert "mode=diagnostic" in _workflow()
    assert "mode=final-candidate" in _workflow()


CURRENT_RUN = "/actions/runs/200"


def _reuse_step_script() -> str:
    workflow = yaml.safe_load(_workflow())
    (step,) = [
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("name") == "Reuse valid exact-head aggregate evidence"
    ]
    return step["run"]


def _run_reuse_step(tmp_path: Path, check_runs: list[dict]) -> dict[str, str]:
    """Execute the real reuse step against a stubbed `gh api` check-run response."""
    fixture = tmp_path / "check-runs.json"
    fixture.write_text(json.dumps({"check_runs": check_runs}), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = --jq ]; then exec jq -r \"$2\" \"$GH_FIXTURE\"; fi\n"
        "  shift\n"
        "done\n"
        "exit 1\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    output = tmp_path / "output"
    subprocess.run(
        ["bash", "-e", "-c", _reuse_step_script()],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GH_FIXTURE": str(fixture),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": "Blummer92/agent-os",
            "HEAD_SHA": "d3501c232181963deda648483c9c65f4290f8ba7",
            "CURRENT_RUN_URL_FRAGMENT": CURRENT_RUN,
        },
        check=True,
    )
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


def _check(run: str, status: str, conclusion: str | None) -> dict:
    return {
        "name": "Run aggregate validation",
        "status": status,
        "conclusion": conclusion,
        "details_url": f"https://github.com/Blummer92/agent-os/actions/runs/{run}/job/1",
    }


def test_2631_chronology_draft_skipped_job_is_not_reusable_evidence(tmp_path: Path) -> None:
    # PR #2631: the Draft-time run skipped the aggregate job; the Ready run must
    # execute it rather than treat the skipped job as accepted evidence.
    outputs = _run_reuse_step(
        tmp_path,
        [_check("35349164504", "completed", "skipped"), _check("200", "in_progress", None)],
    )
    assert outputs == {"state": "missing-or-nonpassing", "run_required": "true"}


def test_completed_exact_head_success_is_reused_once(tmp_path: Path) -> None:
    outputs = _run_reuse_step(tmp_path, [_check("100", "completed", "success")])
    assert outputs == {"state": "passed", "run_required": "false"}


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_active_other_run_is_never_reported_as_satisfied_evidence(tmp_path: Path, status: str) -> None:
    # Skipping here would publish a green aggregate check for this run while the
    # other run could still fail (#2920 / #2589 masking shape).
    outputs = _run_reuse_step(
        tmp_path,
        [_check("100", "completed", "success"), _check("101", status, None)],
    )
    assert outputs == {"state": "active", "run_required": "true"}


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped"])
def test_nonpassing_exact_head_evidence_requires_aggregate(tmp_path: Path, conclusion: str) -> None:
    outputs = _run_reuse_step(tmp_path, [_check("100", "completed", conclusion)])
    assert outputs == {"state": "missing-or-nonpassing", "run_required": "true"}
