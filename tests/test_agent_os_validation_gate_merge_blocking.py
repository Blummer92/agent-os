from pathlib import Path


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
    assert "active|passed)" in step
    assert 'echo "run_required=false" >> "$GITHUB_OUTPUT"' in step


def test_queued_or_in_progress_exact_head_aggregate_is_not_duplicated() -> None:
    step = _ready_evidence_step(_workflow())
    assert 'any(.status == "queued" or .status == "in_progress") then "active"' in step
    assert "active|passed)" in step


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
