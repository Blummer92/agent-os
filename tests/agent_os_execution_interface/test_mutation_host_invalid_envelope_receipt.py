"""AOS-3333-HOST: rejected caller envelope must retain exact blocked receipt."""
import pytest
from scripts.agent_os_execution_interface.fixed_codespace_pilot import consume_fixed_codespace_pilot


@pytest.mark.parametrize("payload", [None, [], (), "accepted", 0, True, {"status": "accepted"}])
def test_host_invalid_transport_is_blocked_without_any_providers(payload):
    result = consume_fixed_codespace_pilot(payload)
    assert result["status"] == "blocked"
    assert result["reason_codes"] == ["invalid-fixed-operation-envelope"]
    assert result["execution_authorized"] is False
    assert result["side_effects_performed"] is False
    assert result["logical_trigger_id"] is None
