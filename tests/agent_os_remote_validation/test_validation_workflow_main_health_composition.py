from pathlib import Path

from scripts.agent_os_remote_validation import (
    SelectionInput,
    load_rule_map,
    select_validation_plan,
)
from scripts.agent_os_remote_validation.main_health import project_main_health
from scripts.agent_os_remote_validation.main_health_admission import (
    evaluate_final_validation_admission,
)


WORKFLOW = Path(".github/workflows/agent-os-validation.yml")

REPOSITORY = "Blummer92/agent-os"
CURRENT_MAIN = "1111111111111111111111111111111111111111"
STALE_BASE = "2222222222222222222222222222222222222222"
CANDIDATE_HEAD = "3333333333333333333333333333333333333333"
AGGREGATE_CHANGES = (".github/workflows/agent-os-validation.yml",)
FOCUSED_CHANGES = ("scripts/agent_os_remote_validation/selector.py",)
MANUAL_REVIEW_CHANGES = ("README.md",)


def _main_health_blockers(admission) -> tuple[str, ...]:
    """Mirror the `Project exact-current main health` step's freeze rule.

    The gate owns exactly one question, so only a `main-health.*` reason may
    freeze the run; candidate-evidence dispositions belong to their existing
    downstream owners.
    """
    return tuple(
        reason for reason in admission.reason_codes if reason.startswith("main-health.")
    )


def _admission(
    validation_conclusion: str,
    *,
    plan_base_sha: str = CURRENT_MAIN,
    evidence_sha: str | None = CURRENT_MAIN,
    changed_files: tuple[str, ...] = AGGREGATE_CHANGES,
):
    """Reproduce the workflow gate's composition exactly, offline."""
    plan = select_validation_plan(
        SelectionInput(
            repository=REPOSITORY,
            pull_request=2620,
            base_sha=plan_base_sha,
            head_sha=CANDIDATE_HEAD,
            changed_files=changed_files,
        ),
        load_rule_map(),
    )
    health = project_main_health(
        repository=REPOSITORY,
        current_main_sha=CURRENT_MAIN,
        evidence_sha=evidence_sha,
        validation_conclusion=validation_conclusion,
    )
    return evaluate_final_validation_admission(
        plan,
        None,
        main_health=health,
        current_base_sha=CURRENT_MAIN,
        current_head_sha=CANDIDATE_HEAD,
    )


def test_authoritative_aggregate_path_consumes_exact_main_health_before_candidate_run():
    text = WORKFLOW.read_text(encoding="utf-8")

    aggregate_job = text.split("  validate:\n", 1)[1]
    aggregate_command = "      - name: Run aggregate validation\n"
    assert aggregate_command in aggregate_job

    before_aggregate = aggregate_job.split(aggregate_command, 1)[0]
    assert "Project exact-current main health" in before_aggregate
    assert "evaluate_final_validation_admission" in before_aggregate
    assert "project_main_health" in before_aggregate
    assert "main-health.exact-main-red" in before_aggregate


def test_main_health_gate_is_fail_closed_for_unproven_current_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    aggregate_job = text.split("  validate:\n", 1)[1]

    assert "main-health.validation-missing" in aggregate_job
    assert "main-health.validation-pending" in aggregate_job
    assert "main-health.infrastructure-unproven" in aggregate_job
    assert "ordinary final candidate aggregate blocked by exact-current main health" in aggregate_job


def test_focused_plan_job_remains_independent_of_main_health_gate():
    text = WORKFLOW.read_text(encoding="utf-8")
    plan_job, aggregate_job = text.split("  validate:\n", 1)

    assert "Run focused validation plan" in plan_job
    assert "Project exact-current main health" not in plan_job
    assert "Project exact-current main health" in aggregate_job


def test_healthy_current_main_does_not_freeze_any_candidate_profile():
    """Regression for the gate that froze every candidate (#2550).

    With healthy current main and no candidate evidence yet, the composed
    admission reports the candidate's own obligation: `require-aggregate` for an
    aggregate plan, `admission.focused-evidence-missing` for a focused plan, and
    `admission.selector-manual-review` for a manual-review plan. None of those is
    a main-health failure, so none of them may freeze this gate.
    """
    for changed_files in (AGGREGATE_CHANGES, FOCUSED_CHANGES, MANUAL_REVIEW_CHANGES):
        admission = _admission("success", changed_files=changed_files)
        assert _main_health_blockers(admission) == (), changed_files
        assert all(
            not reason.startswith("main-health.") for reason in admission.reason_codes
        ), changed_files


