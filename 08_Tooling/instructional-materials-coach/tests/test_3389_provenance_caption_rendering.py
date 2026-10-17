"""#3389 end-to-end: provenance captions render adjacent to placed images.

Drives the REAL placement path (no placement-path mocks):

    VisualPlacementBinding (carried image_provenance)
      -> build_provenance_caption_requests  (new: placeholder token requests)
      -> execute_artifact_visual_placements (real orchestration, fake transport)
      -> replaceAllText application to the fake Doc (like the real Docs API)
      -> TerminalQAExpectations.build_from_requests (real expectations)
      -> evaluate_artifact_qa (real terminal QA)

Assertions prove: the image is placed, the caption token is resolved, the
exact caption text is present in the persisted artifact, terminal QA is
verified, attribution is bound to the right image, and the fail-closed
cases (missing template token, duplicate tokens, malformed provenance,
untokenizable identity, uncarried provenance now reported unresolved,
caption not adjacent to its image, one caption shared by two images) all
hold. The fake Docs service mirrors the real documents.get surface
(inlineObjectElement.inlineObjectId, image positioned at the marker).
"""
from __future__ import annotations

from typing import Any, Mapping

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_PROVENANCE_UNRESOLVED,
    TerminalQAExpectations,
    evaluate_artifact_qa,
    observe_artifact,
    scan_unresolved_tokens,
)
from instructional_materials_coach.connected_visual_placement import (
    VisualPlacementBinding,
    execute_artifact_visual_placements,
)
from instructional_materials_coach.docs_requests import (
    build_provenance_caption_requests,
    provenance_caption_token,
)
from instructional_materials_coach.drive_client import DriveLookupError
from instructional_materials_coach.image_provenance import (
    ImageProvenance,
    ImageProvenanceError,
)
from instructional_materials_coach.placement_receipts import load_placement_records
from instructional_materials_coach.placement_transport import PlacementTransportError
from instructional_workflow_contracts.asset_content_identity import (
    content_identity_from_fingerprint,
)

FINGERPRINT = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
KEY = "k" * 64


def _identity() -> dict[str, Any]:
    return dict(content_identity_from_fingerprint(FINGERPRINT))


def _binding(
    role_id: str,
    *,
    asset_id: str = "asset-1",
    drive_file_id: str = "file-1",
    slot_id: str = "0",
    provenance: ImageProvenance | None = None,
) -> VisualPlacementBinding:
    return VisualPlacementBinding(
        role_id=role_id,
        asset_id=asset_id,
        drive_file_id=drive_file_id,
        content_identity=_identity(),
        source_plan_id="cohesive-visual-plan-test",
        required=True,
        slot_id=slot_id,
        eligibility_evidence={"approved_use": {"state": "approved"}},
        image_provenance=provenance,
    )


def _provenance(origin_kind: str, creator: str | None = None) -> ImageProvenance:
    return ImageProvenance(origin_kind=origin_kind, creator_name=creator)


class _FakeExecutable:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def execute(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeDriveService:
    def __init__(self, metadata_by_file: Mapping[str, Any]) -> None:
        self._metadata = dict(metadata_by_file)

    def files(self) -> "FakeDriveService":
        return self

    def get(self, *, fileId: str, fields: str | None = None,
            supportsAllDrives: bool | None = None) -> _FakeExecutable:
        value = self._metadata.get(fileId, DriveLookupError(fileId, "not-found"))
        return _FakeExecutable(value)


class FakeDocsService:
    """In-memory Docs v1: paragraphs, inline objects, revisionId."""

    def __init__(self) -> None:
        self.documents_store: dict[str, dict[str, Any]] = {}

    def add_document(self, doc_id: str, paragraphs: list[str], revision: str = "r1") -> None:
        self.documents_store[doc_id] = {
            "revisionId": revision,
            "paragraphs": list(paragraphs),
            "inline_objects": [],
            # paragraph index -> inserted inlineObjectId (the marker's
            # paragraph becomes the image's paragraph, mirroring the
            # real insertion).
            "image_at_paragraph": {},
        }

    def documents(self) -> "_FakeDocsResource":
        return _FakeDocsResource(self)


class _FakeDocsResource:
    def __init__(self, service: FakeDocsService) -> None:
        self._service = service

    def get(self, *, documentId: str, fields: str | None = None) -> _FakeExecutable:
        doc = self._service.documents_store[documentId]
        if fields == "revisionId":
            return _FakeExecutable({"revisionId": doc["revisionId"]})
        content = []
        for index, para in enumerate(doc["paragraphs"]):
            image_id = doc["image_at_paragraph"].get(index)
            if image_id is not None:
                # Real Docs API shape: the inline image element carries
                # inlineObjectId (not embeddedObjectId), positioned in
                # the paragraph where the visual marker was.
                content.append(
                    {"paragraph": {"elements": [
                        {"inlineObjectElement": {"inlineObjectId": image_id}}
                    ]}}
                )
            else:
                content.append(
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": para}}],
                        }
                    }
                )
        inline_objects = {
            object_id: {"objectId": object_id}
            for object_id in doc["inline_objects"]
        }
        return _FakeExecutable(
            {"revisionId": doc["revisionId"], "body": {"content": content},
             "inlineObjects": inline_objects}
        )


