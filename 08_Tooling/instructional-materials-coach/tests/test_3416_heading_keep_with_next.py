"""#3416: canonical worksheet heading keep-with-next, applied and verified.

Synthetic, unit-agnostic Docs JSON only; injected fake clients only.
"""
from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock, patch

import pytest

from instructional_materials_coach import artifact_content_qa as qa
from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_LAYOUT_RULE_VIOLATED,
    QA_STATE_VERIFIED,
    TerminalQAExpectations,
    run_terminal_qa,
)
from instructional_materials_coach.live_build import LiveBuildInput, build_live_materials
from instructional_materials_coach.workspace_clients import apply_docs_requests
from instructional_materials_coach.worksheet_pagination import (
    heading_paragraphs,
    headings_missing_keep_with_next,
    plan_heading_keep_with_next_requests,
)

KEY = "h" * 64


def _paragraph(start, end, style, text, keep=None):
    paragraph_style = {"namedStyleType": style}
    if keep is not None:
        paragraph_style["keepWithNext"] = keep
    return {
        "startIndex": start,
        "endIndex": end,
        "paragraph": {
            "paragraphStyle": paragraph_style,
            "elements": [{"textRun": {"content": text}}],
        },
    }


def _document(content, named=None, revision="rev-1"):
    doc = {"documentId": "doc-id", "revisionId": revision, "body": {"content": content}}
    if named is not None:
        doc["namedStyles"] = {
            "styles": [
                {"namedStyleType": name, "paragraphStyle": {"keepWithNext": value}}
                for name, value in named.items()
            ]
        }
    return doc


def _widow_fixture(keep=None):
    """Section heading followed by its first content block (the #3176 shape)."""
    return _document(
        [
            _paragraph(1, 10, "NORMAL_TEXT", "Intro.\n"),
            _paragraph(10, 20, "HEADING_2", "Section\n", keep=keep),
            _paragraph(20, 40, "NORMAL_TEXT", "First task.\n"),
        ]
    )


# --- resolver --------------------------------------------------------------


def test_effective_value_precedence_own_then_named_then_normal_then_false():
    doc = _document(
        [
            _paragraph(1, 5, "HEADING_1", "A\n", keep=False),
            _paragraph(5, 9, "HEADING_2", "B\n"),
            _paragraph(9, 13, "HEADING_3", "C\n"),
        ],
        named={"HEADING_1": True, "HEADING_2": True, "NORMAL_TEXT": False},
    )
    values = {h.named_style_type: h.keep_with_next for h in heading_paragraphs(doc)}
    assert values == {"HEADING_1": False, "HEADING_2": True, "HEADING_3": False}

    inherited = _document([_paragraph(1, 5, "HEADING_4", "D\n")], named={"NORMAL_TEXT": True})
    assert heading_paragraphs(inherited)[0].keep_with_next is True
    assert heading_paragraphs(_document([_paragraph(1, 5, "HEADING_6", "E\n")]))[0].keep_with_next is False


def test_table_cell_headings_are_found_and_non_headings_ignored():
    table = {
        "startIndex": 20,
        "endIndex": 60,
        "table": {
            "tableRows": [
                {"tableCells": [{"content": [_paragraph(22, 30, "HEADING_2", "Band\n")]}]}
            ]
        },
    }
    doc = _document([_paragraph(1, 20, "NORMAL_TEXT", "Body\n"), table, _paragraph(60, 70, "TITLE", "T\n")])
    assert [(h.start_index, h.named_style_type) for h in heading_paragraphs(doc)] == [(22, "HEADING_2")]


def test_heading_without_index_range_fails_closed():
    bad = _document([{"paragraph": {"paragraphStyle": {"namedStyleType": "HEADING_1"}, "elements": []}}])
    with pytest.raises(ValueError, match="startIndex/endIndex"):
        heading_paragraphs(bad)


# --- planner ---------------------------------------------------------------


def test_plan_is_deterministic_ordered_and_scoped_to_heading_ranges():
    doc = _document(
        [
            _paragraph(30, 40, "HEADING_2", "Second\n"),
            _paragraph(1, 10, "HEADING_1", "First\n"),
            _paragraph(10, 30, "NORMAL_TEXT", "Body\n"),
            _paragraph(40, 50, "HEADING_3", "Done\n", keep=True),
        ]
    )
    plan = plan_heading_keep_with_next_requests(doc)
    assert plan == plan_heading_keep_with_next_requests(copy.deepcopy(doc))
    assert [request["updateParagraphStyle"]["range"] for request in plan] == [
        {"startIndex": 1, "endIndex": 10},
        {"startIndex": 30, "endIndex": 40},
    ]
    for request in plan:
        assert request["updateParagraphStyle"]["paragraphStyle"] == {"keepWithNext": True}
        assert request["updateParagraphStyle"]["fields"] == "keepWithNext"


