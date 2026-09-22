"""Bounded read-only Google Cloud identity inspection."""
from __future__ import annotations

import json
import re
import subprocess
from typing import Callable, Sequence

PROJECT = "agent-os-502614"
PROJECT_NUMBER = "966859826758"
ZONE = "us-central1-a"
INSTANCE = "agent-os-test"
TRANSPORT_PRINCIPAL = "agent-os-transport@agent-os-502614.iam.gserviceaccount.com"
DEFAULT_COMPUTE_SERVICE_ACCOUNT = f"{PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
STOP_PERMISSION = "compute.instances.stop"
TOKEN_CREATOR_ROLE = "roles/iam.serviceAccountTokenCreator"
MAX_SERVICE_ACCOUNTS = 50
_USER_MANAGED_SA_EMAIL = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.iam\.gserviceaccount\.com$", re.ASCII)
Run = Callable[..., subprocess.CompletedProcess[str]]


def _valid_service_account_email(value: object) -> bool:
    if type(value) is not str:
        return False
    return value == DEFAULT_COMPUTE_SERVICE_ACCOUNT or _USER_MANAGED_SA_EMAIL.fullmatch(value) is not None


def _run_json(run: Run, argv: Sequence[str], reason: str) -> object:
    completed = run(tuple(argv), timeout=60)
    if completed.returncode != 0:
        raise ValueError(reason)
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(reason) from exc


def _instance_service_accounts(value: object) -> tuple[list[object], str | None]:
    if type(value) is list:
        return value, None
    if type(value) is not dict:
        return [], "instance-service-account-projection-malformed"
    if "serviceAccounts" not in value or value["serviceAccounts"] is None:
        return [], None
    attached = value["serviceAccounts"]
    if type(attached) is not list:
        return [], "instance-service-account-projection-malformed"
    return attached, None


def _service_accounts(value: object) -> tuple[list[dict[str, object]], str | None]:
    if type(value) is not list:
        return [], "service-account-inventory-malformed"
    if len(value) > MAX_SERVICE_ACCOUNTS:
        return [], "service-account-inventory-over-bound"
    clean: list[dict[str, object]] = []
    for item in value:
        if type(item) is not dict:
            return [], "service-account-inventory-malformed"
        email = item.get("email")
        display_name = item.get("displayName", "")
        disabled = item.get("disabled", False)
        if not _valid_service_account_email(email):
            return [], "service-account-inventory-malformed"
        if type(display_name) is not str or type(disabled) is not bool:
            return [], "service-account-inventory-malformed"
        clean.append({"email": email, "display_name": display_name[:160], "disabled": disabled})
    clean.sort(key=lambda item: str(item["email"]))
    return clean, None


def _bindings(value: object, *, reject_conditions: bool = False) -> list[dict[str, object]]:
    if type(value) is not dict:
        raise ValueError("iam-policy-malformed")
    bindings = value.get("bindings", [])
    if type(bindings) is not list:
        raise ValueError("iam-policy-malformed")
    clean: list[dict[str, object]] = []
    for binding in bindings:
        if type(binding) is not dict:
            raise ValueError("iam-policy-malformed")
        role = binding.get("role")
        members = binding.get("members", [])
        if type(role) is not str or type(members) is not list or any(type(member) is not str for member in members):
            raise ValueError("iam-policy-malformed")
        if reject_conditions and "condition" in binding:
            raise ValueError("iam-policy-conditional-binding-unsupported")
        clean.append({"role": role, "members": members})
    return clean


def _runtime_member(runtime_email: str) -> str:
    return f"serviceAccount:{runtime_email}"


def _relevant_binding(bindings: list[dict[str, object]], runtime_email: str) -> bool:
    member = _runtime_member(runtime_email)
    return any(binding["role"] == TOKEN_CREATOR_ROLE and member in binding["members"] for binding in bindings)