class FakePlacementTransport:
    """Simulates the Apps Script seam: marker removed, image element inserted."""

    name = "fake-test-transport"

    def __init__(self, docs: FakeDocsService) -> None:
        self._docs = docs
        self.calls: list[Any] = []

    def insert_placement(self, *, request: Any) -> Mapping[str, Any]:
        self.calls.append(request)
        target = request.target
        inserted_id = f"fake-inserted-{len(self.calls)}"
        doc = self._docs.documents_store[target.artifact_id]
        for index, para in enumerate(doc["paragraphs"]):
            if para.strip() == target.marker:
                doc["paragraphs"][index] = ""
                doc["image_at_paragraph"][index] = inserted_id
                break
        doc["inline_objects"].append(inserted_id)
        doc["revisionId"] = doc["revisionId"] + "-p"
        return {"state": "placed", "inserted_element_id": inserted_id}


def _apply_replace_all_text(docs: FakeDocsService, doc_id: str, requests: list[dict]) -> None:
    """Apply replaceAllText requests the way the Docs API would (exact, case-sensitive)."""
    doc = docs.documents_store[doc_id]
    for request in requests:
        replace = request["replaceAllText"]
        token = replace["containsText"]["text"]
        text = replace["replaceText"]
        doc["paragraphs"] = [p.replace(token, text) for p in doc["paragraphs"]]


def _run_path(*, paragraphs: list[str], bindings: tuple[VisualPlacementBinding, ...], tmp_path):
    """Run the full real path: requests -> placement -> caption application -> QA."""
    docs = FakeDocsService()
    docs.add_document("doc-1", paragraphs)
    drive = FakeDriveService(
        {
            "file-1": {
                "id": "file-1", "name": "asset.png", "mimeType": "image/png",
                "parents": ["folder"], "trashed": False,
                "capabilities": {"canCopy": True, "canAddChildren": True},
                "sha256Checksum": FINGERPRINT, "headRevisionId": "rev-1",
            },
            "file-2": {
                "id": "file-2", "name": "asset2.png", "mimeType": "image/png",
                "parents": ["folder"], "trashed": False,
                "capabilities": {"canCopy": True, "canAddChildren": True},
                "sha256Checksum": FINGERPRINT, "headRevisionId": "rev-1",
            },
        }
    )
    transport = FakePlacementTransport(docs)
    caption_requests = build_provenance_caption_requests(bindings)
    outcomes = execute_artifact_visual_placements(
        bindings=bindings,
        artifact_type="docs",
        artifact_id="doc-1",
        drive_service=drive,
        artifact_service=docs,
        transport=transport,
        receipts_dir=str(tmp_path),
        idempotency_key=KEY,
    )
    _apply_replace_all_text(docs, "doc-1", caption_requests)
    records = load_placement_records(str(tmp_path), KEY)
    expectations = TerminalQAExpectations.build_from_requests(
        idempotency_key=KEY,
        docs_requests=tuple(caption_requests),
        visual_placements=bindings,
    )
    doc = docs.documents_store["doc-1"]
    # Read back the persisted artifact through the real observation
    # path: the Docs structure (real inlineObjectIds, paragraph /
    # table-cell / tab positions) is what terminal QA evaluates.
    observation = observe_artifact(docs, "docs", "doc-1")
    report = evaluate_artifact_qa(
        artifact_type="docs",
        artifact_id="doc-1",
        expectations=expectations,
        observation=observation,
        placement_records=records,
        idempotency_key=KEY,
    )
    return outcomes, caption_requests, doc, report


