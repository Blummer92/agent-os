from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-validation.yml"


def _content() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_pr_events_use_distinct_profile_job_and_exact_head_checkout():
    content = _content()
    assert "name: Run validation plan" in content
    assert "ref: ${{ github.event.pull_request.head.sha }}" in content
    assert "SelectionInput(" in content
    assert "select_validation_plan" in content
    assert "gh api --paginate" in content
    assert "/pulls/$PR_NUMBER/files?per_page=100" in content


def test_static_and_focused_profiles_do_not_impersonate_aggregate_success():
    content = _content()
    assert "steps.plan.outputs.profile == 'focused'" in content
    assert "steps.plan.outputs.profile == 'manual-review'" in content
    assert "needs.plan.outputs.profile == 'aggregate'" in content
    assert content.count("- name: Run aggregate validation") == 1
    assert "Static/focused evidence is non-final" in content
    assert "Static/focused PR evidence never substitutes" in content


def test_manual_review_fails_closed_and_focused_execution_uses_bounded_helper():
    content = _content()
    assert "Canonical validation selector requires manual review" in content
    assert "python scripts/agent_os_ci_validation.py" in content
    assert "eval " not in content
    assert "bash -c" not in content
    assert "sh -c" not in content


def test_push_and_final_candidate_keep_authoritative_aggregate_lane():
    content = _content()
    assert "github.event_name != 'pull_request'" in content
    assert "name: Run aggregate validation" in content
    assert "./scripts/validate-all.sh" in content
    assert "mode=final-candidate" in content
    assert "stale final-candidate request" in content
