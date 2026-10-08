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


def test_3032_issue_start_projects_bounded_rejected_candidate_provenance(monkeypatch):
    envelope = bridge.parse_envelope(payload(specialized_knowledge_required=True))
    monkeypatch.setattr(
        bridge,
        "resolve_lesson_read_route",
        lambda: type("Route", (), {"execute_read": lambda query: {"results": []}})(),
    )
    monkeypatch.setattr(
        bridge,
        "activate_issue_start_lesson_preflight",
        lambda **kwargs: {
            "lesson_retrieval_status": "manual-review",
            "selection_reason_codes": ["unverifiable-relevant-candidate"],
            "selected_lesson_ids": [],
            "selected_lessons": [],
            "materiality_source": "caller-asserted-material",
            "canonical_github_refs": [],
            "rejected_candidate_provenance": [{
                "lesson_id": "LL-42",
                "source_revision": "2026-09-29T12:00:00Z",
                "currentness": "unverifiable",
                "provenance": "canonical-github-ref-missing-or-rejected",
            }],
            "handoff_projection": {
                "known_facts": ["coding-knowledge-sufficiency:manual-review"],
                "prior_decisions": [],
                "allowed_inspect_first": [],
                "stop_conditions": ["coding-knowledge:unverifiable-relevant-candidate"],
            },
            "substantial_hypothesis_admissible": False,
        },
    )
    result = bridge.execute_envelope(envelope, retrieval_required=True)
    assert result["rejected_candidate_provenance"] == [{
        "lesson_id": "LL-42",
        "source_revision": "2026-09-29T12:00:00Z",
        "currentness": "unverifiable",
        "provenance": "canonical-github-ref-missing-or-rejected",
    }]
    assert result["mutation_admissible"] is False
    assert result["side_effects_performed"] is False


def test_3032_issue_start_carries_provider_failure_detail_in_ckr6_reason_codes(monkeypatch):
    # #3032: the full CKR6 call graph (bridge -> route -> canonical reader ->
    # preflight -> orchestration) must project the actual provider cause in the
    # bounded result instead of only the generic unavailable reason.
    from agent_os_execution_service.lesson_reader_composition import (
        build_lesson_read_executor,
    )

    class RaisingAdapter:
        def execute(self, task):
            raise RuntimeError("Notion API returned HTTP 403: Forbidden")

    reader = build_lesson_read_executor(
        data_source_id="2dfd0def-fa42-4c61-992e-c977a1fcaaf4",
        adapter=RaisingAdapter(),
    )
    assert reader is not None
    route = type("Route", (), {})()
    route.execute_read = reader
    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: route)
    envelope = bridge.parse_envelope(payload(specialized_knowledge_required=True))
    result = bridge.execute_envelope(envelope, retrieval_required=True)

    assert result["status"] == "insufficient"
    assert "lesson-retrieval-unavailable-specialized-knowledge-required" in result["reason_codes"]
    assert "notion-http-403" in result["reason_codes"]
    assert result["mutation_admissible"] is False
    assert result["side_effects_performed"] is False


def test_failed_repair_rejects_unsupported_repair_context_at_ingress():
    with pytest.raises(ValueError, match="repair_context must be failed-pr-repair or ci-diagnosis"):
        bridge.parse_envelope(
            payload(
                operation="failed-repair",
                attempt_id="attempt-1",
                failed_hypothesis="bounded hypothesis",
                result_summary="bounded result",
                repair_context="failed-ci-diagnosis",
            )
        )


@pytest.mark.parametrize("repair_context", ["failed-pr-repair", "ci-diagnosis"])
def test_failed_repair_accepts_supported_repair_contexts(repair_context):
    envelope = bridge.parse_envelope(
        payload(
            operation="failed-repair",
            attempt_id="attempt-1",
            failed_hypothesis="bounded hypothesis",
            result_summary="bounded result",
            repair_context=repair_context,
        )
    )
    assert envelope.repair_context == repair_context