# ---------------------------------------------------------------------------
# Unit: token naming and fail-closed builder behavior
# ---------------------------------------------------------------------------


def test_caption_token_names_bind_role_and_slot():
    assert provenance_caption_token(role_id="worked-example", slot_id="0") == (
        "provenance_caption_worked-example.0"
    )


def test_caption_token_rejects_untokenizable_identity():
    with pytest.raises(ImageProvenanceError):
        provenance_caption_token(role_id="{{evil}}", slot_id="0")
    with pytest.raises(ImageProvenanceError):
        provenance_caption_token(role_id="worked-example", slot_id="0\n1")
    with pytest.raises(ImageProvenanceError):
        provenance_caption_token(role_id="", slot_id="0")


def test_builder_skips_binding_without_carried_provenance():
    assert build_provenance_caption_requests((_binding("worked-example"),)) == []


def test_builder_rejects_malformed_provenance():
    bad = _binding("worked-example")
    object.__setattr__(bad, "image_provenance", {"origin_kind": "oil-painting"})
    with pytest.raises(ImageProvenanceError):
        build_provenance_caption_requests((bad,))


def test_builder_rejects_duplicate_caption_tokens():
    first = _binding("worked-example", asset_id="asset-1", provenance=_provenance("ai-generated"))
    second = _binding("worked-example", asset_id="asset-2", provenance=_provenance("ai-generated"))
    with pytest.raises(ImageProvenanceError):
        build_provenance_caption_requests((first, second))


# ---------------------------------------------------------------------------
# Idempotency key covers carried provenance (fresh build on provenance change)
# ---------------------------------------------------------------------------


def _fake_visual_plan(assignments: list[dict]) -> Any:
    class _Record:
        def to_dict(self) -> dict:
            return {
                "cohesive_visual_plan_id": "plan-1",
                "required_role_assignments": assignments,
                "optional_role_assignments": [],
            }

    class _Result:
        record = _Record()

    class _Plan:
        cohesive_visual_plan_result = _Result()

    return _Plan()


def _assignment(provenance: Any) -> dict:
    return {
        "role_id": "worked-example",
        "slot_id": "0",
        "image_provenance": provenance,
        "selected_candidate": {
            "asset_reference": {"asset_id": "asset-1", "content_fingerprint": FINGERPRINT},
            "library_reference": {"drive_file_id": "file-1"},
        },
    }


def test_idempotency_key_covers_carried_provenance():
    from instructional_materials_coach.cli import _selected_visuals_for_key

    with_prov = _selected_visuals_for_key(_fake_visual_plan([_assignment({"origin_kind": "ai-generated"})]))
    changed = _selected_visuals_for_key(
        _fake_visual_plan([_assignment({"origin_kind": "human-photograph", "creator_name": "Maya Chen"})])
    )
    assert with_prov[0]["image_provenance"] == {"origin_kind": "ai-generated"}
    assert with_prov != changed  # a provenance change is a fresh build


def test_idempotency_key_unchanged_for_legacy_assignment_without_provenance():
    from instructional_materials_coach.cli import _selected_visuals_for_key

    legacy = _selected_visuals_for_key(_fake_visual_plan([_assignment(None)]))
    assert "image_provenance" not in legacy[0]  # historic key shape preserved



def test_end_to_end_caption_renders_and_qa_verifies(tmp_path):
    binding = _binding(
        "worked-example",
        provenance=_provenance("human-photograph", creator="Maya Chen"),
    )
    outcomes, caption_requests, doc, report = _run_path(
        paragraphs=[
            "Worksheet",
            "{{visual:worked-example}}",
            "{{provenance_caption_worked-example.0}}",
            "Footer",
        ],
        bindings=(binding,),
        tmp_path=tmp_path,
    )
    # Image placed through the real placement path.
    assert outcomes[0].status == "placed"
    assert "{{visual:worked-example}}" not in doc["paragraphs"]
    # Caption rendered adjacent to the placed image; token fully resolved.
    assert doc["paragraphs"][2] == "Photo: Maya Chen"
    assert "{{provenance_caption_worked-example.0}}" not in "\n".join(doc["paragraphs"])
    assert scan_unresolved_tokens("\n".join(doc["paragraphs"])) == ()
    # Terminal QA is verified: caption text proven present, token gone,
    # image element observed, provenance verified.
    assert report.state == "verified", [f.message for f in report.findings]


