from __future__ import annotations

import json

from workflow_scheduler.governance.codespaces_first_route import (
    resolve_ingress_route,
)


def _transport(reason: str, status: str = "accepted") -> dict:
    return {
        "schema_version": "1.0",
        "status": status,
        "reason": reason,
        "repository": "Blummer92/agent-os",
        "issue_number": 2931,
        "operation": "discover",
    }


def test_discovery_prefers_codespaces_with_gce_fallback() -> None:
    route = resolve_ingress_route(_transport("accepted-discovery-envelope"))
    assert route["preferred"] == "codespaces"
    assert route["gce_fallback_allowed"] is True
    assert route["reason_codes"] == ["codespaces-first-ordinary-operation"]


def test_dev_validation_and_diagnostic_prefer_codespaces() -> None:
    for reason in (
        "accepted-dev-validation-envelope",
        "accepted-codespaces-diagnostic-envelope",
    ):
        route = resolve_ingress_route(_transport(reason))
        assert route["preferred"] == "codespaces"
        assert route["gce_fallback_allowed"] is True


def test_vm_only_capabilities_require_gce() -> None:
    cases = {
        "accepted-runtime-inspection-envelope": "gce-required-fixed-host",
        "accepted-ruleset-admin-envelope": "gce-required-ruleset-admin",
        "accepted-first-publication-activation-envelope": "gce-required-activation",
        "accepted-ppux-projection-envelope": "gce-required-ppux-projection",
        "accepted-notion-read-envelope": "gce-required-notion-read",
        "accepted-envelope": "gce-required-governed-control",
    }
    for reason, expected_code in cases.items():
        route = resolve_ingress_route(_transport(reason))
        assert route["preferred"] == "gce", reason
        assert route["gce_fallback_allowed"] is False, reason
        assert route["reason_codes"] == [expected_code], reason


def test_retired_first_run_validation_envelope_resolves_to_none() -> None:
    # #3101/PR #3233 retired first-run validation: no transport can perform it,
    # so the envelope must fail closed instead of routing to GCE.
    route = resolve_ingress_route(_transport("accepted-first-run-validation-envelope"))
    assert route["preferred"] == "none"
    assert route["gce_fallback_allowed"] is False
    assert route["reason_codes"] == ["route-unknown-envelope"]


def test_non_accepted_envelope_resolves_to_none() -> None:
    for status in ("blocked", "ignored"):
        route = resolve_ingress_route(_transport("accepted-discovery-envelope", status=status))
        assert route["preferred"] == "none"
        assert route["gce_fallback_allowed"] is False
        assert route["reason_codes"] == ["route-no-accepted-envelope"]


def test_unknown_envelope_resolves_to_none() -> None:
    route = resolve_ingress_route(_transport("accepted-something-new-envelope"))
    assert route["preferred"] == "none"
    assert route["gce_fallback_allowed"] is False
    assert route["reason_codes"] == ["route-unknown-envelope"]


def test_route_schema_version() -> None:
    route = resolve_ingress_route(_transport("accepted-discovery-envelope"))
    assert route["schema_version"] == "1.0"


def test_main_writes_route_output(tmp_path) -> None:
    from workflow_scheduler.governance.codespaces_first_route import main

    transport_path = tmp_path / "transport.json"
    route_path = tmp_path / "route.json"
    transport_path.write_text(json.dumps(_transport("accepted-discovery-envelope")), encoding="utf-8")
    assert main(["--transport", str(transport_path), "--route-output", str(route_path)]) == 0
    route = json.loads(route_path.read_text(encoding="utf-8"))
    assert route["preferred"] == "codespaces"