def test_healthy_current_main_reports_the_aggregate_obligation_it_is_about_to_run():
    admission = _admission("success")

    assert admission.status == "require-aggregate"
    assert admission.reason_codes == ("admission.aggregate-required",)
    assert _main_health_blockers(admission) == ()


def test_unhealthy_current_main_freezes_the_candidate_aggregate():
    admission = _admission("repository-failure")

    assert admission.status == "block"
    assert _main_health_blockers(admission) == ("main-health.exact-main-red",)


def test_unproven_current_main_evidence_fails_closed():
    # Each pair is what the gate step actually produces: an absent check run
    # yields no evidence SHA, every other unproven conclusion keeps one.
    cases = (
        ("missing", None, "main-health.evidence-missing"),
        ("pending", CURRENT_MAIN, "main-health.validation-pending"),
        ("cancelled", CURRENT_MAIN, "main-health.validation-cancelled"),
        ("infrastructure-failure", CURRENT_MAIN, "main-health.infrastructure-unproven"),
    )
    for conclusion, evidence_sha, expected in cases:
        admission = _admission(conclusion, evidence_sha=evidence_sha)
        assert admission.status == "block", conclusion
        assert _main_health_blockers(admission) == (expected,), conclusion


def test_candidate_behind_current_main_is_branch_drift_not_a_main_health_block():
    """A base merely behind current main must not be reported as stale health.

    The gate selects the plan against exact-current main; selecting it against
    the candidate's recorded base made every behind candidate fail closed with
    `main-health.evidence-stale` even while main was green.
    """
    assert _main_health_blockers(_admission("success")) == ()

    misaligned = _admission("success", plan_base_sha=STALE_BASE)
    assert misaligned.status == "block"
    assert _main_health_blockers(misaligned) == ("main-health.evidence-stale",)


def test_gate_freeze_rule_matches_the_workflow_step():
    step = WORKFLOW.read_text(encoding="utf-8").split(
        "      - name: Project exact-current main health\n", 1
    )[1].split("\n      - name: ", 1)[0]

    assert 'reason.startswith("main-health.")' in step
    assert "if main_health_blockers:" in step
    # The plan must be selected against exact-current main, not the stale base.
    assert 'base_sha=os.environ["CURRENT_MAIN_SHA"]' in step
    assert 'base_sha=os.environ["CANDIDATE_BASE_SHA"]' not in step


def test_missing_exact_main_evidence_uses_existing_validation_authority_for_recovery():
    text = WORKFLOW.read_text(encoding="utf-8")
    aggregate_job = text.split("  validate:\n", 1)[1]

    recovery = aggregate_job.split(
        "      - name: Recover missing exact-current main aggregate evidence\n", 1
    )[1].split("\n      - name: ", 1)[0]

    assert 'select(.name == "Run aggregate validation")' in recovery
    assert 'gh workflow run agent-os-validation.yml --ref "$current_main_sha"' in recovery
    assert 'echo "recovery_required=true"' in recovery
    assert "workflow_dispatch:" in text


def test_missing_main_recovery_never_substitutes_candidate_or_prior_main_evidence():
    text = WORKFLOW.read_text(encoding="utf-8")
    recovery = text.split(
        "      - name: Recover missing exact-current main aggregate evidence\n", 1
    )[1].split("\n      - name: ", 1)[0]
    stop = text.split(
        "      - name: Stop candidate while exact-current main recovery runs\n", 1
    )[1].split("\n      - name: ", 1)[0]

    assert 'git/ref/heads/main' in recovery
    assert '--ref "$current_main_sha"' in recovery
    assert "PR_HEAD_SHA" not in recovery
    assert "CANDIDATE_HEAD_SHA" not in recovery
    assert "exit 1" in stop
    assert "Candidate validation remains fail-closed" in stop


def test_existing_exact_main_evidence_does_not_dispatch_recovery():
    text = WORKFLOW.read_text(encoding="utf-8")
    recovery = text.split(
        "      - name: Recover missing exact-current main aggregate evidence\n", 1
    )[1].split("\n      - name: ", 1)[0]

    assert 'if [ "$check_count" != "0" ]; then' in recovery
    assert 'echo "recovery_required=false"' in recovery
    assert "exit 0" in recovery


def test_main_health_lookup_filters_aggregate_check_server_side_before_page_limit():
    """Unrelated checks cannot evict exact-main aggregate evidence from page 1."""
    step = WORKFLOW.read_text(encoding="utf-8").split(
        "      - name: Project exact-current main health\n", 1
    )[1].split("\n      - name: ", 1)[0]

    assert (
        'check-runs?check_name=Run%20aggregate%20validation&per_page=100'
        in step
    )
    assert 'check-runs?per_page=100' not in step