def test_plan_is_empty_when_every_heading_is_already_effective():
    doc = _document([_paragraph(1, 10, "HEADING_1", "A\n")], named={"HEADING_1": True})
    assert plan_heading_keep_with_next_requests(doc) == ()
    assert headings_missing_keep_with_next(doc) == ()


def test_docs_write_path_accepts_non_replace_requests():
    service = MagicMock()
    service.documents.return_value.batchUpdate.return_value.execute.return_value = {"replies": [{}]}
    requests = list(plan_heading_keep_with_next_requests(_widow_fixture()))
    apply_docs_requests(service, "doc-id", requests, required_revision_id="rev-1")
    body = service.documents.return_value.batchUpdate.call_args.kwargs["body"]
    assert body == {"requests": requests, "writeControl": {"requiredRevisionId": "rev-1"}}


# --- terminal QA -----------------------------------------------------------


class _Executable:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeDocs:
    """Stateful Docs fake: get returns the stored doc, batchUpdate applies styles."""

    def __init__(self, document):
        self.document = document
        self.batch_bodies: list[dict] = []
        self.events: list[str] = []

    def documents(self):
        return self

    def get(self, *, documentId, fields=None):
        assert documentId == "doc-id"
        return _Executable(copy.deepcopy(self.document))

    def batchUpdate(self, *, documentId, body):
        self.batch_bodies.append(body)
        replies = []
        for request in body["requests"]:
            update = request.get("updateParagraphStyle")
            if update is not None:
                self.events.append("style")
                start = update["range"]["startIndex"]
                for element in self.document["body"]["content"]:
                    if element.get("startIndex") == start and "paragraph" in element:
                        element["paragraph"]["paragraphStyle"]["keepWithNext"] = True
                replies.append({})
            else:
                self.events.append("text")
                replies.append({"replaceAllText": {"occurrencesChanged": 1}})
        current = int(self.document["revisionId"].split("-")[1])
        self.document["revisionId"] = f"rev-{current + 1}"
        return _Executable({"replies": replies})


class _FakeSlides:
    def presentations(self):
        return self

    def get(self, *, presentationId, fields=None):
        return _Executable({"presentationId": presentationId, "revisionId": "s-rev", "slides": []})


def _qa(document):
    return run_terminal_qa(
        expectations=TerminalQAExpectations.build_from_requests(idempotency_key=KEY),
        slides_service=_FakeSlides(),
        docs_service=_FakeDocs(document),
        slides_file_id="slides-id",
        worksheet_file_id="doc-id",
        receipts_dir=None,
    )


def test_qa_refuses_final_for_heading_without_effective_keep_with_next():
    report = _qa(_widow_fixture())
    assert report.worksheet.state == QA_STATE_LAYOUT_RULE_VIOLATED
    assert report.state != QA_STATE_VERIFIED
    finding = [f for f in report.worksheet.findings if f.severity == "fail"][0]
    assert finding.code == "qa-heading-keep-with-next-missing"
    assert finding.detail["start_index"] == 10


def test_qa_verifies_when_heading_keeps_with_next():
    assert _qa(_widow_fixture(keep=True)).worksheet.state == QA_STATE_VERIFIED


def test_pre_rule_verified_evidence_is_not_recovered(tmp_path):
    doc = _widow_fixture()
    stored = {
        "evidence_contract_version": "terminal-qa-evidence-v1",
        "state": QA_STATE_VERIFIED,
        "expectations_hash": TerminalQAExpectations.build_from_requests(idempotency_key=KEY).expectations_hash(),
        "worksheet": {"state": QA_STATE_VERIFIED, "artifact_id": "doc-id", "revision_id": doc["revisionId"], "findings": []},
        "slides": {"state": QA_STATE_VERIFIED, "artifact_id": "slides-id", "revision_id": "s-rev", "findings": []},
    }
    (tmp_path / f"{KEY}.json").write_text(json.dumps(stored), encoding="utf-8")
    assert qa.QA_EVIDENCE_CONTRACT != "terminal-qa-evidence-v1"
    report = run_terminal_qa(
        expectations=TerminalQAExpectations.build_from_requests(idempotency_key=KEY),
        slides_service=_FakeSlides(),
        docs_service=_FakeDocs(doc),
        slides_file_id="slides-id",
        worksheet_file_id="doc-id",
        receipts_dir=None,
        qa_evidence_dir=tmp_path,
    )
    assert report.worksheet.recovered is False
    assert report.worksheet.state == QA_STATE_LAYOUT_RULE_VIOLATED


