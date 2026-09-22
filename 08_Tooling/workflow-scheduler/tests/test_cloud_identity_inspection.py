from __future__ import annotations

import json
from types import SimpleNamespace

from workflow_scheduler.governance import cloud_identity_inspection as live

RUNTIME = "agent-os-runtime@agent-os-502614.iam.gserviceaccount.com"
READER = "visual-asset-reader@agent-os-502614.iam.gserviceaccount.com"
STOP_ROLE = "roles/compute.instanceAdmin.v1"


def result(payload, code=0, stderr=""):
    return SimpleNamespace(returncode=code, stdout=json.dumps(payload), stderr=stderr)


def fake_run_factory(*, inventory=None, project_bindings=None, reader_bindings=None, instance_payload=None, stop_permissions=None, stop_role_permissions=None, stop_code=0):
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
    stop_permissions = stop_permissions if stop_permissions is not None else []
    stop_role_permissions = stop_role_permissions if stop_role_permissions is not None else {}
    calls = []

    def run(argv, *, timeout=60):
        argv = tuple(argv); calls.append(argv)
        if argv[:4] == ("gcloud", "compute", "instances", "describe"):
            return result(instance_payload)
        if argv[:4] == ("gcloud", "compute", "instances", "test-iam-permissions"):
            return result({"permissions": stop_permissions}, code=stop_code, stderr="SECRET provider transcript must not escape")
        if argv[:5] == ("gcloud", "iam", "service-accounts", "list", "--project"):
            return result(inventory)
        if argv[:5] == ("gcloud", "projects", "get-iam-policy", live.PROJECT, "--format=json(bindings)"):
            return result({"bindings": project_bindings})
        if argv[:4] == ("gcloud", "iam", "service-accounts", "get-iam-policy"):
            target = argv[4]
            return result({"bindings": reader_bindings if target == READER else []})
        if argv[:4] == ("gcloud", "iam", "roles", "describe"):
            role = argv[4]
            return result({"name": role, "includedPermissions": stop_role_permissions.get(role, [])})
        raise AssertionError(argv)
    return run, calls


