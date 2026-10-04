"""#3258 red/green proof of the terminal-QA false positive.

This file is intentionally standalone: it imports NOTHING from the Wave 4
QA contract at module level, so the same file runs against the pre-repair
base (where it FAILS, demonstrating the bug) and against the repaired tree
(where it PASSES).

False positive eliminated: on the pre-repair base, a build whose persisted
artifact still carried an unresolved ``{{title}}`` token reported
``succeeded``/``final`` from Drive metadata alone. With Wave 4, terminal
QA reads back the persisted artifact, finds the token, and refuses
terminal success: the receipt is ``persisted`` (metadata-verified), never
``final``.
"""
from __future__ import annotations

from typing import Any


class _Executable:
    def __init__(self, payload: Any):
        self._payload = payload

    def execute(self) -> Any:
        return self._payload


def test_red_unresolved_token_build_reported_final_on_pre_repair_base():
    from unittest.mock import MagicMock, patch

    from instructional_materials_coach.live_build import LiveBuildInput, build_live_materials

    try:
        from instructional_materials_coach.artifact_content_qa import TerminalQAExpectations
    except ImportError:
        TerminalQAExpectations = None  # pre-repair base: no QA contract

    key = "red-key-" + "k" * 56
    docs_requests = ({"replaceAllText": {"containsText": {"text": "{{title}}"},
                                         "replaceText": "Fractions Intro"}},)

    class _TokenDocsService:
        """Readback shows the token was never replaced (the write lied, or a
        later mutation restored it)."""

        def documents(self):
            return self

        def get(self, *, documentId: str, fields: str | None = None):
            return _Executable({
                "documentId": documentId,
                "revisionId": "r1",
                "body": {"content": [{"paragraph": {"elements": [
                    {"textRun": {"content": "{{title}}\n"}}]}}]},
            })

    class _CleanSlidesService:
        def presentations(self):
            return self

        def get(self, *, presentationId: str, fields: str | None = None):
            return _Executable({"presentationId": presentationId,
                                "revisionId": "r1", "slides": []})

    kwargs: dict[str, Any] = dict(
        slides_template_id="slides-template", doc_template_id="doc-template",
        target_folder_id="folder", slides_name="S", doc_name="W",
        idempotency_key=key, slides_requests=(), docs_requests=docs_requests,
    )
    if TerminalQAExpectations is not None:
        kwargs["qa_expectations"] = TerminalQAExpectations.build_from_requests(
            idempotency_key=key, docs_requests=docs_requests, slides_requests=())

    def _meta(file_id, mime, role):
        return {"id": file_id, "mimeType": mime, "parents": ["folder"], "trashed": False,
                "appProperties": {"agent_os_idempotency_key": key, "agent_os_artifact_role": role},
                "webViewLink": f"https://example/{file_id}"}

    slides_meta = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    doc_meta = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")
    build = LiveBuildInput(**kwargs)  # type: ignore[arg-type]
    with patch("instructional_materials_coach.live_build.verify_template"), \
         patch("instructional_materials_coach.live_build.verify_target_folder"), \
         patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], []]), \
         patch("instructional_materials_coach.live_build.duplicate_template", side_effect=[slides_meta, doc_meta]), \
         patch("instructional_materials_coach.live_build.apply_slides_requests"), \
         patch("instructional_materials_coach.live_build.apply_docs_requests"), \
         patch("instructional_materials_coach.live_build.verify_final_copy", side_effect=[slides_meta, doc_meta]):
        receipt = build_live_materials(
            build, drive_service=MagicMock(),
            slides_service=_CleanSlidesService(), docs_service=_TokenDocsService(),
        )
    # The persisted worksheet still carries {{title}}: terminal success is
    # refused. (On the pre-repair base this assertion fails: the build
    # reported final from metadata alone.)
    assert not receipt.succeeded, (
        "build reported final with an unresolved token persisted: "
        f"worksheet qa={getattr(receipt.worksheet, 'terminal_qa_state', 'n/a (pre-repair)')}"
    )
    if hasattr(receipt.worksheet, "is_persisted"):
        # Wave 4 receipt semantics: metadata-only verification is
        # "persisted", never "final".
        assert receipt.worksheet.is_persisted and not receipt.worksheet.is_final