# --- canonical build -------------------------------------------------------


def _meta(file_id, mime, role):
    return {
        "id": file_id, "mimeType": mime, "parents": ["folder"], "trashed": False,
        "appProperties": {"agent_os_idempotency_key": KEY, "agent_os_artifact_role": role},
        "webViewLink": f"https://example/{file_id}",
    }


def _build_input(visual_placements=()):
    docs_requests = (
        {"replaceAllText": {"containsText": {"text": "{{title}}", "matchCase": True}, "replaceText": "Intro."}},
    )
    return LiveBuildInput(
        slides_template_id="slides-template", doc_template_id="doc-template", target_folder_id="folder",
        slides_name="Lesson - Slides", doc_name="Lesson - Worksheet", idempotency_key=KEY,
        slides_requests=(), docs_requests=docs_requests,
        visual_placements=visual_placements,
        qa_expectations=TerminalQAExpectations.build_from_requests(idempotency_key=KEY, docs_requests=docs_requests),
    )


def _run_build(docs, **kwargs):
    slides_meta = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    doc_meta = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")
    with patch("instructional_materials_coach.live_build.verify_template"), \
         patch("instructional_materials_coach.live_build.verify_target_folder"), \
         patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], []]), \
         patch("instructional_materials_coach.live_build.duplicate_template", side_effect=[slides_meta, doc_meta]), \
         patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s-rev"), \
         patch("instructional_materials_coach.live_build.verify_final_copy", side_effect=[slides_meta, doc_meta]):
        return build_live_materials(
            _build_input(**kwargs), drive_service=MagicMock(), slides_service=_FakeSlides(), docs_service=docs,
        )


def test_build_applies_rule_once_revision_bound_and_reaches_final():
    docs = _FakeDocs(_widow_fixture())
    receipt = _run_build(docs)
    style_bodies = [b for b in docs.batch_bodies if "updateParagraphStyle" in b["requests"][0]]
    assert len(style_bodies) == 1
    assert style_bodies[0]["requests"] == list(plan_heading_keep_with_next_requests(_widow_fixture()))
    # Bound to the revision read in the same step (after the text batch).
    assert style_bodies[0]["writeControl"] == {"requiredRevisionId": "rev-2"}
    assert docs.events == ["text", "style"]
    assert receipt.worksheet.terminal_qa_state == QA_STATE_VERIFIED
    assert receipt.succeeded


def test_build_sends_nothing_when_headings_are_already_effective():
    docs = _FakeDocs(_widow_fixture(keep=True))
    receipt = _run_build(docs)
    assert docs.events == ["text"]
    assert receipt.succeeded


def test_style_write_happens_before_visual_placement():
    docs = _FakeDocs(_widow_fixture())
    order: list[str] = []
    original = docs.batchUpdate

    def _tracking_batch(**kwargs):
        if "updateParagraphStyle" in kwargs["body"]["requests"][0]:
            order.append("style")
        return original(**kwargs)

    docs.batchUpdate = _tracking_batch
    with patch(
        "instructional_materials_coach.live_build._place_artifact_visuals",
        side_effect=lambda **kwargs: order.append(f"place:{kwargs['artifact_type']}"),
    ):
        _run_build(docs)
    assert order == ["place:slides", "style", "place:docs"]


def test_red_green_success_never_leaves_a_persisted_heading_without_the_rule():
    """Uses only pre-#3416 APIs: on base the build reports success while the
    persisted worksheet heading still lacks keepWithNext (the defect)."""
    docs = _FakeDocs(_widow_fixture())
    receipt = _run_build(docs)
    headings = [
        element["paragraph"]["paragraphStyle"]
        for element in docs.document["body"]["content"]
        if element["paragraph"]["paragraphStyle"]["namedStyleType"].startswith("HEADING_")
    ]
    if receipt.succeeded:
        assert all(style.get("keepWithNext") is True for style in headings)
