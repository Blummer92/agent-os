from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _validate_job_header(content: str) -> str:
    start = content.index("  validate:\n")
    end = content.index("    runs-on:", start)
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