def test_collects_fixed_sanitized_identity_and_target_scoped_relationship():
    run, calls = fake_run_factory()
    evidence = live.collect_cloud_identity(run)
    assert evidence["schema_version"] == "1.0"
    assert evidence["status"] == "observed"
    assert evidence["vm_runtime_identity"] == {"status": "verified", "email": RUNTIME, "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}
    assert evidence["impersonation_relationships"] == [{"principal": RUNTIME, "target_service_account": READER, "role": live.TOKEN_CREATOR_ROLE, "resource_level": "service-account", "target_service_account_scoped": True}]
    assert evidence["effective_stop_permission"]["effective"] is False
    assert evidence["external_write_performed"] is False
    rendered = json.dumps(evidence).lower()
    for forbidden in ("access_token", "refresh_token", "private_key", "client_secret", "provider transcript"):
        assert forbidden not in rendered
    assert all("sheets" not in " ".join(call).lower() for call in calls)
    assert all("drive" not in " ".join(call).lower() for call in calls)


def test_live_default_compute_service_account_shape_is_accepted():
    payload = {"serviceAccounts": [{"email": live.DEFAULT_COMPUTE_SERVICE_ACCOUNT, "scopes": ["https://www.googleapis.com/auth/cloud-platform"]}]}
    inventory = [{"email": live.DEFAULT_COMPUTE_SERVICE_ACCOUNT, "displayName": "Compute Engine default service account", "disabled": False}]
    run, _ = fake_run_factory(instance_payload=payload, inventory=inventory, reader_bindings=[])
    evidence = live.collect_cloud_identity(run)
    assert evidence["status"] == "observed"
    assert evidence["vm_runtime_identity"]["email"] == live.DEFAULT_COMPUTE_SERVICE_ACCOUNT


def test_instance_diagnostics_distinguish_projection_object_email_and_scopes():
    cases = [
        ("unexpected", "instance-service-account-projection-malformed"),
        ({"serviceAccounts": {}}, "instance-service-account-projection-malformed"),
        ({"serviceAccounts": ["bad"]}, "instance-service-account-object-malformed"),
        ({"serviceAccounts": [{"email": "123-compute@developer.gserviceaccount.com", "scopes": []}]}, "instance-service-account-email-rejected"),
        ({"serviceAccounts": [{"email": RUNTIME, "scopes": {}}]}, "instance-service-account-scopes-malformed"),
    ]
    for payload, reason in cases:
        run, _ = fake_run_factory(instance_payload=payload)
        evidence = live.collect_cloud_identity(run)
        assert evidence["reason_codes"] == [reason]
        assert evidence["external_write_performed"] is False


def test_missing_runtime_identity_preserves_missing_state_but_still_checks_transport_stop_permission():
    run, calls = fake_run_factory(instance_payload={"serviceAccounts": []}, stop_permissions=[])
    evidence = live.collect_cloud_identity(run)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["runtime-service-account-missing"]
    assert evidence["vm_runtime_identity"] == {"status": "missing", "email": None, "scopes": []}
    assert evidence["effective_stop_permission"]["effective"] is False
    assert evidence["effective_stop_permission"]["reason_codes"] == ["stop-permission-denied"]
    assert any(call[:5] == ("gcloud", "compute", "instances", "test-iam-permissions") for call in calls)
    assert not any(call[:4] == ("gcloud", "iam", "service-accounts", "list") for call in calls)


def test_missing_runtime_identity_preserves_independent_positive_stop_proof():
    member = f"serviceAccount:{live.TRANSPORT_PRINCIPAL}"
    run, _ = fake_run_factory(
        instance_payload={"serviceAccounts": []},
        project_bindings=[{"role": STOP_ROLE, "members": [member]}],
        stop_permissions=[live.STOP_PERMISSION],
        stop_role_permissions={STOP_ROLE: [live.STOP_PERMISSION]},
    )
    evidence = live.collect_cloud_identity(run)
    assert evidence["reason_codes"] == ["runtime-service-account-missing"]
    assert evidence["vm_runtime_identity"]["status"] == "missing"
    assert evidence["effective_stop_permission"]["effective"] is True
    assert evidence["effective_stop_permission"]["reason_codes"] == ["stop-permission-effective-direct-project-binding"]


def test_ambiguous_runtime_identity_is_not_guessed():
    run, _ = fake_run_factory(instance_payload={"serviceAccounts": [{"email": RUNTIME, "scopes": []}, {"email": READER, "scopes": []}]})
    assert live.collect_cloud_identity(run)["reason_codes"] == ["runtime-service-account-ambiguous"]


def test_commands_are_fixed_to_canonical_target_and_current_transport_caller():
    run, calls = fake_run_factory()
    live.collect_cloud_identity(run)
    assert calls[0] == ("gcloud", "compute", "instances", "describe", live.INSTANCE, "--project", live.PROJECT, "--zone", live.ZONE, "--format=json")
    stop_call = next(call for call in calls if call[:5] == ("gcloud", "compute", "instances", "test-iam-permissions"))
    assert stop_call == ("gcloud", "beta", "compute", "instances", "test-iam-permissions", live.INSTANCE, "--project", live.PROJECT, "--zone", live.ZONE, "--permissions", live.STOP_PERMISSION, "--format=json(permissions)")


def test_stop_permission_command_failure_is_finite_and_redacted():
    run, _ = fake_run_factory(stop_code=1)
    proof = live.collect_cloud_identity(run)["effective_stop_permission"]
    assert proof["effective"] == "unknown"
    assert proof["readback_state"] == "unavailable"
    assert proof["reason_codes"] == ["stop-permission-command-or-read-failed"]
    assert "provider transcript" not in json.dumps(proof).lower()


def test_effective_stop_permission_positive_direct_project_binding():
    member = f"serviceAccount:{live.TRANSPORT_PRINCIPAL}"
    project = [{"role": STOP_ROLE, "members": [member]}]
    run, _ = fake_run_factory(project_bindings=project, stop_permissions=[live.STOP_PERMISSION], stop_role_permissions={STOP_ROLE: [live.STOP_PERMISSION]})
    proof = live.collect_cloud_identity(run)["effective_stop_permission"]
    assert proof["effective"] is True
    assert proof["binding_source"] == {"role": STOP_ROLE, "member": member, "resource": f"projects/{live.PROJECT}"}
    assert proof["reason_codes"] == ["stop-permission-effective-direct-project-binding"]


def test_effective_stop_permission_negative_does_not_infer_from_policy():
    member = f"serviceAccount:{live.TRANSPORT_PRINCIPAL}"
    run, _ = fake_run_factory(project_bindings=[{"role": STOP_ROLE, "members": [member]}], stop_permissions=[])
    proof = live.collect_cloud_identity(run)["effective_stop_permission"]
    assert proof["effective"] is False
    assert proof["reason_codes"] == ["stop-permission-denied"]


def test_effective_stop_permission_without_bounded_binding_source_is_unknown():
    run, _ = fake_run_factory(stop_permissions=[live.STOP_PERMISSION])
    proof = live.collect_cloud_identity(run)["effective_stop_permission"]
    assert proof["effective"] == "unknown"
    assert proof["reason_codes"] == ["stop-permission-effective-source-not-bounded"]


def test_multiple_supporting_bindings_fail_closed_as_ambiguous():
    member = f"serviceAccount:{live.TRANSPORT_PRINCIPAL}"
    roles = ["roles/custom.stopOne", "roles/custom.stopTwo"]
    run, _ = fake_run_factory(project_bindings=[{"role": role, "members": [member]} for role in roles], stop_permissions=[live.STOP_PERMISSION], stop_role_permissions={role: [live.STOP_PERMISSION] for role in roles})
    proof = live.collect_cloud_identity(run)["effective_stop_permission"]
    assert proof["effective"] == "unknown"
    assert proof["reason_codes"] == ["stop-permission-binding-source-ambiguous"]


def test_conditional_binding_only_fails_stop_proof_closed():
    member = f"serviceAccount:{live.TRANSPORT_PRINCIPAL}"
    project = [{"role": STOP_ROLE, "members": [member], "condition": {"expression": "true"}}]
    run, _ = fake_run_factory(project_bindings=project, stop_permissions=[live.STOP_PERMISSION])
    proof = live.collect_cloud_identity(run)["effective_stop_permission"]
    assert proof["effective"] == "unknown"
    assert proof["reason_codes"] == ["iam-policy-conditional-binding-unsupported"]


def test_inventory_over_bound_and_malformed_fail_closed():
    inventory = [{"email": f"sa-{i}@agent-os-502614.iam.gserviceaccount.com", "displayName": "x", "disabled": False} for i in range(live.MAX_SERVICE_ACCOUNTS + 1)]
    run, _ = fake_run_factory(inventory=inventory)
    assert live.collect_cloud_identity(run)["reason_codes"] == ["service-account-inventory-over-bound"]
    run, _ = fake_run_factory(inventory=[{"displayName": "missing email", "disabled": False}])
    assert live.collect_cloud_identity(run)["reason_codes"] == ["service-account-inventory-malformed"]


def test_failed_initial_cloud_read_returns_bounded_non_authorizing_state():
    def failed(argv, *, timeout=60):
        return SimpleNamespace(returncode=1, stdout="", stderr="SECRET")
    evidence = live.collect_cloud_identity(failed)
    assert evidence["status"] == "needs-decision"
    assert evidence["reason_codes"] == ["instance-service-account-read-failed"]
    assert "secret" not in json.dumps(evidence).lower()
    assert evidence["external_write_performed"] is False
