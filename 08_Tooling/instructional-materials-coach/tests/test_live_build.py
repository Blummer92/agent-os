from unittest.mock import MagicMock, patch

import pytest

from instructional_materials_coach.live_build import LiveBuildInput, build_live_materials


def _build():
    return LiveBuildInput(
        slides_template_id="slides-template", doc_template_id="doc-template", target_folder_id="folder",
        slides_name="Lesson - Slides", doc_name="Lesson - Worksheet", idempotency_key="k" * 64,
        slides_requests=({"replaceAllText": {}},), docs_requests=({"replaceAllText": {}},),
    )


def _meta(file_id, mime, role=None):
    props = {}
    if role:
        props = {"agent_os_idempotency_key": "k" * 64, "agent_os_artifact_role": role}
    return {"id": file_id, "mimeType": mime, "parents": ["folder"], "trashed": False, "appProperties": props, "webViewLink": f"https://example/{file_id}"}


def _preflight():
    return patch("instructional_materials_coach.live_build.verify_template"), patch("instructional_materials_coach.live_build.verify_target_folder")


def test_preflight_failure_blocks_before_copy():
    with patch("instructional_materials_coach.live_build.verify_template", side_effect=RuntimeError("cannot copy")), patch("instructional_materials_coach.live_build.duplicate_template") as copy:
        with pytest.raises(RuntimeError, match="cannot copy"):
            build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    copy.assert_not_called()


def test_zero_matches_creates_both_and_updates_with_revision_controls():
    slides = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    doc = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], []]), patch("instructional_materials_coach.live_build.duplicate_template", side_effect=[slides, doc]), patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s-rev"), patch("instructional_materials_coach.live_build.get_docs_revision_id", return_value="d-rev"), patch("instructional_materials_coach.live_build.apply_slides_requests") as s_apply, patch("instructional_materials_coach.live_build.apply_docs_requests") as d_apply, patch("instructional_materials_coach.live_build.verify_final_copy", side_effect=[slides, doc]):
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.succeeded
    assert s_apply.call_args.kwargs["required_revision_id"] == "s-rev"
    assert d_apply.call_args.kwargs["required_revision_id"] == "d-rev"


def test_one_exact_match_recovers_without_duplicate():
    recovered = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    doc = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[recovered], []]), patch("instructional_materials_coach.live_build.duplicate_template", return_value=doc) as copy, patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s"), patch("instructional_materials_coach.live_build.get_docs_revision_id", return_value="d"), patch("instructional_materials_coach.live_build.apply_slides_requests"), patch("instructional_materials_coach.live_build.apply_docs_requests"), patch("instructional_materials_coach.live_build.verify_final_copy", side_effect=[recovered, doc]):
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.succeeded and copy.call_count == 1


def test_multiple_idempotency_matches_require_manual_reconciliation():
    duplicate = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", return_value=[duplicate, dict(duplicate, id="other")]), patch("instructional_materials_coach.live_build.duplicate_template") as copy:
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.slides.state == "ambiguous" and receipt.manual_reconciliation_required
    copy.assert_not_called()


def test_ambiguous_copy_reconciles_before_any_retry():
    recovered = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    doc = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], [recovered], []]) as find, patch("instructional_materials_coach.live_build.duplicate_template", side_effect=[TimeoutError("unknown"), doc]) as copy, patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s"), patch("instructional_materials_coach.live_build.get_docs_revision_id", return_value="d"), patch("instructional_materials_coach.live_build.apply_slides_requests"), patch("instructional_materials_coach.live_build.apply_docs_requests"), patch("instructional_materials_coach.live_build.verify_final_copy", side_effect=[recovered, doc]):
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.succeeded and copy.call_count == 2 and find.call_count == 3


def test_unresolved_ambiguous_copy_stops_without_second_create():
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], []]), patch("instructional_materials_coach.live_build.duplicate_template", side_effect=TimeoutError("unknown")) as copy:
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.slides.state == "ambiguous" and receipt.manual_reconciliation_required
    copy.assert_called_once()


def test_slides_created_docs_copy_fails_preserves_partial_state():
    slides = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], [], []]), patch("instructional_materials_coach.live_build.duplicate_template", side_effect=[slides, TimeoutError("doc unknown")]), patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s"), patch("instructional_materials_coach.live_build.apply_slides_requests"), patch("instructional_materials_coach.live_build.verify_final_copy", return_value=slides):
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.slides.state == "updated" and receipt.worksheet.state == "ambiguous" and receipt.slides.file_id == "slides-id"


def test_slides_update_failure_stops_before_docs_copy():
    slides = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", return_value=[]), patch("instructional_materials_coach.live_build.duplicate_template", return_value=slides) as copy, patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s"), patch("instructional_materials_coach.live_build.apply_slides_requests", side_effect=RuntimeError("revision mismatch")):
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.slides.state == "failed" and receipt.worksheet.state == "planned" and copy.call_count == 1


def test_docs_update_failure_preserves_slides_success():
    slides = _meta("slides-id", "application/vnd.google-apps.presentation", "slides")
    doc = _meta("doc-id", "application/vnd.google-apps.document", "worksheet")
    p1, p2 = _preflight()
    with p1, p2, patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=[[], []]), patch("instructional_materials_coach.live_build.duplicate_template", side_effect=[slides, doc]), patch("instructional_materials_coach.live_build.get_slides_revision_id", return_value="s"), patch("instructional_materials_coach.live_build.get_docs_revision_id", return_value="d"), patch("instructional_materials_coach.live_build.apply_slides_requests"), patch("instructional_materials_coach.live_build.apply_docs_requests", side_effect=RuntimeError("revision mismatch")), patch("instructional_materials_coach.live_build.verify_final_copy", return_value=slides):
        receipt = build_live_materials(_build(), drive_service=MagicMock(), slides_service=MagicMock(), docs_service=MagicMock())
    assert receipt.slides.state == "updated" and receipt.worksheet.state == "failed"


def test_core_callable_has_no_credential_environment_shell_scheduler_or_notion_imports():
    import inspect
    import instructional_materials_coach.live_build as live_build
    source = inspect.getsource(live_build).lower()
    for forbidden in ("installedappflow", "get_credentials", "os.environ", "subprocess", "scheduler", "notion"):
        assert forbidden not in source