def test_failed_repair_uses_existing_repair_context_to_force_material_retrieval():
    envelope = bridge.parse_envelope(
        payload(
            operation="failed-repair",
            specialized_knowledge_required=None,
            # Sparse signals: CKR2 alone would report not-needed, so only the
            # repair context can make retrieval material.
            ecosystem_hints=[],
            language_hints=[],
            capability_keywords=[],
            target_path_hints=[],
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


def test_workflow_installs_repository_local_agent_os_runtime_graph_before_ckr6():
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/agent-os-ckr6.yml").read_text(encoding="utf-8")
    local_projects = (
        "08_Tooling/reusable-capability-registry",
        "08_Tooling/agent-memory-context-manager",
        "08_Tooling/workflow-scheduler",
        "08_Tooling/agent-os-execution-service",
    )
    install_blocks = text.split("- name: Install existing Agent OS runtime")[1:]
    assert len(install_blocks) == 2
    for block in install_blocks:
        bounded = block.split("\n\n", 1)[0]
        for project in local_projects:
            assert f"-e {project}" in bounded
        assert bounded.index("reusable-capability-registry") < bounded.index("workflow-scheduler")
        assert bounded.index("agent-memory-context-manager") < bounded.index("agent-os-execution-service")
        assert bounded.index("workflow-scheduler") < bounded.index("agent-os-execution-service")
    assert "pip install -e 08_Tooling/agent-os-execution-service" not in text

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


def test_2984_bridge_contract_distinguishes_transport_from_retrieval_activation() -> None:
    root = Path(__file__).resolve().parents[3]
    contract = (root / "08_Tooling/agent-os-execution-service/CKR6_GITHUB_BRIDGE.md").read_text(encoding="utf-8")
    for phrase in (
        "merged/callable transport is not evidence",
        "retrieval-required CKR6 path is usable",
        "AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID",
        "finite retrieval-required canary",
        "activation incomplete / binding pending",
        "do not guess a source identity",
        "#2854 as the binding owner",
    ):
        assert phrase in contract


def _result(**changes):
    value = {
        "operation": "issue-start",
        "repository": "Blummer92/agent-os",
        "issue_number": 2851,
        "status": "not-needed",
        "reason_codes": ["knowledge-not-needed"],
        "selected_lesson_ids": [],
        "canonical_github_refs": [],
        "handoff_projection": {
            "known_facts": ["coding-knowledge-sufficiency:not-needed"],
            "prior_decisions": [],
            "allowed_inspect_first": [],
            "stop_conditions": [],
        },
        "substantial_hypothesis_admissible": True,
        "mutation_admissible": False,
        "execution_authorized": False,
        "github_writes_authorized": False,
        "merge_authorized": False,
        "closure_authorized": False,
        "side_effects_performed": False,
    }
    value.update(changes)
    return value


def test_2851_result_comment_serializes_marker_plus_canonical_json():
    body = bridge.serialize_ckr6_result_comment(_result(), request_comment_id=777)
    assert body.startswith(bridge.CKR6_RESULT_MARKER + "\n")
    assert body.count("\n") == 1
    parsed = bridge.parse_ckr6_result_comment(body)
    assert parsed["status"] == "not-needed"
    assert parsed["request_comment_id"] == 777
    assert parsed["substantial_hypothesis_admissible"] is True
    assert parsed["handoff_projection"]["known_facts"] == [
        "coding-knowledge-sufficiency:not-needed"
    ]


def test_2851_result_comment_never_starts_with_command_prefix():
    # The postback must not retrigger the ingress workflow.
    body = bridge.serialize_ckr6_result_comment(_result(), request_comment_id=1)
    assert not body.startswith(bridge.COMMAND_PREFIX)
    assert bridge.COMMAND_PREFIX not in body.split("\n")[0]


def test_2851_result_comment_rejects_unexpected_fields():
    with pytest.raises(ValueError):
        bridge.serialize_ckr6_result_comment(
            _result(surprise_field=True), request_comment_id=1
        )


@pytest.mark.parametrize(
    "bad",
    [
        "no marker at all",
        bridge.CKR6_RESULT_MARKER + "\n" + '{"a":1}\n' + '{"b":2}',
        bridge.CKR6_RESULT_MARKER + "\nnot json",
    ],
)
def test_2851_result_comment_parse_rejects_non_canonical(bad):
    with pytest.raises(ValueError):
        bridge.parse_ckr6_result_comment(bad)


def test_2851_execute_envelope_carries_handoff_projection(monkeypatch):
    # The host-consumable unit must survive the bridge projection.
    monkeypatch.setattr(
        bridge,
        "resolve_lesson_read_route",
        lambda: (_ for _ in ()).throw(AssertionError("zero-read path must not resolve")),
    )
    envelope = bridge.parse_envelope(payload(specialized_knowledge_required=False))
    result = bridge.execute_envelope(envelope, retrieval_required=False)
    assert result["status"] == "not-needed"
    assert result["handoff_projection"]["known_facts"] == [
        "coding-knowledge-sufficiency:not-needed",
        # #3418: materiality provenance travels with the host-consumable unit.
        "coding-knowledge-materiality:caller-asserted-not-material",
    ]


def _postback_event():
    return {
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 2851},
        "comment": {"id": 777, "body": "ignored", "user": {"login": "Blummer92"}},
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_2851_postback_posts_bounded_comment_to_originating_issue(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))["body"]
        captured["auth"] = request.headers.get("Authorization")
        return _FakeResponse({"id": 888})

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    posted = bridge.postback_result_comment(
        event=_postback_event(),
        repository="Blummer92/agent-os",
        result=_result(),
        api_url="https://api.github.com",
        token="token-value",
    )
    assert captured["url"] == (
        "https://api.github.com/repos/Blummer92/agent-os/issues/2851/comments"
    )
    assert captured["url"].startswith("https://")
    assert captured["auth"] == "Bearer token-value"
    assert "token-value" not in captured["body"]
    parsed = bridge.parse_ckr6_result_comment(captured["body"])
    assert parsed["request_comment_id"] == 777
    assert posted["posted_comment_id"] == 888
    assert posted["result_status"] == "not-needed"


def test_2851_postback_falls_back_to_manual_review_when_result_missing(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["body"] = json.loads(request.data.decode("utf-8"))["body"]
        return _FakeResponse({"id": 889})

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    posted = bridge.postback_result_comment(
        event=_postback_event(),
        repository="Blummer92/agent-os",
        result=None,
        api_url="https://api.github.com",
        token="token-value",
    )
    parsed = bridge.parse_ckr6_result_comment(captured["body"])
    assert parsed["status"] == "manual-review"
    assert parsed["reason_codes"] == ["ckr6-result-unavailable"]
    assert parsed["substantial_hypothesis_admissible"] is False
    assert parsed["execution_authorized"] is False
    assert posted["result_status"] == "manual-review"


def test_2851_postback_fails_closed_on_transport_error(monkeypatch):
    def fake_urlopen(request, timeout=30):
        raise OSError("connection refused")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError):
        bridge.postback_result_comment(
            event=_postback_event(),
            repository="Blummer92/agent-os",
            result=_result(),
            api_url="https://api.github.com",
            token="token-value",
        )


def test_2851_workflow_posts_bounded_result_with_least_privilege():
    root = Path(__file__).resolve().parents[3]
    text = (root / ".github/workflows/agent-os-ckr6.yml").read_text(encoding="utf-8")
    # Top-level stays least-privilege; the execute job alone gains issues:write.
    assert "permissions:\n  contents: read" in text
    execute_block = text.split("name: Execute finite CKR6 request", 1)[1]
    assert "issues: write" in execute_block.split("steps:", 1)[0]
    # The postback always runs so the host gets a terminal signal, and it
    # cannot retrigger the ingress.
    assert "Post bounded CKR6 result to issue" in text
    assert "if: ${{ always() }}" in text
    assert "--phase postback" in text
    postback_step = text.split("Post bounded CKR6 result to issue", 1)[1]
    assert "/agent-os ckr6" not in postback_step.split("- name:", 1)[0]


def test_2851_unbound_route_carries_admission_flag_and_stop_conditions(monkeypatch):
    # CASE C: the blocked result must be machine-readable as blocked and tell
    # the host why it must stop.
    route = type("Route", (), {"execute_read": None, "reason_code": "current-surface-unbound"})()
    monkeypatch.setattr(bridge, "resolve_lesson_read_route", lambda: route)
    envelope = bridge.parse_envelope(payload(specialized_knowledge_required=True))
    result = bridge.execute_envelope(envelope, retrieval_required=True)
    assert result["status"] == "manual-review"
    assert result["reason_codes"] == ["current-surface-unbound"]
    assert result["substantial_hypothesis_admissible"] is False
    assert result["selected_lesson_ids"] == []
    assert result["handoff_projection"]["stop_conditions"] == [
        "coding-knowledge:current-surface-unbound"
    ]
    assert result["handoff_projection"]["known_facts"] == [
        "coding-knowledge-sufficiency:manual-review"
    ]
    # The blocked result must still serialize through the postback contract.
    body = bridge.serialize_ckr6_result_comment(result, request_comment_id=5)
    parsed = bridge.parse_ckr6_result_comment(body)
    assert parsed["substantial_hypothesis_admissible"] is False


# --- #2851: host attribution trailer and bounded rejection receipts -------

FOOTER = "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_\n"


def _body_event(body, *, login="Blummer92", comment_id=6061066366):
    return {
        "repository": {"full_name": "Blummer92/agent-os"},
        "issue": {"number": 2851},
        "comment": {"id": comment_id, "body": body, "user": {"login": login}},
    }


def test_2851_known_host_attribution_trailer_is_tolerated():
    # Exact shape that failed run 37785572464: compact JSON + appended footer.
    body = bridge.COMMAND_PREFIX + json.dumps(payload(), separators=(",", ":")) + FOOTER
    result = bridge.envelope_from_event(
        _body_event(body), expected_repository="Blummer92/agent-os", allowed_actor="Blummer92"
    )
    assert result.issue_number == 2851


@pytest.mark.parametrize(
    "suffix",
    [
        FOOTER + "extra",
        "\nnot json",
        json.dumps(payload()),
        "\n\n---\n_Generated by [Other](https://claude.ai/code)_",
        "\n---\n_Generated by [Claude Code](https://evil.example)_",
    ],
)
def test_2851_any_other_trailing_text_still_fails_closed(suffix):
    body = bridge.COMMAND_PREFIX + json.dumps(payload()) + suffix
    with pytest.raises(ValueError, match="one JSON object"):
        bridge.envelope_from_event(
            _body_event(body), expected_repository="Blummer92/agent-os", allowed_actor="Blummer92"
        )


def _run_main(monkeypatch, tmp_path, body, phase, *extra):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(_body_event(body)), encoding="utf-8")
    output = tmp_path / f"{phase}.json"
    argv = ["ckr6", "--phase", phase, "--event", str(event_path),
            "--repository", "Blummer92/agent-os", "--allowed-actor", "Blummer92",
            "--output", str(output), *extra]
    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.setattr(
        bridge, "resolve_lesson_read_route",
        lambda: (_ for _ in ()).throw(AssertionError("no read for rejected request")),
    )
    assert bridge.main() == 0
    return json.loads(output.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (bridge.COMMAND_PREFIX + "{not json", "payload-not-one-json-object"),
        (bridge.COMMAND_PREFIX + json.dumps(payload(unexpected="private text")), "envelope-field-unsupported"),
        (bridge.COMMAND_PREFIX + json.dumps(payload(operation="write-notion")), "operation-unsupported"),
        (bridge.COMMAND_PREFIX + json.dumps(payload(issue_number=1)), "issue-number-mismatch"),
        (bridge.COMMAND_PREFIX + json.dumps(payload(specialized_knowledge_required="maybe")), "materiality-invalid"),
    ],
)
def test_2851_malformed_request_produces_bounded_rejection_receipt(monkeypatch, tmp_path, body, code):
    classification = _run_main(monkeypatch, tmp_path, body, "classify")
    assert classification["retrieval_required"] is False
    result = _run_main(monkeypatch, tmp_path, body, "execute", "--retrieval-required", "false")
    assert result["status"] == "rejected"
    assert result["reason_codes"] == ["envelope-rejected:" + code]
    assert result["substantial_hypothesis_admissible"] is False
    assert result["notion_read_performed"] is False
    assert not any(result[key] for key in (
        "execution_authorized", "github_writes_authorized", "merge_authorized",
        "closure_authorized", "side_effects_performed", "mutation_admissible"))
    serialized = bridge.serialize_ckr6_result_comment(result, request_comment_id=6061066366)
    assert "private text" not in serialized and "write-notion" not in serialized
    assert not serialized.startswith(bridge.COMMAND_PREFIX)
    assert bridge.parse_ckr6_result_comment(serialized)["status"] == "rejected"


