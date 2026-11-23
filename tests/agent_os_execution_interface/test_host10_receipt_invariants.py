"""HOST10 receipt invariants (promoted from qualification prototypes).

Each test pins a protected invariant of the fixed Codespace pilot's
fail-closed receipts: a rejected envelope's receipt retains the transport's
provenance fields (logical_trigger_id, handoff_id, expected_sha); a non-dict
transport yields a clean receipt, never an exception; a blocked receipt's
status is exactly "blocked" at every early-return site. See issue #3333.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_os_execution_service.production_host_composition import (
    ProductionAdmissionProviders,
)
from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    consume_fixed_codespace_pilot,
    consume_fixed_codespace_pilot_on_host,
    drive_fixed_codespace_pilot_on_host,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (
    admit_issue_comment_event,
)

REPO = "Blummer92/agent-os"
ISSUE_NUMBER = 3333
SHA = "a" * 40
HANDOFF = "executor-handoff:" + "b" * 64
TRIGGER = f"/agent-os codespace-implementation {HANDOFF} {SHA}"
EVALUATED_AT = "2026-10-14T12:34:56Z"


def _event(body=TRIGGER, *, actor="Blummer92"):
    return {
        "action": "created",
        "repository": {"full_name": REPO},
        "issue": {"number": ISSUE_NUMBER},
        "comment": {"id": 101, "body": body, "user": {"login": actor}},
        "sender": {"login": actor},
    }


def _accepted_dict():
    return admit_issue_comment_event(
        _event(), expected_repository=REPO, allowed_actor="Blummer92", run_attempt=1
    ).to_dict()


def _tampered_dict():
    """Accepted-shaped dict that fails _valid_transport, fields intact."""
    return {**_accepted_dict(), "actor": "mallory"}


def _providers():
    return ProductionAdmissionProviders(
        descriptor_loader=lambda handoff: pytest.fail("no descriptor read expected"),
        current_resolver=SimpleNamespace(reacquire=lambda descriptor: None),
        lease_reader=SimpleNamespace(inspect=lambda: None),
        evaluated_at=EVALUATED_AT,
    )


def _assert_receipt_fields(retained, *, status, reason):
    assert retained["status"] == status
    assert retained["reason_codes"] == [reason]
    assert retained["logical_trigger_id"] == _accepted_dict()["logical_trigger_id_or_none"]
    assert retained["handoff_id"] == HANDOFF
    assert retained["expected_sha"] == SHA
    assert retained["execution_authorized"] is False
    assert retained["side_effects_performed"] is False


# --- Group A: envelope preservation on the invalid-envelope branch ---

def test_host10_m2_m4_m5_invalid_envelope_retains_fields_full_copy():
    _assert_receipt_fields(
        consume_fixed_codespace_pilot(_tampered_dict()),
        status="blocked", reason="invalid-fixed-operation-envelope",
    )


def test_host10_m2_m4_m5_invalid_envelope_retains_fields_host_copy():
    _assert_receipt_fields(
        consume_fixed_codespace_pilot_on_host(
            _tampered_dict(),
            providers=_providers(),
            resolve_selection=lambda: pytest.fail("selection must not be read"),
        ),
        status="blocked", reason="invalid-fixed-operation-envelope",
    )


def test_host10_m2_m4_m5_invalid_envelope_retains_fields_drive_copy():
    _assert_receipt_fields(
        drive_fixed_codespace_pilot_on_host(_tampered_dict(), bootstrap=None),
        status="needs-decision", reason="canonical-admission-provider-unavailable",
    )


# --- Group A: non-dict transports must yield a clean receipt, not a crash ---
# (mutants 3 and 5 set envelope=transport for non-dict input, so _receipt
# would call .get on a non-mapping and raise AttributeError.)

@pytest.mark.parametrize("payload", [None, [], (), "accepted", 0, True])
def test_host10_m3_m5_nondict_transport_is_clean_receipt_host_copy(payload):
    result = consume_fixed_codespace_pilot_on_host(
        payload,
        providers=_providers(),
        resolve_selection=lambda: pytest.fail("selection must not be read"),
    )
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["invalid-fixed-operation-envelope"]
    assert result["logical_trigger_id"] is None
    assert result["handoff_id"] is None
    assert result["expected_sha"] is None


@pytest.mark.parametrize("payload", [[], (), "accepted", 0, True])
def test_host10_m3_m5_nondict_transport_is_clean_receipt_drive_copy(payload):
    result = drive_fixed_codespace_pilot_on_host(payload, bootstrap=None)
    assert result["status"] == "needs-decision"
    assert result["reason_codes"] == ["canonical-admission-provider-unavailable"]
    assert result["logical_trigger_id"] is None
    assert result["handoff_id"] is None
    assert result["expected_sha"] is None


# --- Group B: exact blocked status at each early-return site ---

def test_host10_m33_m39_m40_unverified_selection_status_exact_host_copy():
    result = consume_fixed_codespace_pilot_on_host(
        _accepted_dict(),
        providers=_providers(),
        resolve_selection=lambda: None,
    )
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["codespace-currentness-or-health-unverified"]
    assert result["side_effects_performed"] is False
