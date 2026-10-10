"""#3418: production consumers of the existing learning seams, receipts and metrics."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service import lesson_learning_loop as loop
from agent_os_execution_service.issue_start_lesson_preflight import activate_issue_start_lesson_preflight
from agent_os_execution_service.lesson_learning_metrics import derive_lesson_metrics

REVISION = "2026-10-08T12:00:00.000Z"
TASK = "https://github.com/Blummer92/agent-os/issues/3418"


def _rt(text):
    return {"type": "rich_text", "rich_text": [{"plain_text": text, "text": {"content": text}}]}


def row(number=999, revision=REVISION, *, status="New"):
    return {
        "object": "page", "last_edited_time": revision,
        "url": f"https://www.notion.so/{number}",
        "properties": {
            "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": "LL", "number": number}},
            "Lesson Learned": {"type": "title", "title": [{"plain_text": "Verify labels after issue creation"}]},
            "Status": {"type": "select", "select": None if status is None else {"name": status}},
            "Surface Before Work?": {"type": "checkbox", "checkbox": True},
            "Area": {"type": "select", "select": {"name": "Governance"}},
            "Learning Type": {"type": "select", "select": {"name": "Mistake"}},
            "Applies To": {"type": "multi_select", "multi_select": [{"name": "Notion"}]},
            "Source Link": {"type": "url", "url": "https://github.com/Blummer92/agent-os/issues/3305"},
            "Guardrail": _rt("Prove label convergence through readback."),
            "What To Do Next Time": _rt("Verify labels after creating a GitHub issue."),
            "What Happened": _rt("Some created issues lacked labels."),
        },
    }


def reader(rows):
    calls = []

    def execute_read(query):
        calls.append(deepcopy(query))
        return {"results": deepcopy(rows), "has_more": False}

    execute_read.calls = calls
    return execute_read


# --------------------------------------------------------- CKR6 provenance


def test_issue_start_returns_exact_lesson_revision_and_selection_provenance():
    read = reader([row()])
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418, task_reference="issue:#3418",
        capability_keywords=("failure-avoidance",), known_knowledge_refs=("LL-999",),
        specialized_knowledge_required=True, execute_read=read,
    )
    assert result["lesson_retrieval_status"] == "sufficient"
    assert result["selected_lessons"] == [{
        "lesson_id": "LL-999", "source_revision": REVISION,
        "selection_reason_codes": result["selected_lessons"][0]["selection_reason_codes"],
    }]
    assert result["selected_lessons"][0]["selection_reason_codes"]
    assert result["materiality_source"] == "caller-asserted-material"


def test_issue_start_projects_real_rejected_candidate_provenance():
    # Previously dropped by the issue-start projection (only a stub carried it).
    unverifiable = row()
    unverifiable["properties"]["Source Link"]["url"] = None
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418, task_reference="issue:#3418",
        capability_keywords=("failure-avoidance",), known_knowledge_refs=("LL-999",),
        specialized_knowledge_required=True, execute_read=reader([unverifiable]),
    )
    assert result["lesson_retrieval_status"] != "sufficient"
    assert result["selected_lessons"] == []
    assert result["rejected_candidate_provenance"][0]["lesson_id"] == "LL-999"
    assert result["rejected_candidate_provenance"][0]["source_revision"] == REVISION


def test_omitted_materiality_is_reported_as_inferred_never_silent():
    result = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418, task_reference="issue:#3418",
        capability_keywords=("ckr6",), execute_read=reader([]),
    )
    assert result["lesson_retrieval_status"] == "not-needed"
    assert result["materiality_source"] == "inferred-not-material"
    assert "coding-knowledge-materiality:inferred-not-material" in result["handoff_projection"]["known_facts"]
    asserted = activate_issue_start_lesson_preflight(
        repository="Blummer92/agent-os", issue_number=3418, task_reference="issue:#3418",
        specialized_knowledge_required=False, execute_read=reader([]),
    )
    assert asserted["materiality_source"] == "caller-asserted-not-material"


def test_bridge_result_carries_revision_provenance(monkeypatch):
    read = reader([row()])
    monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                        lambda: type("Route", (), {"execute_read": staticmethod(read)})())
    envelope = bridge.parse_envelope({
        "operation": "issue-start", "repository": "Blummer92/agent-os", "issue_number": 3418,
        "task_reference": "issue:#3418", "capability_keywords": ["failure-avoidance"],
        "known_knowledge_refs": ["LL-999"], "specialized_knowledge_required": True,
    })
    result = bridge.execute_envelope(envelope, retrieval_required=True)
    assert result["selected_lessons"][0]["source_revision"] == REVISION
    parsed = bridge.parse_ckr6_result_comment(bridge.serialize_ckr6_result_comment(result, request_comment_id=5))
    assert parsed["selected_lessons"] == result["selected_lessons"]


# ---------------------------------------------------------------- capture


def candidate(**changes):
    value = {
        "source_reference": "PR #3392 repair",
        "signal": "repeated-repair",
        "failure_signature": "issue-creation-path-skips-label-plan",
        "ecosystem": "agent-os",
        "capability_kind": "failure-avoidance",
        "lesson_summary": "Every issue-creation path must consume the canonical label plan",
        "what_happened": "Two repairs failed because one host creation path skipped the label plan.",
        "severity": "High",
        "owner_agent": "github-service-agent",
        "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3092"],
        "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3421"],
        "what_to_do_next_time": "Route every creation path through the label plan and read labels back.",
        "guardrail": "Terminal success requires label convergence by readback.",
        "reusable_rule_proven": True,
    }
    value.update(changes)
    return value


def _learning_envelope(operation, key, detail):
    return bridge.parse_envelope({
        "operation": operation, "repository": "Blummer92/agent-os", "issue_number": 3418,
        "task_reference": "issue:#3418", key: detail,
    })


def _no_route(monkeypatch):
    monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                        lambda: (_ for _ in ()).throw(AssertionError("capture must not read")))


def test_capture_runs_producer_ckr5_and_projection_through_the_ingress(monkeypatch):
    _no_route(monkeypatch)
    calls = []
    for name in ("normalize_learning_outcome", "evaluate_coding_failure", "project_lesson_to_notion"):
        original = getattr(loop, name)
        monkeypatch.setattr(loop, name, lambda *a, _o=original, _n=name, **k: (calls.append(_n), _o(*a, **k))[1])
    envelope = _learning_envelope("lesson-candidate", "candidate", candidate())
    assert bridge.classify_envelope(envelope)["retrieval_required"] is False
    result = bridge.execute_envelope(envelope, retrieval_required=False)
    assert calls == ["normalize_learning_outcome", "evaluate_coding_failure", "project_lesson_to_notion"]
    assert result["status"] == "reusable-new"
    proposal = result["lesson_proposal"]
    draft = proposal["catalog_entry_draft"]
    assert draft["target_lesson_id"] is None
    assert draft["properties"]["Learning Type"] == "Mistake"
    assert draft["properties"]["Source Link"] == "https://github.com/Blummer92/agent-os/issues/3092"
    assert {"Status", "Surface Before Work?"}.isdisjoint(draft["properties"])
    assert proposal["catalog_ready"] is True
    assert not any(proposal[k] for k in ("authority_created", "notion_write_performed", "publication_authorized"))
    assert result["notion_read_performed"] is False
    comment = bridge.serialize_ckr6_result_comment(result, request_comment_id=9)
    assert bridge.parse_ckr6_result_comment(comment)["lesson_proposal"]["lesson_identity"] == proposal["lesson_identity"]


@pytest.mark.parametrize(("change", "status"), [
    ({"signal": "ordinary-pass"}, "non-reusable"),
    ({"signal": "transient-environment"}, "non-reusable"),
    ({"reusable_rule_proven": False}, "non-reusable"),
    ({"guardrail": None}, "insufficient-evidence"),
    ({"evidence_refs": []}, "insufficient-evidence"),
])
def test_materiality_threshold_excludes_noise_without_proposal(monkeypatch, change, status):
    _no_route(monkeypatch)
    result = bridge.execute_envelope(_learning_envelope("lesson-candidate", "candidate", candidate(**change)),
                                     retrieval_required=False)
    assert (result["status"], result["lesson_proposal"]) == (status, None)


def test_candidate_envelope_is_strict():
    # Malformed detail is refused as a bounded rejection receipt, never a proposal.
    for detail in (candidate(Status="Applied"), candidate(signal="anything")):
        result = bridge.execute_envelope(_learning_envelope("lesson-candidate", "candidate", detail),
                                         retrieval_required=False)
        assert (result["status"], result["lesson_proposal"]) == ("rejected", None)
    with pytest.raises(ValueError):
        _learning_envelope("lesson-candidate", "candidate", "text")
    with pytest.raises(ValueError):
        bridge.parse_envelope({"operation": "lesson-candidate", "repository": "Blummer92/agent-os",
                               "issue_number": 3418, "task_reference": "x", "candidate": candidate(),
                               "refinement": {}})


# ------------------------------------------------------------- refinement

RECEIPT_REF = "https://github.com/Blummer92/agent-os/issues/3418#issuecomment-6100000001"


def refinement(**changes):
    value = {
        "lesson_id": "LL-999", "source_revision": REVISION, "receipt_refs": [RECEIPT_REF],
        "evidence": [{
            "reference": "https://github.com/Blummer92/agent-os/issues/3092",
            "effect": "improves-root-cause",
            "canonical_github_refs": ["https://github.com/Blummer92/agent-os/issues/3092"],
            "evidence_refs": ["https://github.com/Blummer92/agent-os/pull/3421"],
            "revised_next_time": "Every issue-creation path must consume the canonical label plan and prove convergence through readback before terminal success.",
        }],
    }
    value.update(changes)
    return value


def _route(monkeypatch, rows):
    read = reader(rows)
    monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                        lambda: type("Route", (), {"execute_read": staticmethod(read)})())
    return read


def test_refinement_reads_exact_lesson_and_runs_ckr7(monkeypatch):
    read = _route(monkeypatch, [row()])
    calls = []
    original = loop.evaluate_lesson_enrichment
    monkeypatch.setattr(loop, "evaluate_lesson_enrichment",
                        lambda *a, **k: (calls.append("ckr7"), original(*a, **k))[1])
    envelope = _learning_envelope("lesson-refinement", "refinement", refinement())
    assert bridge.classify_envelope(envelope)["retrieval_required"] is True
    result = bridge.execute_envelope(envelope, retrieval_required=True)
    assert calls == ["ckr7"]
    assert read.calls == [{"page_size": 5, "filter": {"or": [{"property": "Lesson ID", "unique_id": {"equals": 999}}]}}]
    assert result["status"] == "enrich-existing"
    proposal = result["revision_proposal"]
    assert (proposal["lesson_id"], proposal["expected_revision"]) == ("LL-999", REVISION)
    assert RECEIPT_REF in proposal["receipt_refs"]
    draft = proposal["catalog_entry_draft"]
    assert draft["target_lesson_id"] == "LL-999"
    assert "label plan" in draft["properties"]["What To Do Next Time"]
    assert {"Status", "Surface Before Work?"}.isdisjoint(draft["properties"])
    assert result["notion_read_performed"] is True and result["side_effects_performed"] is False


def test_refinement_refuses_stale_revision_and_unusable_lessons(monkeypatch):
    _route(monkeypatch, [row(revision="2026-10-09T00:00:00.000Z")])
    stale = bridge.execute_envelope(_learning_envelope("lesson-refinement", "refinement", refinement()), retrieval_required=True)
    assert (stale["status"], stale["reason_codes"]) == ("rejected", ["stale-lesson-revision"])
    _route(monkeypatch, [row(status=None)])
    skip = bridge.execute_envelope(_learning_envelope("lesson-refinement", "refinement", refinement()), retrieval_required=True)
    assert skip["reason_codes"] == ["lesson-not-normalizable:ambiguous-status-vocabulary"]
    _route(monkeypatch, [])
    missing = bridge.execute_envelope(_learning_envelope("lesson-refinement", "refinement", refinement()), retrieval_required=True)
    assert missing["reason_codes"] == ["lesson-not-found"]


def test_refinement_requires_observed_use_receipts():
    for change in ({"receipt_refs": []}, {"receipt_refs": ["https://github.com/Blummer92/agent-os/issues/3418"]},
                   {"lesson_id": "93"}, {"source_revision": "yesterday"}, {"evidence": []}):
        with pytest.raises(ValueError):
            loop.parse_refinement(refinement(**change))


def test_contradicting_evidence_routes_to_manual_review_without_draft(monkeypatch):
    _route(monkeypatch, [row()])
    detail = refinement()
    detail["evidence"][0]["effect"] = "contradicts"
    result = bridge.execute_envelope(_learning_envelope("lesson-refinement", "refinement", detail), retrieval_required=True)
    assert (result["status"], result["revision_proposal"]) == ("manual-review", None)


# --------------------------------------------------------------- receipts


def receipt(**changes):
    value = {"ckr6_result_comment_id": 501, "lesson_id": "LL-999", "source_revision": REVISION,
             "task_ref": TASK, "disposition": "applied", "reason_code": "guided-decision",
             "decision": "Routed the new creation path through the label plan before success.",
             "outcome_ref": "https://github.com/Blummer92/agent-os/pull/3421"}
    value.update(changes)
    return value


def sufficient_result(lessons=(("LL-999", REVISION),)):
    return {"operation": "issue-start", "repository": "Blummer92/agent-os", "issue_number": 3418,
            "status": "sufficient", "reason_codes": ["knowledge-sufficient"],
            "selected_lesson_ids": [lesson for lesson, _ in lessons],
            "selected_lessons": [{"lesson_id": lesson, "source_revision": rev, "selection_reason_codes": ["x"]}
                                 for lesson, rev in lessons],
            "canonical_github_refs": [], "substantial_hypothesis_admissible": True,
            "execution_authorized": False, "github_writes_authorized": False, "merge_authorized": False,
            "closure_authorized": False, "side_effects_performed": False, "mutation_admissible": False}


def test_receipt_round_trip_and_host_footer_tolerance():
    body = loop.serialize_receipt_comment(receipt())
    assert loop.parse_receipt_comment(body) == receipt()
    footer = body + "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_\n"
    assert loop.parse_receipt_comment(footer) == receipt()
    with pytest.raises(ValueError):
        loop.parse_receipt_comment(body + "\nanything else")


@pytest.mark.parametrize("change", [
    {"disposition": "used"}, {"reason_code": "not-relevant-to-task"},
    {"disposition": "skipped", "reason_code": "guided-decision"}, {"lesson_id": "lesson"},
    {"task_ref": "#3418"}, {"decision": "x" * 257}, {"outcome_ref": "https://example.com"},
    {"ckr6_result_comment_id": 0},
])
def test_receipt_shape_is_finite(change):
    with pytest.raises(ValueError):
        loop.validate_receipt_shape(receipt(**change))


def test_receipt_requires_actual_retrieval_of_that_revision():
    result = sufficient_result()
    assert loop.verify_receipt_against_result(receipt(), result, result_comment_id=501) is None
    assert loop.verify_receipt_against_result(receipt(lesson_id="LL-5"), result, result_comment_id=501) == "receipt-lesson-not-returned-by-ckr6"
    assert loop.verify_receipt_against_result(receipt(source_revision="2026-01-01T00:00:00Z"), result, result_comment_id=501) == "receipt-lesson-not-returned-by-ckr6"
    assert loop.verify_receipt_against_result(receipt(), {**result, "status": "not-needed"}, result_comment_id=501) == "receipt-result-not-sufficient"
    legacy = {k: v for k, v in result.items() if k != "selected_lessons"}
    assert loop.verify_receipt_against_result(receipt(), legacy, result_comment_id=501) == "receipt-result-lacks-revision-provenance"


# ---------------------------------------------------------------- metrics


def _comment(comment_id, body):
    return {"id": comment_id, "body": body}


def test_metrics_count_only_valid_deduplicated_receipts_and_expose_signals():
    result_body = bridge.serialize_ckr6_result_comment(sufficient_result(), request_comment_id=500)
    capture = {"operation": "lesson-candidate", "repository": "Blummer92/agent-os", "issue_number": 3418,
               "status": "reusable-new", "reason_codes": [], "selected_lesson_ids": [], "canonical_github_refs": [],
               "lesson_proposal": {"core_identity": "abc"}, "notion_read_performed": False}
    comments = {3418: [
        _comment(501, result_body),
        _comment(502, loop.serialize_receipt_comment(receipt())),
        _comment(503, loop.serialize_receipt_comment(receipt())),  # duplicate
        _comment(504, loop.serialize_receipt_comment(receipt(disposition="skipped", reason_code="guidance-outdated"))),
        _comment(505, loop.serialize_receipt_comment(receipt(lesson_id="LL-7"))),  # not returned
        _comment(506, loop.serialize_receipt_comment(receipt(ckr6_result_comment_id=999))),  # unknown result
        _comment(507, bridge.serialize_ckr6_result_comment(capture, request_comment_id=1)),
        _comment(508, bridge.serialize_ckr6_result_comment(capture, request_comment_id=2)),
        _comment(509, "<!-- agent-os-lesson-receipt:v1 -->\n{broken"),
        _comment(510, "ordinary discussion"),
    ]}
    metrics = derive_lesson_metrics(comments)
    receipts = metrics["receipts"]
    assert receipts["valid"] == 1
    assert receipts["applied"] == {"guided-decision": 1}
    assert receipts["duplicates_ignored"] == 1
    assert receipts["conflicting"] == 1
    assert receipts["invalid"] == {"receipt-lesson-not-returned-by-ckr6": 1, "receipt-result-not-found": 1}
    assert metrics["lessons_selected"] == 1 and metrics["selected_without_receipt"] == []
    assert metrics["lesson_candidates"] == {"reusable-new": 2}
    assert metrics["candidate_recurrences"] == 1
    assert metrics["malformed_markers"] == {"receipt": 1}
    assert metrics["accountability"] == {"LL-999": "not-in-accountability-catalog"}
    assert metrics["causality_inferred"] is False
    json.dumps(metrics)


def test_metrics_reuse_ckr12_accountability_by_lesson_number():
    result_body = bridge.serialize_ckr6_result_comment(sufficient_result((("LL-36", REVISION),)), request_comment_id=500)
    metrics = derive_lesson_metrics({1: [_comment(501, result_body)]})
    assert metrics["accountability"]["LL-36"] != "not-in-accountability-catalog"
    assert metrics["selected_without_receipt"] == [f"LL-36@{REVISION}"]


# ------------------------------------- live follow-up (#3418, 2026-10-09)

API_RECEIPT_REF = "https://api.github.com/repos/Blummer92/agent-os/issues/comments/6080491160"


def test_anchor_free_api_receipt_reference_is_accepted():
    parsed = loop.parse_refinement(refinement(receipt_refs=[API_RECEIPT_REF]))
    assert parsed["receipt_refs"] == (API_RECEIPT_REF,)
    for bad in ("https://api.github.com/repos/Other/repo/issues/comments/1",
                "https://api.github.com/repos/Blummer92/agent-os/issues/comments/x",
                "`" + RECEIPT_REF):
        with pytest.raises(ValueError):
            loop.parse_refinement(refinement(receipt_refs=[bad]))


def _main_result(monkeypatch, tmp_path, body, retrieval_required):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({
        "repository": {"full_name": "Blummer92/agent-os"}, "issue": {"number": 3418},
        "comment": {"id": 6080494403, "body": body, "user": {"login": "Blummer92"}},
    }), encoding="utf-8")
    output = tmp_path / "result.json"
    read = reader([row()])

    def never_read(query):
        raise AssertionError("a rejected detail must not read")

    monkeypatch.setattr(bridge, "resolve_lesson_read_route",
                        lambda: type("Route", (), {"execute_read": staticmethod(never_read)})())
    monkeypatch.setattr("sys.argv", [
        "ckr6", "--phase", "execute", "--event", str(event_path), "--repository", "Blummer92/agent-os",
        "--allowed-actor", "Blummer92", "--output", str(output),
        "--retrieval-required", "true" if retrieval_required else "false",
    ])
    assert bridge.main() == 0
    return json.loads(output.read_text(encoding="utf-8")), read


def test_live_host_rewritten_refinement_returns_bounded_rejection(monkeypatch, tmp_path):
    # Exact failure shape of run 37927552170: the host inserted a backtick
    # before the #issuecomment receipt URL and appended its footer.
    detail = refinement()
    detail["receipt_refs"] = ["`" + RECEIPT_REF]
    body = bridge.COMMAND_PREFIX + json.dumps({
        "operation": "lesson-refinement", "repository": "Blummer92/agent-os", "issue_number": 3418,
        "task_reference": "#3418 live acceptance F", "refinement": detail,
    }) + "\n\n---\n_Generated by [Claude Code](https://claude.ai/code)_\n"
    result, _ = _main_result(monkeypatch, tmp_path, body, True)
    assert result["status"] == "rejected"
    assert result["reason_codes"] == ["envelope-rejected:refinement-receipt-refs-invalid"]
    assert result["revision_proposal"] is None and result["notion_read_performed"] is False
    assert "`" not in json.dumps(result)
    parsed = bridge.parse_ckr6_result_comment(bridge.serialize_ckr6_result_comment(result, request_comment_id=6080494403))
    assert parsed["operation"] == "lesson-refinement"


@pytest.mark.parametrize(("change", "code"), [
    ({"signal": "anything"}, "candidate-detail-invalid"),
    ({"source_reference": ""}, "field-invalid"),
    ({"reusable_rule_proven": "yes"}, "candidate-detail-invalid"),
])
def test_malformed_candidate_detail_returns_bounded_rejection(monkeypatch, tmp_path, change, code):
    body = bridge.COMMAND_PREFIX + json.dumps({
        "operation": "lesson-candidate", "repository": "Blummer92/agent-os", "issue_number": 3418,
        "task_reference": "#3418", "candidate": candidate(**change),
    })
    result, _ = _main_result(monkeypatch, tmp_path, body, False)
    assert (result["status"], result["reason_codes"]) == ("rejected", ["envelope-rejected:" + code])
    assert result["lesson_proposal"] is None