def _stop_permission_base() -> dict[str, object]:
    return {
        "permission": STOP_PERMISSION,
        "effective": "unknown",
        "principal": TRANSPORT_PRINCIPAL,
        "resource": {"project": PROJECT, "zone": ZONE, "instance": INSTANCE},
        "binding_source": None,
        "source_scope": "unknown",
        "inheritance": "unknown",
        "readback_state": "unavailable",
        "reason_codes": ["stop-permission-unavailable"],
    }


def _effective_stop_permission(run: Run) -> dict[str, object]:
    evidence = _stop_permission_base()
    member = _runtime_member(TRANSPORT_PRINCIPAL)
    try:
        # The instance permission probe is GA in current Google Cloud CLI.
        # Keep the probe on the stable track so the governed runtime does not
        # depend on beta command registration. It remains fixed-resource,
        # read-only, and evaluates the current authenticated caller.
        allowed = _run_json(run, (
            "gcloud", "compute", "instances", "test-iam-permissions", INSTANCE,
            "--project", PROJECT, "--zone", ZONE,
            "--permissions", STOP_PERMISSION,
            "--format=json(permissions)",
        ), "stop-permission-command-or-read-failed")
        if type(allowed) is not dict or type(allowed.get("permissions", [])) is not list:
            raise ValueError("stop-permission-response-malformed")
        permissions = allowed.get("permissions", [])
        if any(type(permission) is not str for permission in permissions):
            raise ValueError("stop-permission-response-malformed")
        unexpected = [permission for permission in permissions if permission != STOP_PERMISSION]
        if unexpected:
            raise ValueError("stop-permission-response-unsupported")

        policy = _run_json(run, (
            "gcloud", "projects", "get-iam-policy", PROJECT, "--format=json(bindings)",
        ), "stop-permission-project-policy-read-failed")
        bindings = _bindings(policy, reject_conditions=True)
        direct = [binding for binding in bindings if member in binding["members"]]

        if STOP_PERMISSION not in permissions:
            evidence.update({
                "effective": False,
                "source_scope": "instance",
                "inheritance": "none",
                "readback_state": "current",
                "reason_codes": ["stop-permission-denied"],
            })
            return evidence

        supporting: list[str] = []
        for binding in direct:
            role = str(binding["role"])
            role_description = _run_json(run, (
                "gcloud", "iam", "roles", "describe", role,
                "--format=json(name,includedPermissions)",
            ), "stop-permission-role-description-read-failed")
            if type(role_description) is not dict:
                raise ValueError("stop-permission-role-description-malformed")
            role_name = role_description.get("name")
            included = role_description.get("includedPermissions")
            if type(role_name) is not str or role_name != role or type(included) is not list or any(type(item) is not str for item in included):
                raise ValueError("stop-permission-role-description-malformed")
            if STOP_PERMISSION in included:
                supporting.append(role)

        if len(supporting) == 1:
            evidence.update({
                "effective": True,
                "binding_source": {"role": supporting[0], "member": member, "resource": f"projects/{PROJECT}"},
                "source_scope": "project",
                "inheritance": "direct",
                "readback_state": "current",
                "reason_codes": ["stop-permission-effective-direct-project-binding"],
            })
            return evidence
        if len(supporting) > 1:
            evidence.update({"readback_state": "ambiguous", "reason_codes": ["stop-permission-binding-source-ambiguous"]})
            return evidence

        evidence.update({
            "source_scope": "unknown",
            "inheritance": "unknown",
            "readback_state": "current",
            "reason_codes": ["stop-permission-effective-source-not-bounded"],
        })
        return evidence
    except ValueError as exc:
        reason = str(exc)[:160]
        evidence["readback_state"] = "ambiguous" if "ambiguous" in reason else "unavailable"
        evidence["reason_codes"] = [reason]
        return evidence


