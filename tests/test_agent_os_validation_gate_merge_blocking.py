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


def test_ready_event_reads_latest_canonical_commit_status_for_exact_head() -> None:
    step = _ready_evidence_step(_workflow())
    assert 'HEAD_SHA: ${{ github.event.pull_request.head.sha }}' in step
    assert '"/repos/$GITHUB_REPOSITORY/commits/$HEAD_SHA/statuses?per_page=100"' in step
    assert 'select(.context == "agent-os/authoritative-aggregate")' in step
    assert "sort_by(.id)" in step
    # Historical "any successful check run" semantics are gone (#2761).
    assert "check-runs" not in step
    assert "pulls/$PR_NUMBER" not in step


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


def _reuse_step_script() -> str:
    workflow = yaml.safe_load(_workflow())
    (step,) = [
        step
        for step in workflow["jobs"]["validate"]["steps"]
        if step.get("name") == "Reuse valid exact-head aggregate evidence"
    ]
    return step["run"]


def _run_reuse_step(tmp_path: Path, statuses: list[dict]) -> dict[str, str]:
    """Execute the real reuse step against a stubbed `gh api` status response."""
    fixture = tmp_path / "statuses.json"
    fixture.write_text(json.dumps(statuses), encoding="utf-8")
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
        },
        check=True,
    )
    return dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())


def _status(status_id: int, state: str, context: str = "agent-os/authoritative-aggregate") -> dict:
    return {"id": status_id, "state": state, "context": context}


# (statuses newest-first as GitHub returns them, expected state, run_required)
REUSE_MATRIX = [
    ([], "missing", "true"),
    ([_status(1, "success")], "success", "false"),
    ([_status(2, "pending"), _status(1, "success")], "pending", "true"),
    # #2761: older success -> newer failure must not be reused.
    ([_status(2, "failure"), _status(1, "success")], "failure", "true"),
    ([_status(2, "error"), _status(1, "success")], "error", "true"),
    # Newer success after a failure is the governing evidence.
    ([_status(3, "success"), _status(2, "failure")], "success", "false"),
    # Ordering of the response must not matter; the highest id governs.
    ([_status(1, "success"), _status(2, "failure")], "failure", "true"),
    # Other contexts never count, however new or green.
    ([_status(9, "success", "ci/other")], "missing", "true"),
    ([_status(9, "success", "ci/other"), _status(2, "failure")], "failure", "true"),
]


@pytest.mark.parametrize("statuses,state,run_required", REUSE_MATRIX)
def test_workflow_reuse_step_obeys_latest_status_matrix(
    tmp_path: Path, statuses: list[dict], state: str, run_required: str
) -> None:
    outputs = _run_reuse_step(tmp_path, statuses)
    assert outputs == {"state": state, "run_required": run_required}


@pytest.mark.parametrize("statuses,state,run_required", REUSE_MATRIX)
def test_python_reuse_decision_matches_workflow_matrix(
    statuses: list[dict], state: str, run_required: str
) -> None:
    from scripts.agent_os_aggregate_gate import evaluate_reuse

    assert evaluate_reuse(statuses) == (run_required == "false", state)
