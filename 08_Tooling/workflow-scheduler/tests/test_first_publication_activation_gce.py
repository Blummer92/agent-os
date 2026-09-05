from __future__ import annotations

from workflow_scheduler.governance.gce_gcloud_adapter import RESOURCE, WIF_PROVIDER, WORKFLOW_REF, execute_transport
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import IssueCommentIngressResult

CAPSULE = "pre-publication-evidence:" + "a" * 64
HANDOFF = "executor-handoff:" + "b" * 64


def ingress() -> IssueCommentIngressResult:
    return IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason="accepted-first-publication-activation-envelope",
        repository="Blummer92/agent-os",
        issue_number=1239,
        comment_id=1,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:" + "c" * 64,
        run_attempt=1,
        source_capsule_id_or_none=CAPSULE,
    )


def claims() -> dict[str, object]:
    return {
        "repository": "Blummer92/agent-os",
        "repository_owner": "Blummer92",
        "workflow_ref": WORKFLOW_REF,
        "ref": "refs/heads/main",
        "aud": WIF_PROVIDER,
    }


class Adapter:
    def __init__(self, state: VmState = VmState.RUNNING) -> None:
        self.state = state
        self.activated: list[str] = []

    def observe_state(self, resource):
        assert resource == RESOURCE
        return self.state

    def probe_activation_ready(self, resource):
        assert resource == RESOURCE
        return True

    def activate_first_publication(self, resource, *, source_capsule_id):
        assert resource == RESOURCE
        self.activated.append(source_capsule_id)
        return {
            "schema_version": "1.0",
            "source_capsule_id": source_capsule_id,
            "handoff_id": HANDOFF,
            "publication_invoked": True,
            "scheduler_invoked": False,
            "execution_lease_acquired": False,
            "resume_invoked": False,
        }


def test_activation_uses_exact_capsule_once_and_never_resumes() -> None:
    adapter = Adapter()
    result = execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.activated == [CAPSULE]
    evidence = result["first_publication_activation"]
    assert evidence["handoff_id"] == HANDOFF
    assert evidence["scheduler_invoked"] is False
    assert evidence["execution_lease_acquired"] is False
    assert evidence["resume_invoked"] is False


def test_activation_does_not_start_stopped_vm() -> None:
    adapter = Adapter(VmState.STOPPED)
    result = execute_transport(ingress(), claims=claims(), adapter=adapter)
    assert adapter.activated == []
    evidence = result["first_publication_activation"]
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["host-not-running"]
    assert evidence["scheduler_invoked"] is False


def test_activation_rejects_oidc_claim_drift_before_host_call() -> None:
    adapter = Adapter()
    bad = claims(); bad["ref"] = "refs/heads/other"
    result = execute_transport(ingress(), claims=bad, adapter=adapter)
    assert adapter.activated == []
    assert result["first_publication_activation"]["reason_codes"] == ["claims-rejected"]
