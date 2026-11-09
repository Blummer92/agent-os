"""Wave 3 NC16 candidate (FU-HOST-2): full 27-key receipt shape, invalid envelope.

Local-only candidate. Intended home (when filed): the existing test file
tests/agent_os_execution_interface/test_mutation_host_invalid_envelope_receipt.py.

Provenance: Wave 2 PR #3850's test asserts only five receipt fields
(status, reason_codes, execution_authorized, side_effects_performed,
logical_trigger_id). FU-HOST-2 asserts the complete receipt dict, so dropping
any single receipt field fails this test. The mutant used for the local kill
removes "scheduler_invoked", a field the existing test never checks -- the
existing 7-case test still passes on that mutant, so this file is the sole
detector for it.
"""
import pytest

from scripts.agent_os_execution_interface.fixed_codespace_pilot import (
    FIXED_ARGV,
    consume_fixed_codespace_pilot,
)

EXPECTED_INVALID_ENVELOPE_RECEIPT = {
    "schema_version": "1.0",
    "operation_id": "codespace-implementation-pilot-v1",
    "status": "blocked",
    "reason_codes": ["invalid-fixed-operation-envelope"],
    "repository": "Blummer92/agent-os",
    "issue_number": 3333,
    "logical_trigger_id": None,
    "handoff_id": None,
    "expected_sha": None,
    "request_id": None,
    "codespace_name": None,
    "argv": list(FIXED_ARGV),
    "exit_status": None,
    "stdout_tail": "",
    "stderr_tail": "",
    "stdout_truncated": False,
    "stderr_truncated": False,
    "started_at": None,
    "ended_at": None,
    "duration_ms": None,
    "execution_authorized": False,
    "github_writes_authorized": False,
    "external_writes_authorized": False,
    "publication_authorized": False,
    "merge_authorized": False,
    "scheduler_invoked": False,
    "side_effects_performed": False,
}


@pytest.mark.parametrize(
    "payload", [None, [], (), "accepted", 0, True, {"status": "accepted"}]
)
def test_host_invalid_transport_receipt_has_full_27_key_shape(payload):
    """Every invalid transport yields exactly the 27-key blocked receipt.

    Exact dict equality: no missing field, no extra field, no changed value.
    In particular no authorization flag is ever True and no provider field
    (request_id, codespace_name, exit_status, timing) is ever populated.
    """
    result = consume_fixed_codespace_pilot(payload)
    assert len(result) == 27
    assert result == EXPECTED_INVALID_ENVELOPE_RECEIPT