def collect_cloud_identity(run: Run) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": ["cloud-identity-unavailable"],
        "project": PROJECT,
        "zone": ZONE,
        "instance": INSTANCE,
        "vm_runtime_identity": {"status": "missing", "email": None, "scopes": []},
        "service_accounts": [],
        "impersonation_relationships": [],
        "effective_stop_permission": _stop_permission_base(),
        "spreadsheet_access_verification": {"status": "not-performed", "reason": "requires-separately-authorized-workspace-access-verification"},
        "credential_token_operation_performed": False,
        "google_workspace_operation_performed": False,
        "external_write_performed": False,
    }
    try:
        # Ask gcloud for the field value rather than a projected JSON object.
        # The live surface can serialize --format=json(serviceAccounts) as a
        # projection object shape that is not stable across gcloud versions.
        instance = _run_json(run, (
            "gcloud", "compute", "instances", "describe", INSTANCE,
            "--project", PROJECT, "--zone", ZONE,
            "--format=json",
        ), "instance-service-account-read-failed")
        if type(instance) is not dict:
            base["reason_codes"] = ["instance-service-account-projection-malformed"]
            return base
        attached, shape_error = _instance_service_accounts(instance)
        if shape_error is not None:
            base["reason_codes"] = [shape_error]
            return base
        if len(attached) == 0:
            base["reason_codes"] = ["runtime-service-account-missing"]
            base["effective_stop_permission"] = _effective_stop_permission(run)
            return base
        if len(attached) != 1:
            base["reason_codes"] = ["runtime-service-account-ambiguous"]
            return base
        if type(attached[0]) is not dict:
            base["reason_codes"] = ["instance-service-account-object-malformed"]
            return base
        runtime_email = attached[0].get("email")
        scopes = attached[0].get("scopes", [])
        if not _valid_service_account_email(runtime_email):
            base["reason_codes"] = ["instance-service-account-email-rejected"]
            return base
        if type(scopes) is not list or any(type(scope) is not str for scope in scopes):
            base["reason_codes"] = ["instance-service-account-scopes-malformed"]
            return base
        base["vm_runtime_identity"] = {"status": "verified", "email": runtime_email, "scopes": sorted(set(scopes))}

        inventory_raw = _run_json(run, (
            "gcloud", "iam", "service-accounts", "list", "--project", PROJECT,
            "--format=json(email,displayName,disabled)",
        ), "service-account-inventory-read-failed")
        inventory, error = _service_accounts(inventory_raw)
        if error is not None:
            base["reason_codes"] = [error]
            return base
        base["service_accounts"] = inventory

        relationships: list[dict[str, object]] = []
        project_policy = _run_json(run, (
            "gcloud", "projects", "get-iam-policy", PROJECT, "--format=json(bindings)",
        ), "project-iam-policy-read-failed")
        if _relevant_binding(_bindings(project_policy), runtime_email):
            relationships.append({"principal": runtime_email, "target_service_account": None, "role": TOKEN_CREATOR_ROLE, "resource_level": "project", "target_service_account_scoped": False})
        for account in inventory:
            target_email = str(account["email"])
            policy = _run_json(run, (
                "gcloud", "iam", "service-accounts", "get-iam-policy", target_email,
                "--project", PROJECT, "--format=json(bindings)",
            ), "service-account-iam-policy-read-failed")
            if _relevant_binding(_bindings(policy), runtime_email):
                relationships.append({"principal": runtime_email, "target_service_account": target_email, "role": TOKEN_CREATOR_ROLE, "resource_level": "service-account", "target_service_account_scoped": True})
        relationships.sort(key=lambda item: (str(item["resource_level"]), str(item["target_service_account"])))
        base["impersonation_relationships"] = relationships
        base["effective_stop_permission"] = _effective_stop_permission(run)
        base["status"] = "observed"
        base["reason_codes"] = ["cloud-identity-observed"]
        return base
    except ValueError as exc:
        base["reason_codes"] = [str(exc)[:160]]
        return base


__all__ = ["DEFAULT_COMPUTE_SERVICE_ACCOUNT", "INSTANCE", "MAX_SERVICE_ACCOUNTS", "PROJECT", "PROJECT_NUMBER", "STOP_PERMISSION", "TOKEN_CREATOR_ROLE", "TRANSPORT_PRINCIPAL", "ZONE", "collect_cloud_identity"]
