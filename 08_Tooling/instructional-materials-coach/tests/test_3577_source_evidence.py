"""#3577: independently injected source-content receipts + required gate.

The lesson-revision YAML spec is an assertion, never a self-certified read
receipt. Source evidence is injected independently (existing Drive
metadata/fetch tools + the host page-reader boundary) and bound fail-closed
by ``bind_source_evidence``. A required gate can never be disabled by missing
optional inputs, including for scheduled consumers.
"""

from __future__ import annotations

import hashlib

import pytest
import yaml

from instructional_materials_coach.artifact_content_qa import TerminalQAExpectations
from instructional_materials_coach.build_request import (
    compose_governed_build_request,
    live_build_input_factory,
)
from instructional_materials_coach.cli import (
    _load_lesson_revision_spec,
    retrieve_deck_source_receipt,
)
from instructional_materials_coach.worksheet_revision_qa import (
    SourceContentReceipt,
    SourcePage,
    WorksheetRevisionQAError,
    bind_source_evidence,
    parse_lesson_revision_spec,
)

_QA_KEY = "k" * 64
_DRIVE_ID = "drive-deck-convenience-1"
_DRIVE_REVISION = "drv-rev-2026-10-13"
_FILENAME = "Marketing_Foundations_Day1_Convenience_Revised.pdf"
_MEDIA = b"%PDF-1.4 retrieved deck bytes"


def _spec_dict():
    return {
        "lesson_id": "day-1",
        "deck": {
            "revision_id": "deck-new",
            "filename": _FILENAME,
            "drive_id": _DRIVE_ID,
            "slide_mapping_source": "independent deck read via Drive",
        },
        "learning_targets": [{"id": "target-1", "concept": "Compare"}],
        "worksheet": {"lesson_id": "day-1", "synced_deck_revision_id": "deck-new"},
        "coverage_matrix": [
            {
                "target_id": "target-1",
                "deck_slide_note": "exact slide 2",
                "worksheet_tasks": ["warm-up"],
            }
        ],
    }


def _receipt(*, drive_id=_DRIVE_ID, endorsed=True, pages=None, digest=None):
    actual_digest = digest or "sha256:" + hashlib.sha256(_MEDIA).hexdigest()
    return SourceContentReceipt(
        source_drive_id=drive_id,
        source_filename=_FILENAME,
        source_revision_id=_DRIVE_REVISION,
        content_digest=actual_digest,
        pages=() if pages is None else pages,
        retrieved_at="2026-10-16T12:00:00+00:00",
        source_provenance="drive-v3-files-get-media:" + drive_id,
        teacher_owner_identity="teacher@example.org" if endorsed else None,
        teacher_endorsed=endorsed,
    )


# --- bind_source_evidence ----------------------------------------------------


def test_bind_attaches_independently_retrieved_receipt() -> None:
    spec = parse_lesson_revision_spec(_spec_dict())
    receipt = _receipt(pages=(SourcePage(1, 2, "Slide 2: compare convenience"),))
    bound = bind_source_evidence(spec, receipt)
    assert bound.source_evidence is receipt
    assert bound.slide_refs_validated
    # The original parsed spec is unchanged (assertion stays an assertion).
    assert spec.source_evidence is None
    assert not spec.slide_refs_validated


def test_bind_rejects_non_receipt() -> None:
    spec = parse_lesson_revision_spec(_spec_dict())
    with pytest.raises(WorksheetRevisionQAError):
        bind_source_evidence(spec, {"source_drive_id": _DRIVE_ID})


def test_bind_rejects_drive_revision_mismatch() -> None:
    spec_dict = _spec_dict()
    spec_dict["deck"]["drive_revision_id"] = "drv-rev-expected"
    spec = parse_lesson_revision_spec(spec_dict)
    receipt = _receipt(pages=(SourcePage(1, 2, "text"),))
    assert receipt.source_revision_id != "drv-rev-expected"
    with pytest.raises(WorksheetRevisionQAError):
        bind_source_evidence(spec, receipt)


def test_bind_accepts_matching_asserted_digest_and_revision() -> None:
    digest = "sha256:" + hashlib.sha256(_MEDIA).hexdigest()
    spec_dict = _spec_dict()
    spec_dict["deck"]["content_digest"] = digest
    spec_dict["deck"]["drive_revision_id"] = _DRIVE_REVISION
    spec = parse_lesson_revision_spec(spec_dict)
    bound = bind_source_evidence(
        spec, _receipt(pages=(SourcePage(1, 2, "text"),))
    )
    assert bound.source_evidence is not None


