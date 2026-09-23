from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge


def payload(**changes):
    value = {
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": 2851,
        "task_reference": "issue:#2851",
        "ecosystem_hints": ["python"],
        "language_hints": ["python"],
        "library_hints": [],
        "capability_keywords": ["ckr6"],
        "target_path_hints": ["08_Tooling/agent-os-execution-service"],
        "canonical_rule_refs": ["#2851"],
        "known_knowledge_refs": [],
        "specialized_knowledge_required": False,
    }
    value.update(changes)
    return value


def event(envelope=None, **changes):
    body = bridge.COMMAND_PREFIX + json.dumps(envelope or payload())
    value = {
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 2851},
        "comment": {"body": body, "user": {"login": "Blummer92"}},
    }
    value.update(changes)
    return value


def test_event_parser_binds_repo_issue_actor_and_strict_json_envelope():
    result = bridge.envelope_from_event(
        event(), expected_repository="Blummer92/agent-os", allowed_actor="Blummer92"
    )
    assert result.operation == "issue-start"
    assert result.issue_number == 2851
    assert result.specialized_knowledge_required is False


@pytest.mark.parametrize(
    "bad",
    [
        {"unexpected": True},
        {"repository": "Other/repo"},
        {"issue_number": 1},
    ],
)
def test_event_parser_fails_closed_on_unknown_or_mismatched_input(bad):
    envelope = payload(**bad)
    with pytest.raises(ValueError):
        bridge.envelope_from_event(
            event(envelope),
            expected_repository="Blummer92/agent-os",
            allowed_actor="Blummer92",
        )


def test_issue_start_not_needed_classification_performs_zero_provider_reads(monkeypatch):
    envelope = bridge.parse_envelope(payload(specialized_knowledge_required=False))
    result = bridge.classify_envelope(envelope)
    assert result["retrieval_required"] is False
    assert result["notion_read_performed"] is False

    monkeypatch.setattr(
        bridge,
        "resolve_lesson_read_route",
        lambda: (_ for _ in ()).throw(AssertionError("reader route must not resolve")),
    )
    executed = bridge.execute_envelope(envelope, retrieval_required=False)
    assert executed["status"] == "not-needed"
    assert executed["selected_lesson_ids"] == []
    assert executed["side_effects_performed"] is False


def test_failed_repair_uses_existing_repair_context_to_force_material_retrieval():
    envelope = bridge.parse_envelope(
        payload(
            operation="failed-repair",
            specialized_knowledge_required=None,
            attempt_id="attempt-1",
            failed_hypothesis="label convergence was already complete",
            result_summary="refresh still reported blocked",
            repair_context="failed-pr-repair",
        )
    )
    result = bridge.classify_envelope(envelope)
    assert result["retrieval_required"] is True
    assert "failed-pr-repair" in result["reason_codes"][0]


def test_explicit_failed_repair_opt_out_is_transported_not_reclassified():
    envelope = bridge.parse_envelope(
        payload(
            operation="failed-repair",
            specialized_knowledge_required=False,
            attempt_id="attempt-1",
            failed_hypothesis="bounded hypothesis",
            result_summary="bounded result",
            repair_context="failed-pr-repair",
        )
    )
    assert bridge.classify_envelope(envelope)["retrieval_required"] is False


def test_retrieval_required_fails_closed_when_canonical_route_is_unbound(monkeypatch):
    class Route:
        execute_read = None
        reason_code = "connector-surface-unavailable"

    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: Route())
    envelope = bridge.parse_envelope(payload(specialized_knowledge_required=True))
    result = bridge.execute_envelope(envelope, retrieval_required=True)
    assert result["status"] == "manual-review"
    assert result["reason_codes"] == ["connector-surface-unavailable"]
    assert result["execution_authorized"] is False
    assert result["github_writes_authorized"] is False


def test_workflow_keeps_secret_post_classification_and_avoids_gce():
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/agent-os-ckr6.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "id-token: write" not in text
    assert "gcloud" not in text.lower()
    assert "NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}" in text
    assert "needs.classify.outputs.retrieval_required == 'true'" in text
    assert text.index("needs.classify.outputs.retrieval_required == 'true'") < text.index(
        "NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}"
    )
    assert "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID: ${{ vars.AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID }}" in text