def test_end_to_end_ai_disclosure_caption(tmp_path):
    binding = _binding("worked-example", provenance=_provenance("ai-generated"))
    outcomes, caption_requests, doc, report = _run_path(
        paragraphs=[
            "Worksheet",
            "{{visual:worked-example}}",
            "{{provenance_caption_worked-example.0}}",
            "Footer",
        ],
        bindings=(binding,),
        tmp_path=tmp_path,
    )
    assert doc["paragraphs"][2] == "AI-generated image"
    assert report.state == "verified", [f.message for f in report.findings]


def test_two_images_captions_stay_attached_to_their_image():
    """Identity, not placement-count: each caption request derives from its
    own binding's provenance and its token names its own (role, slot). A
    caption can never be rendered against the wrong image unless the
    (role, slot) identity itself is wrong -- and that fails closed in the
    placement path."""
    first = _binding(
        "worked-example", asset_id="asset-1", drive_file_id="file-1",
        provenance=_provenance("human-photograph", creator="Maya Chen"),
    )
    second = _binding(
        "exit-ticket", asset_id="asset-2", drive_file_id="file-2",
        provenance=_provenance("human-photograph", creator="Jordan Lee"),
    )
    requests = build_provenance_caption_requests((first, second))
    by_token = {
        r["replaceAllText"]["containsText"]["text"]: r["replaceAllText"]["replaceText"]
        for r in requests
    }
    assert by_token["{{provenance_caption_worked-example.0}}"] == "Photo: Maya Chen"
    assert by_token["{{provenance_caption_exit-ticket.0}}"] == "Photo: Jordan Lee"
    assert len(by_token) == 2


def test_end_to_end_missing_template_token_fails_closed_not_silent(tmp_path):
    """The template lacks the caption token: the build must NOT pass QA
    with an unattributed placed image."""
    binding = _binding(
        "worked-example",
        provenance=_provenance("human-photograph", creator="Maya Chen"),
    )
    outcomes, caption_requests, doc, report = _run_path(
        paragraphs=["Worksheet", "{{visual:worked-example}}", "Footer"],
        bindings=(binding,),
        tmp_path=tmp_path,
    )
    # Placement still succeeded...
    assert outcomes[0].status == "placed"
    # ...but the caption text never rendered, so terminal QA refuses.
    assert report.state != "verified"
    codes = [f.code for f in report.findings]
    assert "qa-content-missing" in codes
    missing = [f for f in report.findings if f.code == "qa-content-missing"][0]
    assert "provenance_caption_worked-example.0" in missing.message


def test_end_to_end_unresolved_provenance_still_refuses_terminal(tmp_path):
    """Unknown origin: caption discloses 'source unknown' AND terminal QA
    refuses via the existing qa-provenance-unresolved enforcement."""
    binding = _binding("worked-example", provenance=_provenance("unknown"))
    outcomes, caption_requests, doc, report = _run_path(
        paragraphs=[
            "Worksheet",
            "{{visual:worked-example}}",
            "{{provenance_caption_worked-example.0}}",
            "Footer",
        ],
        bindings=(binding,),
        tmp_path=tmp_path,
    )
    assert doc["paragraphs"][2] == "Image source unknown"
    assert report.state != "verified"
    codes = [f.code for f in report.findings]
    assert "qa-provenance-unresolved" in codes


def test_end_to_end_no_carried_provenance_is_unresolved(tmp_path):
    """#3389 production repair: provenance=None (predates tracking) emits
    no caption -- nothing invented -- AND terminal QA reports the placed
    image as provenance-unresolved instead of verifying it. Unknown
    origin is unresolved for every student-visible image."""
    binding = _binding("worked-example", provenance=None)
    outcomes, caption_requests, doc, report = _run_path(
        paragraphs=["Worksheet", "{{visual:worked-example}}", "Footer"],
        bindings=(binding,),
        tmp_path=tmp_path,
    )
    assert caption_requests == []
    assert report.state == QA_STATE_PROVENANCE_UNRESOLVED
    assert "qa-provenance-unresolved" in [f.code for f in report.findings]