def test_receipt_fingerprint_binds_all_fields() -> None:
    pages = (SourcePage(1, 2, "Slide 2: compare convenience"),)
    first = _receipt(pages=pages).receipt_fingerprint()
    assert first == _receipt(pages=pages).receipt_fingerprint()
    assert first != _receipt(pages=()).receipt_fingerprint()
    assert first != _receipt(pages=pages, endorsed=False).receipt_fingerprint()
    assert first != _receipt(pages=pages, drive_id="other").receipt_fingerprint()


# --- retrieve_deck_source_receipt (existing Drive tools) ---------------------


class _FakeExecutable:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeFiles:
    def __init__(self, metadata, media):
        self._metadata = metadata
        self._media = media

    def get(self, **kwargs):
        assert kwargs["fileId"] == _DRIVE_ID
        return _FakeExecutable(self._metadata)

    def get_media(self, **kwargs):
        assert kwargs["fileId"] == _DRIVE_ID
        return _FakeExecutable(self._media)


class _FakeDriveService:
    def __init__(self, metadata, media):
        self._files = _FakeFiles(metadata, media)

    def files(self):
        return self._files


def _drive_service(*, media=_MEDIA, mime="application/pdf"):
    metadata = {
        "id": _DRIVE_ID,
        "name": _FILENAME,
        "mimeType": mime,
        "headRevisionId": _DRIVE_REVISION,
    }
    return _FakeDriveService(metadata, media)


def test_retrieve_builds_receipt_from_drive_tools() -> None:
    spec = parse_lesson_revision_spec(_spec_dict())
    receipt = retrieve_deck_source_receipt(
        _drive_service(),
        spec,
        page_reader=lambda data, mime: (SourcePage(1, 2, "Slide 2 text"),),
        teacher_approval={"owner_identity": "teacher@example.org", "approved": True},
    )
    assert receipt.source_drive_id == _DRIVE_ID
    assert receipt.source_filename == _FILENAME
    assert receipt.source_revision_id == _DRIVE_REVISION
    assert receipt.content_digest == "sha256:" + hashlib.sha256(_MEDIA).hexdigest()
    assert receipt.pages == (SourcePage(1, 2, "Slide 2 text"),)
    assert receipt.retrieved_at
    assert receipt.source_provenance.startswith("drive-v3-files-get-media:")
    # Teacher approval is a separate assertion, never derived from the hash.
    assert receipt.teacher_owner_identity == "teacher@example.org"
    assert receipt.teacher_endorsed


def test_retrieve_without_teacher_approval_is_not_approved() -> None:
    spec = parse_lesson_revision_spec(_spec_dict())
    receipt = retrieve_deck_source_receipt(_drive_service(), spec)
    assert not receipt.teacher_endorsed
    assert receipt.teacher_owner_identity is None


def test_retrieve_requires_asserted_drive_id() -> None:
    spec_dict = _spec_dict()
    del spec_dict["deck"]["drive_id"]
    spec = parse_lesson_revision_spec(spec_dict)
    with pytest.raises(WorksheetRevisionQAError):
        retrieve_deck_source_receipt(_drive_service(), spec)


def test_retrieve_propagates_drive_lookup_failure() -> None:
    class _FailingDriveService:
        def files(self):
            raise RuntimeError("drive unavailable")

    spec = parse_lesson_revision_spec(_spec_dict())
    with pytest.raises(Exception, match="drive unavailable"):
        retrieve_deck_source_receipt(_FailingDriveService(), spec)


# --- _load_lesson_revision_spec (CLI injection point) ------------------------


def test_cli_load_binds_injected_receipt(tmp_path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(_spec_dict()), encoding="utf-8")
    receipt = _receipt(pages=(SourcePage(1, 2, "Slide 2 text"),))
    spec = _load_lesson_revision_spec(
        str(path), source_reader=lambda drive_service, parsed: receipt
    )
    assert spec.source_evidence is receipt
    assert spec.slide_refs_validated


def test_cli_load_rejects_typed_yaml_evidence(tmp_path) -> None:
    spec_dict = _spec_dict()
    spec_dict["deck_evidence"] = {"kind": "teacher-owned-deck-read"}
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec_dict), encoding="utf-8")
    with pytest.raises(RuntimeError, match="deck_evidence"):
        _load_lesson_revision_spec(str(path))


