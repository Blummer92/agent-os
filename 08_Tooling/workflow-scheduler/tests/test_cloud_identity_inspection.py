from __future__ import annotations

import json
from types import SimpleNamespace

from workflow_scheduler.governance import cloud_identity_inspection as live

RUNTIME = "agent-os-runtime@agent-os-502614.iam.gserviceaccount.com"
READER = "visual-asset-reader@agent-os-502614.iam.gserviceaccount.com"


def result(payload, code=0):
    return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr="")


def fake_run_factory(*, inventory=None, project_bindings=None, reader_bindings=None, instance_payload=None):
    inventory = inventory if inventory is not None else [
        {"email": RUNTIME, "displayName": "runtime", "disabled": False},
        {"email": READER, "displayName": "Visual Asset reader", "disabled": False},
    ]
    project_bindings = project_bindings if project_bindings is not None else []
    reader_bindings = reader_bindings if reader_bindings is not None else [
        {"role": live.TOKEN_CREATOR_ROLE, "members": [f"serviceAccount:{RUNTIME}"]}
    ]
    instance_payload = instance_payload if instance_payload is not None else {
        "serviceAccounts": [{"email": RUNTIME, "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}]
    }
    calls = []

    def run(argv, *, timeout=60):
        argv = tuple(argv); calls.append(argv)
        if argv[:4] == ("gcloud", "compute", "instances", "describe"):
            return result(instance_payload)
        if argv[:4] == ("gcloud", "iam", "service-accounts", "list"):
            return result(inventory)
        if argv[:4] == ("gcloud", "projects", "get-iam-policy", live.PROJECT):
            return result({"bindings": project_bindings})
        if argv[:4] == ("gcloud", "iam", "service-accounts", "get-iam-policy"):
            target = argv[4]
            return result({"bindings": reader_bindings if target == READER else []})
        raise AssertionError(argv)
    return run, calls


def test_collects_fixed_sanitized_identity_and_target_scoped_relationship():
    run, calls = fake_run_factory()
    evidence = live.collect_cloud_identity(run)
    assert evidence["status"] == "observed"
    assert evidence["vm_runtime_identity"] == {"status": "verified", "email": RUNTIME, "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}
    assert evidence["impersonation_relationships"] == [{"principal": RUNTIME, "target_service_account": READER, "role": live.TOKEN_CREATOR_ROLE, "resource_level": "service-account", "target_service_account_scoped": True}]
    assert evidence["spreadsheet_access_verification"] == {"status": "not-performed", "reason": "requires-separately-authorized-workspace-access-verification"}
    assert evidence["credential_token_operation_performed"] is False
    assert evidence["google_workspace_operation_performed"] is False
    assert evidence["external_write_performed"] is False
    rendered = json.dumps(evidence).lower()
    for forbidden in ("access_token", "refresh_token", "private_key", "client_secret"):
        assert forbidden not in rendered
    assert all("sheets" not in " ".join(call).lower() for call in calls)
    assert all("drive" not in " ".join(call).lower() for call in calls)


def test_direct_projected_service_account_list_is_normalized():
    projected = [{"email": RUNTIME, "scopes": ["scope-b", "scope-a", "scope-a"]}]
    run, _ = fake_run_factory(instance_payload=projected)
    evidence = live.collect_cloud_identity(run)
    assert evidence["status"] == "observed"
    assert evidence["vm_runtime_identity"] == {"status": "verified", "email": RUNTIME, "scopes": ["scope-a", "scope-b"]}


def test_null_or_omitted_projection_is_missing_not_malformed():
    for payload in ({}, {"serviceAccounts": None}):
        run, calls = fake_run_factory(instance_payload=payload)
        evidence = live.collect_cloud_identity(run)
        assert evidence["reason_codes"] == ["runtime-service-account-missing"]
        assert evidence["vm_runtime_identity"]["email"] is None
        assert len(calls) == 1


def test_malformed_projected_service_account_shape_fails_closed():
    for payload in ("unexpected", {"serviceAccounts": {}}, [{"email": 7, "scopes": []}]):
        run, _ = fake_run_factory(instance_payload=payload)
        evidence = live.collect_cloud_identity(run)
        assert evidence["reason_codes"] == ["instance-service-account-evidence-malformed"]
        assert evidence["external_write_performed"] is False


def test_commands_are_fixed_to_canonical_project_instance_and_zone():
    run, calls = fake_run_factory()
    live.collect_cloud_identity(run)
    assert calls[0] == ("gcloud", "compute", "instances", "describe", live.INSTANCE, "--project", live.PROJECT, "--zone", live.ZONE, "--format=json(serviceAccounts)")
    assert calls[1] == ("gcloud", "iam", "service-accounts", "list", "--project", live.PROJECT, "--format=json(email,displayName,disabled)")


def test_project_wide_token_creator_is_distinguished_from_target_scoped():
    project = [{"role": live.TOKEN_CREATOR_ROLE, "members": [f"serviceAccount:{RUNTIME}"]}]
    run, _ = fake_run_factory(project_bindings=project, reader_bindings=[])
    evidence = live.collect_cloud_identity(run)
    assert evidence["impersonation_relationships"] == [{"principal": RUNTIME, "target_service_account": None, "role": live.TOKEN_CREATOR_ROLE, "resource_level": "project", "target_service_account_scoped": False}]


def test_unrelated_iam_bindings_are_not_emitted():
    project = [{"role": "roles/viewer", "members": [f"serviceAccount:{RUNTIME}"]}]
    reader = [{"role": live.TOKEN_CREATOR_ROLE, "members": ["serviceAccount:other@example.iam.gserviceaccount.com"]}]
    run, _ = fake_run_factory(project_bindings=project, reader_bindings=reader)
    assert live.collect_cloud_identity(run)["impersonation_relationships"] == []


def test_inventory_over_bound_fails_closed_before_iam_reads():
    inventory = [{"email": f"sa-{i}@agent-os-502614.iam.gserviceaccount.com", "displayName": "x", "disabled": False} for i in range(live.MAX_SERVICE_ACCOUNTS + 1)]
    run, calls = fake_run_factory(inventory=inventory)
    evidence = live.collect_cloud_identity(run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["service-account-inventory-over-bound"]
    assert len(calls) == 2


def test_malformed_inventory_fails_closed():
    run, _ = fake_run_factory(inventory=[{"displayName": "missing email", "disabled": False}])
    assert live.collect_cloud_identity(run)["reason_codes"] == ["service-account-inventory-malformed"]


def test_missing_or_ambiguous_runtime_identity_is_not_guessed():
    run, _ = fake_run_factory(instance_payload={"serviceAccounts": []})
    evidence = live.collect_cloud_identity(run)
    assert evidence["reason_codes"] == ["runtime-service-account-missing"]
    assert evidence["vm_runtime_identity"]["email"] is None
    run, _ = fake_run_factory(instance_payload={"serviceAccounts": [{"email": RUNTIME, "scopes": []}, {"email": READER, "scopes": []}]})
    evidence = live.collect_cloud_identity(run)
    assert evidence["reason_codes"] == ["runtime-service-account-ambiguous"]
    assert evidence["vm_runtime_identity"]["email"] is None


def test_failed_cloud_read_returns_bounded_non_authorizing_state():
    def failed(argv, *, timeout=60):
        return SimpleNamespace(returncode=1, stdout="", stderr="denied")
    evidence = live.collect_cloud_identity(failed)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["instance-service-account-read-failed"]
    assert evidence["external_write_performed"] is False
