"""Regression coverage for canonical-JSON contract boundaries tracked by #1733.

These tests intentionally exercise representative owner-local serializers instead
of introducing a repository-global canonical JSON helper. Equal JSON rendering
is not sufficient evidence that downstream identities share a semantic domain.

The executor-route serializer pair moved to the canonical #918 router as part
of the Decision 1 consolidation; the identity-domain test now proves the
executor-route-decision domain is owned there.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.agent_os_issue_acceptance import operating_mode, post_pr_state_audit

SERVICE_SRC = (
    Path(__file__).resolve().parents[2]
    / "08_Tooling"
    / "agent-os-execution-service"
    / "src"
)
if str(SERVICE_SRC) not in sys.path:
    sys.path.insert(0, str(SERVICE_SRC))

from agent_os_execution_service.executor_routing import (  # noqa: E402
    executor_route_decision_id,
    select_executor_route,
)


def test_issue_acceptance_non_ascii_rendering_is_byte_exact() -> None:
    payload = {"z": "caf\u00e9", "a": ["\u96ea", 1]}
    expected_text = '{"a":["\u96ea",1],"z":"caf\u00e9"}'
    expected_bytes = expected_text.encode("utf-8")

    operating_render = operating_mode._canonical_json(payload)
    audit_render = post_pr_state_audit._canonical_json(payload)

    assert operating_render == expected_text
    assert audit_render == expected_text
    assert operating_render.encode("utf-8") == expected_bytes
    assert audit_render.encode("utf-8") == expected_bytes
    assert "\\u00e9" not in operating_render
    assert "\\u96ea" not in audit_render


def test_equal_rendering_does_not_collapse_identity_domains() -> None:
    payload = {"label": "caf\u00e9", "ordinal": 1}

    operating_id = operating_mode._decision_id(payload)
    assert operating_id.startswith("operating-mode-decision:")

    route = select_executor_route(
        repository="Blummer92/agent-os",
        issue_or_handoff_identity="issue:1733",
        requested_operation="identity-domain-probe",
        required_capabilities=(),
        governed_runner_capabilities=(),
        governed_runner_available=False,
        external_fallback_available=False,
        external_fallback_explicitly_permitted=False,
        created_at="2026-10-05T00:00:00Z",
        expires_at="2026-10-05T01:00:00Z",
        invalidation_conditions=("identity-probe",),
        execution_service_request_fingerprint_or_none="execution-request:id1",
        operating_mode_decision_id_or_none="operating-mode:id1",
        executable_lane_selection_id_or_none="lane-selection:id1",
    )
    executor_id = executor_route_decision_id(route)
    assert executor_id.startswith("executor-route-decision:")
    assert operating_id != executor_id
