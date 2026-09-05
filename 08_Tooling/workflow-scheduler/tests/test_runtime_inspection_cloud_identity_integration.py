from __future__ import annotations

from types import SimpleNamespace

import workflow_scheduler.governance.gce_gcloud_adapter as live
from workflow_scheduler.governance.gce_control_path import VmState
from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event


def _ingress():
    event = {
        "action": "created",
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 1940},
        "comment": {"id": 5554980781, "body": "/agent-os inspect-runtime", "user": {"login": "Blummer92"}},
        "sender": {"login": "Blummer92"},
    }
    return admit_issue_comment_event(
        event,
        expected_repository="Blummer92/agent-os",
        allowed_actor="Blummer92",
        run_attempt=1,
    )


def _claims():
    return {
        "repository": "Blummer92/agent-os",
        "repository_owner": "Blummer92",
        "workflow_ref": live.WORKFLOW_REF,
        "ref": "refs/heads/main",
        "aud": live.WIF_PROVIDER,
    }


class Adapter:
    def __init__(self, state=VmState.RUNNING):
        self.state = state
        self.calls = []

    def observe_state(self, resource):
        self.calls.append("observe")
        return self.state

    def inspect_runtime(self, resource):
        self.calls.append("inspect")
        return {
            "schema_version": "1.0",
            "status": "observed",
            "reason_codes": ["runtime-context-observed"],
            "project": live.PROJECT,
            "zone": live.ZONE,
            "instance": live.INSTANCE,
            "interpreter": live.HOST_PYTHON,
            "execution_authorized": False,
            "scheduler_invoked": False,
            "discovery_invoked": False,
            "resume_invoked": False,
            "side_effects_performed": False,
        }


def _result(stdout: str):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr="")


def test_runtime_inspection_dispatch_includes_cloud_identity(monkeypatch):
    calls = []

    def fake_run(argv, *, timeout=60):
        argv = tuple(argv)
        calls.append(argv)
        if argv[:4] == ("gcloud", "compute", "instances", "describe"):
            return _result('{"serviceAccounts":[{"email":"runtime@agent-os-502614.iam.gserviceaccount.com","scopes":["https://www.googleapis.com/auth/cloud-platform"]}]}')
        if argv[:4] == ("gcloud", "iam", "service-accounts", "list"):
            return _result('[{"email":"visual-asset-reader@agent-os-502614.iam.gserviceaccount.com","displayName":"Visual Asset Reader","disabled":false}]')
        if argv[:3] == ("gcloud", "projects", "get-iam-policy"):
            return _result('{"bindings":[]}')
        if argv[:4] == ("gcloud", "iam", "service-accounts", "get-iam-policy"):
            return _result('{"bindings":[{"role":"roles/iam.serviceAccountTokenCreator","members":["serviceAccount:runtime@agent-os-502614.iam.gserviceaccount.com"]}]}')
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(live, "_run", fake_run)
    result = live.execute_transport(_ingress(), claims=_claims(), adapter=Adapter())

    assert set(result) == {"runtime_inspection", "cloud_identity"}
    cloud = result["cloud_identity"]
    assert cloud["status"] == "observed"
    assert cloud["vm_runtime_identity"]["email"] == "runtime@agent-os-502614.iam.gserviceaccount.com"
    assert cloud["service_accounts"][0]["email"] == "visual-asset-reader@agent-os-502614.iam.gserviceaccount.com"
    assert cloud["impersonation_relationships"] == [{
        "principal": "runtime@agent-os-502614.iam.gserviceaccount.com",
        "target_service_account": "visual-asset-reader@agent-os-502614.iam.gserviceaccount.com",
        "role": "roles/iam.serviceAccountTokenCreator",
        "resource_level": "service-account",
        "target_service_account_scoped": True,
    }]
    assert cloud["spreadsheet_access_verification"] == {
        "status": "not-performed",
        "reason": "requires-separately-authorized-workspace-access-verification",
    }
    assert cloud["credential_token_operation_performed"] is False
    assert cloud["google_workspace_operation_performed"] is False
    assert cloud["external_write_performed"] is False
    assert all("sheets" not in " ".join(command).lower() for command in calls)
    assert all("drive" not in " ".join(command).lower() for command in calls)
    assert all("generate-access-token" not in " ".join(command).lower() for command in calls)


def test_stopped_vm_blocks_before_cloud_identity_reads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("cloud identity read must not occur for stopped VM")

    monkeypatch.setattr(live, "_run", forbidden)
    adapter = Adapter(VmState.STOPPED)
    result = live.execute_transport(_ingress(), claims=_claims(), adapter=adapter)

    assert adapter.calls == ["observe"]
    assert set(result) == {"runtime_inspection"}
    assert result["runtime_inspection"]["reason_codes"] == ["host-not-running"]


def test_rejected_claims_block_before_cloud_identity_reads(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("cloud identity read must not occur for rejected claims")

    monkeypatch.setattr(live, "_run", forbidden)
    adapter = Adapter()
    claims = _claims()
    claims["repository"] = "other/repo"
    result = live.execute_transport(_ingress(), claims=claims, adapter=adapter)

    assert adapter.calls == []
    assert set(result) == {"runtime_inspection"}
    assert result["runtime_inspection"]["reason_codes"] == ["claims-rejected"]
