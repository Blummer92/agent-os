from pathlib import Path

import yaml

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
    """A non-aggregate profile can never stand in for the authoritative run.

    Previously the `validate` job was admitted only when the plan selected the
    `aggregate` profile, so a Ready PR with a static or focused plan produced a
    *skipped* required check -- which branch protection cannot distinguish from
    a pass (#2132). The profile now steers only the cheap developer-loop lane in
    the `plan` job; it has no say in whether the authoritative aggregate runs.
    """
    content = _content()
    assert "steps.plan.outputs.profile == 'focused'" in content
    assert "steps.plan.outputs.profile == 'manual-review'" in content

    start = content.index("  validate:\n")
    admission = content[start : content.index("    runs-on:", start)]
    assert "needs.plan.outputs.profile" not in admission
    assert "github.event.pull_request.draft == false" in admission

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


def test_aggregate_is_not_serialized_behind_the_developer_loop_plan_job():
    """The plan job must never sit on the authoritative aggregate's critical path.

    `validate` consumes no `plan` output -- the sibling assertions above pin that
    the profile has no say in whether the aggregate runs. A `needs: plan` edge
    therefore bought no correctness, only wall-clock: the aggregate job was not
    created until the plan job finished (measured on current `main`: ~11-16s for
    an aggregate-profile PR, and ~56s for a focused-profile Ready PR, whose plan
    job spends ~30s installing the same dependency set the aggregate job then
    installs again). The focused developer-loop lane still runs -- concurrently,
    so it keeps its early-failure value without delaying the exact-head gate.
    """
    content = _content()

    # Parsed, not string-matched: the point is the absence of a `needs:` key on
    # the job, which prose in a nearby comment must not be able to fake.
    validate = yaml.safe_load(content)["jobs"]["validate"]
    assert "needs" not in validate

    # The focused developer-loop lane is preserved, not removed.
    assert "- name: Run focused validation plan" in content
    assert "steps.plan.outputs.profile == 'focused'" in content

    # The authoritative exact-head aggregate is untouched and still singular.
    assert content.count("./scripts/validate-all.sh") == 1
    assert "checked-out SHA $checked_out_sha does not match pull request head" in content


def test_push_and_final_candidate_keep_authoritative_aggregate_lane():
    content = _content()
    assert "github.event_name != 'pull_request'" in content
    assert "name: Run aggregate validation" in content
    assert "./scripts/validate-all.sh" in content
    assert "mode=final-candidate" in content
    assert "stale final-candidate request" in content
