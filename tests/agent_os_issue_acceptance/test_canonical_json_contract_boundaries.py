"""Regression coverage for canonical-JSON contract boundaries tracked by #1733.

These tests intentionally exercise representative owner-local serializers instead
of introducing a repository-global canonical JSON helper. Equal JSON rendering
is not sufficient evidence that downstream identities share a semantic domain.
"""

from __future__ import annotations

from scripts.agent_os_issue_acceptance import executor_route, operating_mode


def test_issue_acceptance_non_ascii_rendering_is_byte_exact() -> None:
    payload = {"z": "caf\u00e9", "a": ["\u96ea", 1]}
    expected_text = '{"a":["\u96ea",1],"z":"caf\u00e9"}'
    expected_bytes = expected_text.encode("utf-8")

    operating_render = operating_mode._canonical_json(payload)
    executor_render = executor_route._canonical_json(payload)

    assert operating_render == expected_text
    assert executor_render == expected_text
    assert operating_render.encode("utf-8") == expected_bytes
    assert executor_render.encode("utf-8") == expected_bytes
    assert "\\u00e9" not in operating_render
    assert "\\u96ea" not in executor_render


def test_equal_rendering_does_not_collapse_identity_domains() -> None:
    payload = {"label": "caf\u00e9", "ordinal": 1}

    operating_id = operating_mode._decision_id(payload)
    executor_id = executor_route._decision_id(payload)

    assert operating_id.startswith("operating-mode-decision:")
    assert executor_id.startswith("executor-route-decision:")
    assert operating_id != executor_id
