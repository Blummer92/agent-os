"""Workflow wiring contract for the fixed Ready-for-Review admission job (#3446)."""
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/agent-os-governed-invocation.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_ingress_job_skips_ready_admission_trigger():
    condition = _workflow()["jobs"]["ingress"]["if"]
    assert "!startsWith(github.event.comment.body, '/agent-os ready-admit')" in condition
    assert "github.event.issue.pull_request == null" in condition


def test_ready_admission_job_is_read_only_and_owner_scoped():
    job = _workflow()["jobs"]["ready_admission"]
    assert job["permissions"] == {
        "contents": "read", "pull-requests": "read", "checks": "read", "statuses": "read"}
    condition = job["if"]
    assert "github.event.issue.pull_request == null" in condition
    assert "github.event.comment.user.id == 32861845" in condition
    assert "startsWith(github.event.comment.body, '/agent-os ready-admit ')" in condition


def test_ready_admission_job_has_no_write_steps_or_generic_execution():
    text = yaml.safe_dump(_workflow()["jobs"]["ready_admission"])
    for forbidden in ("gh pr", "gh api", "mark_pull_request_ready", "gcloud", "secrets.", "id-token",
                      "--command", "eval ", "bash -c"):
        assert forbidden not in text
    assert "scripts.agent_os_issue_labels.ready_admission_actions" in text
    assert "workflow_scheduler.governance.github_issue_comment_ingress" in text


ORIGINAL_JOBS = ["ingress", "refresh_pr", "ready_admission", "merge_admission"]
# #2410: additional jobs authorized in this workflow: the two
# draft-validation jobs plus the confined Ready-recovery job below. The
# Ready-recovery job is owner-authorized (Option B) and is the only newly
# authorized Actions-write holder besides the draft-validation dispatch
# job; it is recognized here by exact name, never by a broad allowance.
DRAFT_VALIDATION_JOBS = ["draft_validation_dispatch", "draft_validation_receipt"]
READY_RECOVERY_JOBS = ["ready_recovery_dispatch"]


def test_existing_jobs_unchanged_in_shape():
    jobs = list(_workflow()["jobs"])
    # The original four jobs are preserved, in order and first.
    assert jobs[: len(ORIGINAL_JOBS)] == ORIGINAL_JOBS
    # Exactly the authorized #2410 jobs follow, in order; any other job fails closed.
    assert jobs[len(ORIGINAL_JOBS):] == DRAFT_VALIDATION_JOBS + READY_RECOVERY_JOBS


def test_draft_validation_dispatch_job_has_only_the_bounded_permissions():
    job = _workflow()["jobs"]["draft_validation_dispatch"]
    assert job["permissions"] == {
        "actions": "write", "contents": "read", "pull-requests": "read"}


def test_draft_validation_receipt_job_has_no_actions_authority():
    job = _workflow()["jobs"]["draft_validation_receipt"]
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert job["needs"] == "draft_validation_dispatch"


def test_draft_validation_jobs_are_owner_scoped_main_only_and_fixed_form():
    for name in DRAFT_VALIDATION_JOBS:
        condition = _workflow()["jobs"][name]["if"]
        assert "github.event.issue.pull_request == null" in condition
        assert "github.ref == 'refs/heads/main'" in condition
        assert "github.event.comment.user.id == 32861845" in condition
        assert "startsWith(github.event.comment.body, '/agent-os validate-draft ')" in condition
    ingress_condition = _workflow()["jobs"]["ingress"]["if"]
    assert "!startsWith(github.event.comment.body, '/agent-os validate-draft')" in ingress_condition


SERVICE_ACTOR_ID = "199175422"  # chatgpt-codex-connector[bot]


def test_draft_validation_jobs_also_admit_the_service_actor():
    for name in DRAFT_VALIDATION_JOBS:
        condition = _workflow()["jobs"][name]["if"]
        assert f"github.event.comment.user.id == {SERVICE_ACTOR_ID}" in condition


def test_no_other_job_admits_the_service_actor():
    for name, job in _workflow()["jobs"].items():
        if name in DRAFT_VALIDATION_JOBS + READY_RECOVERY_JOBS:
            continue
        assert SERVICE_ACTOR_ID not in yaml.safe_dump(job), name
        assert "chatgpt-codex-connector" not in yaml.safe_dump(job), name


