"""Contract regressions for Ready-PR exact-head zero-job recovery.

These tests must fail until the bounded workflow repair is implemented.
They do not grant workflow, merge, or lifecycle authority.
"""

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/agent-os-validation.yml"
)


def workflow():
    return WORKFLOW.read_text(encoding="utf-8")


def test_ready_recovery_has_distinct_explicit_dispatch_mode():
    content = workflow()
    assert "ready_recovery:" in content
    assert "mode=ready-recovery" in content
    assert 'if [ "$is_draft" != "true" ]' in content
    assert "mode=final-candidate" in content


def test_ready_recovery_requires_zero_job_source_evidence():
    content = workflow()
    assert "source_validation_run_id:" in content
    assert "action_required" in content
    assert "ready-recovery" in content


def test_recovery_binds_current_main_and_exact_candidate_head():
    content = workflow()
    assert "expected_main_sha:" in content
    assert "EXPECTED_HEAD_SHA" in content
    assert "GITHUB_SHA" in content
    assert "checked_out_sha" in content


def test_existing_validation_authority_is_preserved():
    content = workflow()
    assert content.count("./scripts/validate-all.sh") == 1
    assert "agent-os/authoritative-aggregate" in content
    assert "Run aggregate validation" in content
    assert "statuses: write" in content
    assert "contents: write" not in content
    assert "pull-requests: write" not in content


def test_recovery_verifies_failed_run_provenance_and_zero_jobs():
    content = workflow()
    assert "actions/runs/$SOURCE_VALIDATION_RUN_ID" in content
    assert "action_required" in content
    assert 'job_count" != "0"' in content
    assert '.head_sha == $sha' in content
    assert '.head_branch == $branch' in content
    assert 'GITHUB_ACTOR' in content


def test_recovery_does_not_implicitly_allow_non_draft_final_candidate():
    content = workflow()
    assert 'if [ "$READY_RECOVERY" != "true" ]; then' in content
    assert 'if [ "$is_draft" != "true" ]; then' in content
    assert 'if [ "$is_draft" != "false" ]; then' in content
    assert 'if [ "$GITHUB_SHA" != "$EXPECTED_HEAD_SHA" ]' in content


def test_recovery_keeps_existing_single_aggregate_executor():
    content = workflow()
    assert content.count("./scripts/validate-all.sh") == 1
    assert 'mode=ready-recovery' in content
    assert 'mode=final-candidate' in content


def test_ready_recovery_binds_workflow_revision_separately():
    content = workflow()
    assert "expected_workflow_sha:" in content
    assert 'GITHUB_SHA" != "$EXPECTED_WORKFLOW_SHA' in content
    assert 'actual_workflow_sha' in content
    assert 'GITHUB_REF_TYPE' in content


def test_ready_recovery_has_job_local_actions_read():
    content = workflow()
    validate = content.split("  validate:", 1)[1].split(
        "  aggregate-gate:", 1
    )[0]
    assert "actions: read" in validate
    assert "actions: write" not in validate


def test_source_run_must_identify_the_target_pr():
    content = workflow()
    assert '(($prs | length) > 0 and' in content
    assert 'any($prs[]; .number == $pr)' in content


def test_recovery_attempts_use_provider_history():
    content = workflow()
    assert "run-name:" in content
    assert "ready-recovery:{0}:{1}" in content
    assert "actions/workflows/agent-os-validation.yml/runs?" in content
    assert "GITHUB_RUN_ID" in content
    assert "current_run_found" in content
    assert "recovery_attempts" in content


def test_recovery_attempt_limit_matches_canonical_contract():
    import yaml
    from scripts.agent_os_issue_acceptance.zero_job_validation_recovery import (
        MAX_ZERO_JOB_RECOVERY_ATTEMPTS,
    )

    data = yaml.safe_load(workflow())
    configured = int(
        data["jobs"]["validate"]["env"][
            "MAX_READY_RECOVERY_ATTEMPTS"
        ]
    )
    assert configured == MAX_ZERO_JOB_RECOVERY_ATTEMPTS == 2


def test_ready_recovery_has_scoped_concurrency():
    content = workflow()
    assert "ready-recovery-{0}-{1}" in content
    assert "cancel-in-progress:" in content
    assert "github.run_id" in content


def test_source_run_uses_stable_workflow_identity():
    content = workflow()
    assert '.workflow_id == $workflow_id' in content
    assert 'expected_workflow_id=' in content
    assert '.name == "Agent OS Validation Gate"' not in content


def test_retry_history_cannot_reset_across_branches():
    content = workflow()
    assert (
        'runs?event=workflow_dispatch&per_page=100'
        in content
    )
    assert (
        'runs?event=workflow_dispatch&branch='
        not in content
    )