def test_2851_postback_is_idempotent_per_request_comment(monkeypatch):
    existing = bridge.serialize_ckr6_result_comment(_result(), request_comment_id=777)
    calls = []

    def fake_urlopen(request, timeout=30):
        calls.append(request.get_method())
        if request.get_method() == "GET":
            assert "since=2026-10-08T13%3A35%3A35Z" in request.full_url
            return _FakeResponse([{"id": 1, "body": "unrelated"}, {"id": 990, "body": existing}])
        return _FakeResponse({"id": 991})

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    event_value = _postback_event()
    event_value["comment"]["created_at"] = "2026-10-08T13:35:35Z"
    posted = bridge.postback_result_comment(
        event=event_value, repository="Blummer92/agent-os", result=_result(),
        api_url="https://api.github.com", token="token-value",
    )
    assert calls == ["GET"]
    assert (posted["posted_comment_id"], posted["deduplicated"]) == (990, True)


def test_2851_postback_lookup_failure_still_returns_a_receipt(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=30):
        calls.append(request.get_method())
        if request.get_method() == "GET":
            raise OSError("lookup unavailable")
        return _FakeResponse({"id": 992})

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    event_value = _postback_event()
    event_value["comment"]["created_at"] = "2026-10-08T13:35:35Z"
    posted = bridge.postback_result_comment(
        event=event_value, repository="Blummer92/agent-os", result=_result(),
        api_url="https://api.github.com", token="token-value",
    )
    assert calls == ["GET", "POST"]
    assert posted["posted_comment_id"] == 992