def test_cli_load_rejects_unbindable_receipt(tmp_path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(_spec_dict()), encoding="utf-8")
    with pytest.raises(RuntimeError, match="rejected"):
        _load_lesson_revision_spec(
            str(path),
            source_reader=lambda drive_service, parsed: _receipt(drive_id="foreign-deck"),
        )


def test_cli_load_without_evidence_returns_unbound_spec(tmp_path) -> None:
    """The authentic revised Day-1 PDF is unavailable: no receipt can be
    retrieved, so the spec stays unbound and terminal QA routes to MANUAL
    REVIEW (not verified, not failed)."""
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(_spec_dict()), encoding="utf-8")

    def _missing(drive_service, parsed):
        raise RuntimeError("file not found in Drive")

    spec = _load_lesson_revision_spec(str(path), source_reader=_missing)
    assert spec.source_evidence is None


# --- required gate: CLI and scheduled consumers -----------------------------


def _inputs(**overrides):
    data = dict(
        slides_template_id="slides", doc_template_id="docs",
        target_folder_id="folder", content_title="Unit",
        idempotency_key="key", slides_requests=(), docs_requests=(),
        visual_placements=(), resume_dir="resume",
        placement_transport=None, placement_receipts_dir="placements",
        qa_evidence_dir="qa",
    )
    data.update(overrides)
    return data


def test_required_gate_refuses_missing_spec_at_composition() -> None:
    """A required gate can never be disabled by missing optional inputs."""
    with pytest.raises(ValueError, match="governed-lesson-revision-required-but-missing"):
        compose_governed_build_request(**_inputs(lesson_revision_required=True))


def test_optional_gate_stays_unarmed_without_spec() -> None:
    request = compose_governed_build_request(**_inputs())
    assert request.build_input.qa_expectations.lesson_revision is None
    assert not request.build_input.qa_expectations.lesson_revision_required


def test_required_gate_armed_in_expectations() -> None:
    spec = bind_source_evidence(
        parse_lesson_revision_spec(_spec_dict()),
        _receipt(pages=(SourcePage(1, 2, "Slide 2 text"),)),
    )
    request = compose_governed_build_request(
        **_inputs(lesson_revision_spec=spec, lesson_revision_required=True)
    )
    expectations = request.build_input.qa_expectations
    assert expectations.lesson_revision_required
    assert expectations.lesson_revision is spec


def test_scheduled_consumer_required_gate_refuses_missing_spec() -> None:
    """Scheduled builds declare the dependency through the shared composer:
    required-but-missing spec fails for scheduled consumers too."""

    def resolver(request, subject):
        return _inputs(lesson_revision_required=True)

    with pytest.raises(ValueError, match="governed-lesson-revision-required-but-missing"):
        live_build_input_factory(object(), {}, governed_inputs_resolver=resolver)


def test_scheduled_consumer_required_gate_armed() -> None:
    spec = bind_source_evidence(
        parse_lesson_revision_spec(_spec_dict()),
        _receipt(pages=(SourcePage(1, 2, "Slide 2 text"),)),
    )

    def resolver(request, subject):
        return _inputs(lesson_revision_spec=spec, lesson_revision_required=True)

    scheduled = live_build_input_factory(object(), {}, governed_inputs_resolver=resolver)
    assert scheduled.build_input.qa_expectations.lesson_revision_required
    assert scheduled.build_input.qa_expectations.lesson_revision is spec


def test_expectations_hash_binds_required_flag_and_receipt() -> None:
    spec = parse_lesson_revision_spec(_spec_dict())
    bound = bind_source_evidence(
        spec, _receipt(pages=(SourcePage(1, 2, "Slide 2 text"),))
    )
    base = TerminalQAExpectations(idempotency_key=_QA_KEY)
    unbound = TerminalQAExpectations(idempotency_key=_QA_KEY, lesson_revision=spec)
    bound_exp = TerminalQAExpectations(idempotency_key=_QA_KEY, lesson_revision=bound)
    required_exp = TerminalQAExpectations(
        idempotency_key=_QA_KEY, lesson_revision=bound, lesson_revision_required=True
    )
    hashes = {
        base.expectations_hash(),
        unbound.expectations_hash(),
        bound_exp.expectations_hash(),
        required_exp.expectations_hash(),
    }
    # Four distinct expectation identities: unbound vs bound vs required.
    assert len(hashes) == 4
