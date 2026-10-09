"""#3416: canonical worksheets keep headings with the content that follows.

Migrates the #3176 pagination rule into the governed build (#3259 D1/D1b):
the build applies ``keepWithNext`` to heading paragraphs that lack it,
between text replacement and #3257 placement, and #3258 terminal QA refuses
``final`` when any heading lacks it.

The build/QA tests at the top use only APIs that exist before #3416, so the
same file demonstrates the defect on the pre-fix tree. The resolver/planner
tests import the new module lazily for the same reason. All fixtures are
synthetic and unit-agnostic.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from instructional_materials_coach.artifact_content_qa import (
    TerminalQAExpectations,
    qa_evidence_path,
    run_terminal_qa,
)
from instructional_materials_coach.live_build import LiveBuildInput, build_live_materials
from instructional_materials_coach.workspace_clients import apply_docs_requests

KEY = "kwn-key-" + "k" * 56
DOCS_REQUESTS = (
    {"replaceAllText": {"containsText": {"text": "{{title}}", "matchCase": True},
                        "replaceText": "Shape Study"}},
)


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self) -> Any:
        return self._fn()


class _WorksheetDocs:
    """In-memory Docs service holding one worksheet copy.

    The body is a title line carrying a ``{{title}}`` placeholder, one
    ``HEADING_2`` section heading, and its section text. ``batchUpdate``
    enforces ``requiredRevisionId``, applies ``replaceAllText`` and
    ``updateParagraphStyle``, bumps the revision, and logs each write.
    Indices are recomputed on every read, as in the real API.
    """

    def __init__(self, *, named_keep: bool | None = None, direct_keep: bool | None = None,
                 events: list[str] | None = None):
        self.revision = 1
        self.named_keep = named_keep
        self.events = events if events is not None else []
        self.writes: list[dict[str, Any]] = []
        self.paragraphs = [
            {"text": "Worksheet {{title}}\n", "style": "TITLE", "keep": None},
            {"text": "Section heading\n", "style": "HEADING_2", "keep": direct_keep},
            {"text": "Section text that belongs with its heading.\n", "style": "NORMAL_TEXT", "keep": None},
        ]

    def documents(self) -> "_WorksheetDocs":
        return self

    def _ranges(self) -> list[tuple[int, int]]:
        ranges, index = [], 1
        for paragraph in self.paragraphs:
            end = index + len(paragraph["text"])
            ranges.append((index, end))
            index = end
        return ranges

    def resource(self) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"endIndex": 1, "sectionBreak": {}}]
        for paragraph, (start, end) in zip(self.paragraphs, self._ranges()):
            style: dict[str, Any] = {"namedStyleType": paragraph["style"]}
            if paragraph["keep"] is not None:
                style["keepWithNext"] = paragraph["keep"]
            content.append({
                "startIndex": start, "endIndex": end,
                "paragraph": {
                    "elements": [{"startIndex": start, "endIndex": end,
                                  "textRun": {"content": paragraph["text"]}}],
                    "paragraphStyle": style,
                },
            })
        heading_style: dict[str, Any] = {}
        if self.named_keep is not None:
            heading_style["keepWithNext"] = self.named_keep
        return {
            "documentId": "doc-id",
            "revisionId": f"rev-{self.revision}",
            "body": {"content": content},
            "namedStyles": {"styles": [
                {"namedStyleType": "NORMAL_TEXT", "paragraphStyle": {"keepWithNext": False}},
                {"namedStyleType": "HEADING_2", "paragraphStyle": heading_style},
            ]},
        }

    def get(self, *, documentId: str, fields: str | None = None) -> _Exec:
        return _Exec(self.resource)

    def batchUpdate(self, *, documentId: str, body: dict[str, Any]) -> _Exec:
        def _run() -> dict[str, Any]:
            required = (body.get("writeControl") or {}).get("requiredRevisionId")
            if required is not None and required != f"rev-{self.revision}":
                raise RuntimeError("revision mismatch")
            self.writes.append(body)
            replies: list[dict[str, Any]] = []
            kinds: list[str] = []
            for request in body["requests"]:
                if "replaceAllText" in request:
                    spec = request["replaceAllText"]
                    token, replacement = spec["containsText"]["text"], spec["replaceText"]
                    changed = 0
                    for paragraph in self.paragraphs:
                        changed += paragraph["text"].count(token)
                        paragraph["text"] = paragraph["text"].replace(token, replacement)
                    replies.append({"replaceAllText": {"occurrencesChanged": changed}})
                    kinds.append("text")
                elif "updateParagraphStyle" in request:
                    spec = request["updateParagraphStyle"]
                    assert spec["fields"] == "keepWithNext"
                    low, high = spec["range"]["startIndex"], spec["range"]["endIndex"]
                    for paragraph, (start, end) in zip(self.paragraphs, self._ranges()):
                        if start < high and low < end:
                            paragraph["keep"] = spec["paragraphStyle"]["keepWithNext"]
                    replies.append({})
                    kinds.append("style")
                else:  # pragma: no cover - the fake models only these writes
                    raise AssertionError(f"unexpected request {request}")
            self.events.extend(sorted(set(kinds)))
            self.revision += 1
            return {"replies": replies}

        return _Exec(_run)


class _CleanSlides:
    def presentations(self) -> "_CleanSlides":
        return self

    def get(self, *, presentationId: str, fields: str | None = None) -> _Exec:
        return _Exec(lambda: {"presentationId": presentationId, "revisionId": "s1", "slides": []})


def _meta(file_id: str, mime: str, role: str) -> dict[str, Any]:
    return {"id": file_id, "mimeType": mime, "parents": ["folder"], "trashed": False,
            "appProperties": {"agent_os_idempotency_key": KEY, "agent_os_artifact_role": role},
            "webViewLink": f"https://example/{file_id}"}


SLIDES_META = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
DOC_META = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")


def _build_input() -> LiveBuildInput:
    return LiveBuildInput(
        slides_template_id="slides-template", doc_template_id="doc-template",
        target_folder_id="folder", slides_name="S", doc_name="W", idempotency_key=KEY,
        slides_requests=(), docs_requests=DOCS_REQUESTS,
        qa_expectations=TerminalQAExpectations.build_from_requests(
            idempotency_key=KEY, docs_requests=DOCS_REQUESTS),
    )


def _run_build(docs: _WorksheetDocs, *, events: list[str], recovered: bool = False,
               resume_dir=None, place=None):
    metas = {"slides-id": SLIDES_META, "doc-id": DOC_META}
    copies = [[SLIDES_META], [DOC_META]] if recovered else [[], []]

    def _verify(_drive, file_id, **kwargs):
        events.append(f"verify:{kwargs['role']}")
        return metas[file_id]

    def _place(**kwargs):
        events.append(f"placement:{kwargs['artifact_type']}")
        if place is not None:
            place(**kwargs)

    with patch("instructional_materials_coach.live_build.verify_template"), \
         patch("instructional_materials_coach.live_build.verify_target_folder"), \
         patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=copies), \
         patch("instructional_materials_coach.live_build.duplicate_template",
               side_effect=[SLIDES_META, DOC_META]), \
         patch("instructional_materials_coach.live_build.verify_final_copy", side_effect=_verify), \
         patch("instructional_materials_coach.live_build._place_artifact_visuals", side_effect=_place):
        return build_live_materials(
            _build_input(), drive_service=MagicMock(), slides_service=_CleanSlides(),
            docs_service=docs, resume_dir=resume_dir,
        )


def _style_writes(docs: _WorksheetDocs) -> list[dict[str, Any]]:
    return [w for w in docs.writes if any("updateParagraphStyle" in r for r in w["requests"])]


# ---------------------------------------------------------------------------
# Build: the canonical path applies the rule (red on the pre-fix tree)
# ---------------------------------------------------------------------------

def test_build_keeps_template_heading_with_its_section():
    events: list[str] = []
    docs = _WorksheetDocs(events=events)
    receipt = _run_build(docs, events=events)

    assert receipt.succeeded, (receipt.worksheet.state, receipt.worksheet.error)
    assert docs.paragraphs[1]["keep"] is True, "persisted heading lacks keepWithNext"
    # Only the heading changed; title and body paragraphs are untouched.
    assert docs.paragraphs[0]["keep"] is None and docs.paragraphs[2]["keep"] is None


def test_style_write_runs_after_text_and_before_placement_and_verification():
    events: list[str] = []
    docs = _WorksheetDocs(events=events)
    _run_build(docs, events=events)

    worksheet_events = [e for e in events if not e.endswith(":slides")]
    assert worksheet_events == ["text", "style", "placement:docs", "verify:worksheet"]


def test_style_write_is_one_batch_bound_to_the_revision_it_was_planned_from():
    events: list[str] = []
    docs = _WorksheetDocs(events=events)
    _run_build(docs, events=events)

    style_writes = _style_writes(docs)
    assert len(style_writes) == 1
    # The text write produced rev-2; the plan was read at rev-2, so its range
    # reflects the replaced title ("Worksheet Shape Study\n" ends at 23).
    assert style_writes[0]["writeControl"] == {"requiredRevisionId": "rev-2"}
    assert style_writes[0]["requests"] == [{
        "updateParagraphStyle": {
            "range": {"startIndex": 23, "endIndex": 39},
            "paragraphStyle": {"keepWithNext": True},
            "fields": "keepWithNext",
        }
    }]


def test_no_style_write_when_template_heading_style_already_keeps_with_next():
    events: list[str] = []
    docs = _WorksheetDocs(named_keep=True, events=events)
    receipt = _run_build(docs, events=events)

    assert receipt.succeeded
    assert _style_writes(docs) == []
    assert docs.revision == 2  # only the text write bumped the revision


def test_direct_false_overrides_named_style_and_is_corrected():
    events: list[str] = []
    docs = _WorksheetDocs(named_keep=True, direct_keep=False, events=events)
    receipt = _run_build(docs, events=events)

    assert receipt.succeeded
    assert len(_style_writes(docs)) == 1
    assert docs.paragraphs[1]["keep"] is True


def test_resume_after_placement_failure_sends_no_duplicate_style_write(tmp_path):
    events: list[str] = []
    docs = _WorksheetDocs(events=events)
    resume_dir = tmp_path / "resume"

    def _fail_docs_placement(**kwargs):
        if kwargs["artifact_type"] == "docs":
            raise RuntimeError("placement transport interrupted")

    first = _run_build(docs, events=events, resume_dir=resume_dir, place=_fail_docs_placement)
    assert first.worksheet.state == "failed"
    assert len(_style_writes(docs)) == 1

    second = _run_build(docs, events=events, recovered=True, resume_dir=resume_dir)
    assert second.succeeded, (second.worksheet.state, second.worksheet.error)
    assert len(_style_writes(docs)) == 1  # the retry found the rule satisfied


def test_unreadable_document_writes_nothing_and_is_never_final():
    with patch("instructional_materials_coach.live_build.verify_template"), \
         patch("instructional_materials_coach.live_build.verify_target_folder"), \
         patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], []]), \
         patch("instructional_materials_coach.live_build.duplicate_template",
               side_effect=[SLIDES_META, DOC_META]), \
         patch("instructional_materials_coach.live_build.get_docs_revision_id", return_value="d"), \
         patch("instructional_materials_coach.live_build.apply_docs_requests") as apply, \
         patch("instructional_materials_coach.live_build.verify_final_copy",
               side_effect=[SLIDES_META, DOC_META]):
        receipt = build_live_materials(
            _build_input(), drive_service=MagicMock(), slides_service=_CleanSlides(),
            docs_service=MagicMock(),
        )
    assert apply.call_count == 1  # the text write only
    assert not receipt.succeeded and not receipt.worksheet.is_final


# ---------------------------------------------------------------------------
# Terminal QA: a heading without keep-with-next is never final
# ---------------------------------------------------------------------------

def _qa(docs: _WorksheetDocs, *, qa_evidence_dir=None):
    for paragraph in docs.paragraphs:
        paragraph["text"] = paragraph["text"].replace("{{title}}", "Shape Study")
    return run_terminal_qa(
        expectations=TerminalQAExpectations.build_from_requests(
            idempotency_key=KEY, docs_requests=DOCS_REQUESTS),
        slides_service=_CleanSlides(), docs_service=docs,
        slides_file_id="slides-id", worksheet_file_id="doc-id",
        receipts_dir=None, qa_evidence_dir=qa_evidence_dir,
    )


def test_qa_refuses_a_heading_without_keep_with_next():
    report = _qa(_WorksheetDocs())

    assert report.worksheet.state == "pagination-unverified"
    assert report.state != "verified"
    codes = [f.code for f in report.worksheet.findings]
    assert codes == ["qa-heading-keep-with-next-missing"]
    finding = report.worksheet.findings[0]
    assert finding.severity == "fail"
    assert finding.detail["count"] == 1
    assert finding.detail["headings"] == [
        {"start_index": 23, "named_style_type": "HEADING_2", "text": "Section heading"}
    ]
    assert report.slides.state == "verified"  # Slides carry no paragraph styles


@pytest.mark.parametrize(("named_keep", "direct_keep"), ((True, None), (None, True), (False, True)))
def test_qa_verifies_effective_keep_with_next(named_keep, direct_keep):
    report = _qa(_WorksheetDocs(named_keep=named_keep, direct_keep=direct_keep))

    assert report.worksheet.state == "verified", report.worksheet.findings
    assert report.state == "verified"


def test_pre_rule_verified_evidence_is_not_recovered(tmp_path):
    docs = _WorksheetDocs()
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY, docs_requests=DOCS_REQUESTS)
    verified = {"state": "verified", "findings": []}
    path = qa_evidence_path(tmp_path, KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "evidence_contract_version": "terminal-qa-evidence-v1",
        "idempotency_key": KEY,
        "state": "verified",
        "expectations_hash": expectations.expectations_hash(),
        "slides": {**verified, "artifact_id": "slides-id", "revision_id": "s1"},
        "worksheet": {**verified, "artifact_id": "doc-id", "revision_id": "rev-1"},
    }), encoding="utf-8")

    report = _qa(docs, qa_evidence_dir=tmp_path)

    assert not report.worksheet.recovered
    assert report.worksheet.state == "pagination-unverified"


# ---------------------------------------------------------------------------
# Write path: non-replace requests are accepted
# ---------------------------------------------------------------------------

def test_apply_docs_requests_accepts_paragraph_style_requests():
    docs = _WorksheetDocs()
    request = {"updateParagraphStyle": {
        "range": {"startIndex": 21, "endIndex": 37},
        "paragraphStyle": {"keepWithNext": True}, "fields": "keepWithNext"}}

    apply_docs_requests(docs, "doc-id", [request], required_revision_id="rev-1")

    assert docs.writes[0]["writeControl"] == {"requiredRevisionId": "rev-1"}
    assert docs.paragraphs[1]["keep"] is True


# ---------------------------------------------------------------------------
# Resolver and planner (pure)
# ---------------------------------------------------------------------------

def _pagination():
    from instructional_materials_coach import worksheet_pagination

    return worksheet_pagination


def _paragraph(start: int, end: int, style: str, keep: bool | None = None, text: str = "Heading\n"):
    paragraph_style: dict[str, Any] = {"namedStyleType": style}
    if keep is not None:
        paragraph_style["keepWithNext"] = keep
    return {"startIndex": start, "endIndex": end, "paragraph": {
        "elements": [{"textRun": {"content": text}}], "paragraphStyle": paragraph_style}}


def _document(content: list[dict[str, Any]], named: dict[str, bool | None] | None = None):
    styles = []
    for style_type, keep in (named or {}).items():
        paragraph_style = {} if keep is None else {"keepWithNext": keep}
        styles.append({"namedStyleType": style_type, "paragraphStyle": paragraph_style})
    return {"body": {"content": content}, "namedStyles": {"styles": styles}}


@pytest.mark.parametrize(
    ("direct", "named", "expected"),
    (
        (True, {}, True),
        (False, {"HEADING_1": True}, False),
        (None, {"HEADING_1": True}, True),
        (None, {"HEADING_1": None, "NORMAL_TEXT": True}, True),
        (None, {"HEADING_1": False, "NORMAL_TEXT": True}, False),
        (None, {}, False),
    ),
)
def test_effective_keep_with_next_resolution(direct, named, expected):
    document = _document([_paragraph(1, 9, "HEADING_1", direct)], named)

    (heading,) = _pagination().heading_paragraphs(document)
    assert heading.keep_with_next is expected


def test_headings_inside_table_cells_are_found():
    cell = {"content": [_paragraph(5, 13, "HEADING_3")]}
    table = {"startIndex": 3, "endIndex": 20, "table": {"tableRows": [{"tableCells": [cell]}]}}
    document = _document([_paragraph(1, 3, "NORMAL_TEXT", text="x\n"), table])

    headings = _pagination().heading_paragraphs(document)
    assert [(h.start_index, h.named_style_type) for h in headings] == [(5, "HEADING_3")]


def test_planner_targets_only_headings_lacking_the_rule_in_index_order():
    document = _document([
        _paragraph(30, 40, "HEADING_2"),
        _paragraph(1, 10, "HEADING_1"),
        _paragraph(10, 20, "NORMAL_TEXT", text="Body text\n"),
        _paragraph(20, 30, "HEADING_2", True),
        _paragraph(40, 50, "TITLE", text="Title\n"),
    ])

    requests = _pagination().plan_keep_with_next_requests(document)
    assert [r["updateParagraphStyle"]["range"] for r in requests] == [
        {"startIndex": 1, "endIndex": 10},
        {"startIndex": 30, "endIndex": 40},
    ]
    assert all(r["updateParagraphStyle"]["fields"] == "keepWithNext" for r in requests)
    assert all(r["updateParagraphStyle"]["paragraphStyle"] == {"keepWithNext": True} for r in requests)


def test_planner_is_empty_when_every_heading_already_keeps_with_next():
    document = _document([_paragraph(1, 10, "HEADING_1"), _paragraph(10, 20, "HEADING_4", True)],
                         {"HEADING_1": True})

    assert _pagination().plan_keep_with_next_requests(document) == []


def test_non_mapping_document_has_no_headings():
    assert _pagination().heading_paragraphs(MagicMock()) == ()
    assert _pagination().plan_keep_with_next_requests(None) == []
