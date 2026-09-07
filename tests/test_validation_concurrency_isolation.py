from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _concurrency_block() -> str:
    content = WORKFLOW.read_text(encoding="utf-8")
    start = content.index("concurrency:")
    end = content.index("\njobs:", start)
    return content[start:end]


def test_pr_validation_uses_stable_pr_lineage_and_can_supersede_same_pr_runs():
    block = _concurrency_block()
    assert "github.event_name == 'pull_request'" in block
    assert "github.event.pull_request.number" in block
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in block


def test_non_pr_validation_uses_unique_run_lineage_instead_of_shared_ref():
    block = _concurrency_block()
    assert "github.run_id" in block
    assert "github.ref" not in block


def test_dispatch_inputs_do_not_control_pre_admission_concurrency_identity():
    block = _concurrency_block()
    assert "inputs.pr_number" not in block
    assert "inputs.expected_head_sha" not in block
    assert "github.event.inputs" not in block


def test_concurrency_model_does_not_preempt_future_main_push_policy():
    content = WORKFLOW.read_text(encoding="utf-8")
    trigger_block = content[: content.index("permissions:")]
    assert "\n  push:" not in trigger_block
