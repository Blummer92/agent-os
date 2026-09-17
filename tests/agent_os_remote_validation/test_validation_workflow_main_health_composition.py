from pathlib import Path


WORKFLOW = Path(".github/workflows/agent-os-validation.yml")


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