def test_draft_validation_parse_steps_scope_the_service_actor():
    # The parser flag is what confines the app identity to validate-draft;
    # both draft jobs must pass it, and no other job may.
    for name, job in _workflow()["jobs"].items():
        text = yaml.safe_dump(job)
        if name in DRAFT_VALIDATION_JOBS:
            assert "--draft-validation-service-actor" in text, name
            assert "chatgpt-codex-connector[bot]" in text, name
        else:
            assert "--draft-validation-service-actor" not in text, name


def test_only_the_dispatch_job_can_hold_actions_write():
    # Exactly two jobs hold actions: write: the draft-validation dispatch
    # job and the confined Ready-recovery dispatch job. Every other job
    # holding it fails this test; the allowlist is by exact name only.
    actions_write_holders = {"draft_validation_dispatch", "ready_recovery_dispatch"}
    for name, job in _workflow()["jobs"].items():
        grants = job.get("permissions", {})
        if name in actions_write_holders:
            continue
        assert not (isinstance(grants, dict) and grants.get("actions") == "write"), name


def test_draft_validation_jobs_do_not_persist_checkout_credentials():
    # The dispatch job holds actions: write; its checkout must not leave the job
    # token in .git/config for a later-installed dependency to read.
    for name in DRAFT_VALIDATION_JOBS:
        checkouts = [
            step for step in _workflow()["jobs"][name]["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout@")
        ]
        assert checkouts, name
        for step in checkouts:
            assert step.get("with", {}).get("persist-credentials") is False, name


def test_ready_recovery_dispatch_job_has_only_the_bounded_permissions():
    job = _workflow()["jobs"]["ready_recovery_dispatch"]
    assert job["permissions"] == {
        "actions": "write", "contents": "read", "pull-requests": "read"}


def test_ready_recovery_dispatch_job_is_issue_only_and_invokes_governed_ingress():
    # Moved from tests/test_2410_ready_recovery_ingress_workflow.py
    # (test_ready_recovery_job_is_confined_to_one_actions_write_job) when
    # that file's overlapping governed-workflow checks were consolidated:
    # these are the step/condition checks the strong file did not already
    # cover. Permissions, main-only/fixed-form, service-actor scoping and
    # checkout-credential checks remain in the neighbouring tests above.
    job = _workflow()["jobs"]["ready_recovery_dispatch"]
    assert "github.event.issue.pull_request == null" in job["if"]
    step_text = "\n".join(str(step) for step in job["steps"])
    assert "github_issue_comment_ingress" in step_text
    assert "ready_recovery_dispatch" in step_text
    assert "agent-os-ready-recovery-" in step_text


def test_ready_recovery_dispatch_job_is_main_only_and_fixed_form():
    job = _workflow()["jobs"]["ready_recovery_dispatch"]
    condition = job["if"]
    assert "github.event.issue.pull_request == null" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.event.comment.user.id == 32861845" in condition
    assert f"github.event.comment.user.id == {SERVICE_ACTOR_ID}" in condition
    assert "startsWith(github.event.comment.body, '/agent-os recover-ready ')" in condition


def test_ready_recovery_parse_step_scopes_the_service_actor():
    # The parser flag is what confines the app identity to recover-ready;
    # the Ready-recovery job must pass it, must NOT use the validate-draft
    # admission flag, and no other job may pass the recover-ready flag.
    for name, job in _workflow()["jobs"].items():
        text = yaml.safe_dump(job)
        if name in READY_RECOVERY_JOBS:
            assert "--ready-recovery-service-actor" in text, name
            assert "chatgpt-codex-connector[bot]" in text, name
            assert "--draft-validation-service-actor" not in text, name
        else:
            assert "--ready-recovery-service-actor" not in text, name


def test_ready_recovery_dispatch_job_does_not_persist_checkout_credentials():
    # The Ready-recovery job holds actions: write; its checkout must not
    # leave the job token in .git/config for a later-installed dependency
    # to read. Same rule as the draft-validation dispatch job.
    for name in READY_RECOVERY_JOBS:
        checkouts = [
            step for step in _workflow()["jobs"][name]["steps"]
            if str(step.get("uses", "")).startswith("actions/checkout@")
        ]
        assert checkouts, name
        for step in checkouts:
            assert step.get("with", {}).get("persist-credentials") is False, name


def test_generic_ingress_job_excludes_recover_ready():
    ingress_condition = _workflow()["jobs"]["ingress"]["if"]
    assert "!startsWith(github.event.comment.body, '/agent-os recover-ready')" in ingress_condition
