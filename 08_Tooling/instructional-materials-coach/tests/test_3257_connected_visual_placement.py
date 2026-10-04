"""Wave-3 acceptance: connected visual placement (#3257).

Proves the normal connected Instructional Materials Coach path accepts a
governed selected visual and places the EXACT selected bytes into the
intended Google Doc/Slide with a verified, attributable PlacementReceipt --
by composing the existing #2087 placement contract, #3256 content
identity, #3252 continuation, and the #2087 Apps Script transport seam,
not by building new architecture.

Regression-matrix coverage (17 scenarios):
 1. eligible selected asset -> placed ............. test_docs/slides_placement, test_connected_build_regression
 2. teacher-selected asset -> exact selected revision placed ..... test_teacher_selected_asset_survives_continuation
 3. automatic selected asset -> exact selected revision placed ... test_automatic_selection_same_identity_contract
 4. one asset reused for permitted roles -> receipts per role ..... test_shared_asset_across_permitted_roles
 5. multiple distinct assets -> distinct placements .............. test_multiple_distinct_assets_distinct_roles
 6. provider content changed -> blocked as stale ................. test_stale_content_revision_blocked
 7. provider asset missing -> blocked as missing ................. test_missing_asset_blocked_as_missing
 8. provider access failure -> blocked as access failure ......... test_access_failure_blocked_as_access_failure
 9. placement runtime unavailable -> blocked .................... test_runtime_unavailable_fails_closed (+ CLI test)
10. marker/target missing -> placement failure, not absence ..... test_marker_missing_is_placement_failure_not_absence
11. identity conflict -> fail closed ............................ test_identity_conflict_fails_closed
12. retry after completed placement -> no duplicate .... test_partial_retry, test_build_retry_recovers_receipts
13. retry after partial placement -> only unresolved continue ... test_partial_retry_does_not_duplicate
14. continuation after teacher choice -> same selection .......... test_teacher_selected_asset_survives_continuation
15. placement failure -> never authorizes generation ............ test_placement_failure_never_authorizes_generation
16. normal imc-build with visuals -> no longer dies ............. test_connected_build_regression (+ CLI gate test)
17. receipt preserves role+asset+content identity ............... test_docs..., test_slides... (record-field assertions)

All external interaction uses injected fakes; no live Docs/Slides/Drive
mutation occurs in this suite.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from instructional_materials_coach.connected_visual_placement import (
    BindingOutcome,
    PlacementExecutionError,
    VisualPlacementBinding,
    execute_artifact_visual_placements,
    plan_visual_placement_bindings,
    require_all_required_visuals_placed,
)
from instructional_materials_coach.drive_client import DriveLookupError
from instructional_materials_coach.placement_receipts import load_placement_records
from instructional_materials_coach.placement_transport import (
    PlacementRuntimeUnavailable,
    PlacementTransportError,
)
from instructional_materials_coach.visual_placement import marker_for_role
from instructional_workflow_contracts.asset_content_identity import content_identity_from_fingerprint


FINGERPRINT = "c" * 64
STALE_FINGERPRINT = "d" * 64


def _identity(fingerprint: str = FINGERPRINT) -> dict[str, Any]:
    return dict(content_identity_from_fingerprint(fingerprint))


def _binding(
    role_id: str,
    *,
    asset_id: str = "asset-1",
    drive_file_id: str = "file-1",
    fingerprint: str = FINGERPRINT,
    required: bool = True,
    slot_id: str = "0",
    source_plan_id: str = "cohesive-visual-plan-test",
) -> VisualPlacementBinding:
    return VisualPlacementBinding(
        role_id=role_id,
        asset_id=asset_id,
        drive_file_id=drive_file_id,
        content_identity=_identity(fingerprint),
        source_plan_id=source_plan_id,
        required=required,
        slot_id=slot_id,
        eligibility_evidence={"approved_use": {"state": "approved"}},
    )


# ---------------------------------------------------------------------------
# Fake connected services
# ---------------------------------------------------------------------------


class _FakeExecutable:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def execute(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeDriveService:
    """Fake Drive v3 service: files().get(...).execute() -> metadata."""

    def __init__(self, metadata_by_file: Mapping[str, Any]) -> None:
        self._metadata = dict(metadata_by_file)

    def files(self) -> "FakeDriveService":
        return self

    def get(self, *, fileId: str, fields: str | None = None, supportsAllDrives: bool | None = None) -> _FakeExecutable:
        value = self._metadata.get(fileId, DriveLookupError(fileId, "not-found"))
        return _FakeExecutable(value)


def _drive_metadata(file_id: str, *, sha256: str = FINGERPRINT, trashed: bool = False) -> dict[str, Any]:
    return {
        "id": file_id,
        "name": "asset.png",
        "mimeType": "image/png",
        "parents": ["folder"],
        "trashed": trashed,
        "capabilities": {"canCopy": True, "canAddChildren": True},
        "sha256Checksum": sha256,
        "headRevisionId": "rev-1",
    }


class FakeDocsService:
    """Fake Docs v1 service over an in-memory document store.

    documents_store: doc_id -> {"revisionId": str, "paragraphs": [str, ...],
    "inline_objects": [embeddedObjectId, ...]}.
    """

    def __init__(self) -> None:
        self.documents_store: dict[str, dict[str, Any]] = {}

    def add_document(self, doc_id: str, paragraphs: list[str], revision: str = "r1") -> None:
        self.documents_store[doc_id] = {"revisionId": revision, "paragraphs": list(paragraphs), "inline_objects": []}

    def documents(self) -> "_FakeDocsResource":
        return _FakeDocsResource(self)


class _FakeDocsResource:
    def __init__(self, service: FakeDocsService) -> None:
        self._service = service

    def get(self, *, documentId: str, fields: str | None = None) -> _FakeExecutable:
        doc = self._service.documents_store[documentId]
        content = [
            {"paragraph": {"elements": [{"textRun": {"content": text + "\n"}}]}}
            for text in doc["paragraphs"]
        ]
        # #3258: placed visuals are observable as inline objects, mirroring
        # the real documents.get inlineObjects surface.
        for object_id in doc.get("inline_objects", []):
            content.append(
                {"paragraph": {"elements": [{"inlineObjectElement": {"embeddedObjectId": object_id}}]}}
            )
        inline_objects = {object_id: {"objectId": object_id} for object_id in doc.get("inline_objects", [])}
        return _FakeExecutable({"revisionId": doc["revisionId"], "body": {"content": content}, "inlineObjects": inline_objects})


class FakeSlidesService:
    """Fake Slides v1 service over an in-memory presentation store.

    presentations_store: pres_id -> {"revisionId": str,
        "slides": [{"objectId": str, "elements": [{"objectId": str, "text": str}]}]}.
    """

    def __init__(self) -> None:
        self.presentations_store: dict[str, dict[str, Any]] = {}

    def add_presentation(self, pres_id: str, slides: list[dict[str, Any]], revision: str = "r1") -> None:
        self.presentations_store[pres_id] = {"revisionId": revision, "slides": slides}

    def presentations(self) -> "_FakeSlidesResource":
        return _FakeSlidesResource(self)


class _FakeSlidesResource:
    def __init__(self, service: FakeSlidesService) -> None:
        self._service = service

    def get(self, *, presentationId: str, fields: str | None = None) -> _FakeExecutable:
        pres = self._service.presentations_store[presentationId]
        slides = [
            {
                "objectId": slide["objectId"],
                "pageElements": [
                    {
                        "objectId": element["objectId"],
                        "shape": {
                            "text": {
                                "textElements": [{"textRun": {"content": element["text"] + "\n"}}]
                            }
                        },
                    }
                    for element in slide["elements"]
                ],
            }
            for slide in pres["slides"]
        ]
        return _FakeExecutable({"revisionId": pres["revisionId"], "slides": slides})


class FakePlacementTransport:
    """Fake connected placement transport.

    Simulates the #2087 Apps Script seam: removes the marker from the fake
    artifact store and records an inserted element, returning a "placed"
    result. ``fail_for_roles`` makes insertion raise for chosen roles.
    """

    name = "fake-test-transport"

    def __init__(
        self,
        *,
        docs: FakeDocsService | None = None,
        slides: FakeSlidesService | None = None,
        fail_for_roles: set[str] | None = None,
    ) -> None:
        self._docs = docs
        self._slides = slides
        self._fail_for_roles = set(fail_for_roles or ())
        self.calls: list[Any] = []

    def insert_placement(self, *, request: Any) -> Mapping[str, Any]:
        self.calls.append(request)
        if request.role_id in self._fail_for_roles:
            raise PlacementTransportError(f"placement-transport-failed: simulated failure for role={request.role_id}")
        target = request.target
        inserted_id = f"fake-inserted-{len(self.calls)}"
        if target.artifact_type == "slides":
            assert self._slides is not None
            pres = self._slides.presentations_store[target.artifact_id]
            for slide in pres["slides"]:
                if slide["objectId"] != target.container_id:
                    continue
                for element in slide["elements"]:
                    if element["objectId"] == target.element_id and element["text"].strip() == target.marker:
                        element["text"] = ""
                slide["elements"].append({"objectId": inserted_id, "text": ""})
            pres["revisionId"] = pres["revisionId"] + "-p"
        else:
            assert self._docs is not None
            doc = self._docs.documents_store[target.artifact_id]
            doc["paragraphs"] = ["" if p.strip() == target.marker else p for p in doc["paragraphs"]]
            # #3258: the inserted visual is observable in readback as an
            # inline object, like the real Docs API.
            doc.setdefault("inline_objects", []).append(inserted_id)
            doc["revisionId"] = doc["revisionId"] + "-p"
        return {"state": "placed", "inserted_element_id": inserted_id}


def _execute(
    bindings: list[VisualPlacementBinding],
    *,
    artifact_type: str,
    artifact_id: str,
    drive: FakeDriveService,
    docs: FakeDocsService,
    slides: FakeSlidesService,
    transport: FakePlacementTransport,
    receipts_dir: Any,
    key: str = "k" * 64,
) -> tuple[BindingOutcome, ...]:
    service = slides if artifact_type == "slides" else docs
    return execute_artifact_visual_placements(
        bindings=tuple(bindings),
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        drive_service=drive,
        artifact_service=service,
        transport=transport,
        receipts_dir=str(receipts_dir),
        idempotency_key=key,
    )


# ---------------------------------------------------------------------------
# 1-2: Docs and Slides placement produce verified, attributable receipts
# ---------------------------------------------------------------------------


def _docs_harness(tmp_path):
    docs = FakeDocsService()
    docs.add_document("doc-1", ["Worksheet", marker_for_role("worked-example"), "Footer"])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    return docs, slides, drive, transport


def test_docs_placement_produces_verified_receipt(tmp_path):
    docs, slides, drive, transport = _docs_harness(tmp_path)
    binding = _binding("worked-example")
    (outcome,) = _execute([binding], artifact_type="docs", artifact_id="doc-1",
                          drive=drive, docs=docs, slides=slides, transport=transport,
                          receipts_dir=tmp_path / "receipts")
    assert outcome.status == "placed"
    record = outcome.record
    assert record is not None and record["state"] == "verified"
    # Matrix 17: the receipt preserves role + asset + content identity.
    assert record["role_id"] == "worked-example"
    assert record["slot_id"] == "0"
    assert record["asset_id"] == "asset-1"
    assert record["drive_file_id"] == "file-1"
    assert record["content_identity"] == _identity()
    assert record["artifact_type"] == "docs" and record["artifact_id"] == "doc-1"
    assert record["marker"] == marker_for_role("worked-example")
    assert record["inserted_element_id"]
    # The marker is gone from the persisted artifact (positive proof).
    assert marker_for_role("worked-example") not in docs.documents_store["doc-1"]["paragraphs"]
    # The durable store holds exactly one record for the build.
    assert len(load_placement_records(tmp_path / "receipts", "k" * 64)) == 1


def test_slides_placement_produces_verified_receipt(tmp_path):
    docs = FakeDocsService()
    slides = FakeSlidesService()
    slides.add_presentation("pres-1", [{"objectId": "slide-1", "elements": [
        {"objectId": "shape-1", "text": marker_for_role("worked-example")},
    ]}])
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    binding = _binding("worked-example")
    (outcome,) = _execute([binding], artifact_type="slides", artifact_id="pres-1",
                          drive=drive, docs=docs, slides=slides, transport=transport,
                          receipts_dir=tmp_path / "receipts")
    assert outcome.status == "placed"
    record = outcome.record
    assert record is not None and record["state"] == "verified"
    assert record["role_id"] == "worked-example"
    assert record["asset_id"] == "asset-1"
    assert record["content_identity"] == _identity()
    assert record["artifact_type"] == "slides" and record["artifact_id"] == "pres-1"
    assert record["container_id"] == "slide-1"
    assert record["inserted_element_id"]
    elements = slides.presentations_store["pres-1"]["slides"][0]["elements"]
    assert any(e["objectId"] == record["inserted_element_id"] for e in elements)
    assert not any(e["text"].strip() == marker_for_role("worked-example") for e in elements)


# ---------------------------------------------------------------------------
# 3-5: stale / missing / inaccessible provider content fails visibly
# ---------------------------------------------------------------------------


def test_stale_content_revision_blocked(tmp_path):
    """Matrix 6: changed bytes after selection -> blocked as stale, never placed."""
    docs, slides, drive, transport = _docs_harness(tmp_path)
    drive = FakeDriveService({"file-1": _drive_metadata("file-1", sha256=STALE_FINGERPRINT)})
    with pytest.raises(PlacementExecutionError, match="content-identity-mismatch"):
        _execute([_binding("worked-example")], artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=tmp_path / "receipts")
    assert transport.calls == []
    assert load_placement_records(tmp_path / "receipts", "k" * 64) == ()
    # The marker is untouched: nothing was placed, nothing was reinterpreted.
    assert marker_for_role("worked-example") in docs.documents_store["doc-1"]["paragraphs"]


def test_missing_asset_blocked_as_missing(tmp_path):
    """Matrix 7: deleted provider file -> blocked as missing, not a visual gap."""
    docs, slides, drive, transport = _docs_harness(tmp_path)
    drive = FakeDriveService({})  # file-1 absent -> not-found
    with pytest.raises(PlacementExecutionError, match="asset-missing"):
        _execute([_binding("worked-example")], artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=tmp_path / "receipts")
    assert transport.calls == []
    assert load_placement_records(tmp_path / "receipts", "k" * 64) == ()


def test_access_failure_blocked_as_access_failure(tmp_path):
    """Matrix 8: permission gap -> blocked as access failure, not absence."""
    docs, slides, drive, transport = _docs_harness(tmp_path)
    drive = FakeDriveService({"file-1": DriveLookupError("file-1", "no-access", "forbidden")})
    with pytest.raises(PlacementExecutionError, match="asset-access-failure"):
        _execute([_binding("worked-example")], artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=tmp_path / "receipts")
    assert transport.calls == []


# ---------------------------------------------------------------------------
# 6: conflicting identity fails closed
# ---------------------------------------------------------------------------


def test_identity_conflict_fails_closed(tmp_path):
    """Matrix 11: duplicate (role, slot) bindings and duplicate receipts fail closed."""
    plan = _real_plan()
    # Duplicate the single assignment to simulate an identity conflict.
    payload = plan.cohesive_visual_plan_result.record.to_dict()
    payload["required_role_assignments"] = (
        payload["required_role_assignments"] + payload["required_role_assignments"]
    )
    from instructional_materials_coach.visual_reuse import GovernedVisualReusePlan
    from instructional_workflow_contracts import ValidationResult

    class _FakeResult:
        def __init__(self, payload):
            self._payload = payload

        @property
        def record(self):
            parent = self

            class _Record:
                def to_dict(self_inner):
                    return parent._payload

            return _Record()

    conflicted = GovernedVisualReusePlan(
        outcome=plan.outcome,
        final_production_blocked=False,
        selected_asset_ids=plan.selected_asset_ids,
        material_requirement_result=plan.material_requirement_result,
        visual_needs_result=plan.visual_needs_result,
        cohesive_visual_plan_result=_FakeResult(payload),
    )
    with pytest.raises(PlacementExecutionError, match="placement-binding-ambiguous"):
        plan_visual_placement_bindings(conflicted)

    # The durable store refuses a second verified receipt for an identical binding.
    docs, slides, drive, transport = _docs_harness(tmp_path)
    binding = _binding("worked-example")
    _execute([binding], artifact_type="docs", artifact_id="doc-1",
             drive=drive, docs=docs, slides=slides, transport=transport,
             receipts_dir=tmp_path / "receipts")
    from instructional_materials_coach.placement_receipts import append_placement_record, build_placement_record
    record = build_placement_record(
        receipt={"asset_id": "asset-1", "drive_file_id": "file-1", "role_id": "worked-example",
                 "artifact_type": "docs", "artifact_id": "doc-1", "artifact_revision_id": "r1",
                 "marker": marker_for_role("worked-example"), "container_id": "body",
                 "inserted_element_id": "x", "state": "verified"},
        content_identity=_identity(), slot_id="0", source_plan_id="p", required=True,
        eligibility_evidence={}, transport_name="t", post_insertion_revision="r2",
    )
    with pytest.raises(ValueError, match="duplicate verified receipt"):
        append_placement_record(tmp_path / "receipts", "k" * 64, record)


# ---------------------------------------------------------------------------
# 7-8: multiplicity -- shared assets and distinct assets
# ---------------------------------------------------------------------------


def test_shared_asset_across_permitted_roles(tmp_path):
    """Matrix 4: one governed asset satisfying two roles -> one receipt per role."""
    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role("worked-example"), marker_for_role("comparison")])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    bindings = [_binding("worked-example"), _binding("comparison")]
    outcomes = _execute(bindings, artifact_type="docs", artifact_id="doc-1",
                       drive=drive, docs=docs, slides=slides, transport=transport,
                       receipts_dir=tmp_path / "receipts")
    assert [o.status for o in outcomes] == ["placed", "placed"]
    # Input order preserved, no overwrite: each receipt maps to its own role.
    assert outcomes[0].record["role_id"] == "worked-example"
    assert outcomes[1].record["role_id"] == "comparison"
    assert outcomes[0].record["asset_id"] == outcomes[1].record["asset_id"] == "asset-1"
    assert outcomes[0].record["inserted_element_id"] != outcomes[1].record["inserted_element_id"]
    assert len(transport.calls) == 2


def test_multiple_distinct_assets_distinct_roles(tmp_path):
    """Matrix 5: distinct assets land in distinct roles with distinct receipts."""
    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role("worked-example"), marker_for_role("comparison")])
    slides = FakeSlidesService()
    drive = FakeDriveService({
        "file-1": _drive_metadata("file-1"),
        "file-2": _drive_metadata("file-2"),
    })
    transport = FakePlacementTransport(docs=docs, slides=slides)
    bindings = [
        _binding("worked-example", asset_id="asset-1", drive_file_id="file-1"),
        _binding("comparison", asset_id="asset-2", drive_file_id="file-2"),
    ]
    outcomes = _execute(bindings, artifact_type="docs", artifact_id="doc-1",
                       drive=drive, docs=docs, slides=slides, transport=transport,
                       receipts_dir=tmp_path / "receipts")
    assert [o.status for o in outcomes] == ["placed", "placed"]
    by_role = {o.record["role_id"]: o.record for o in outcomes}
    assert by_role["worked-example"]["asset_id"] == "asset-1"
    assert by_role["comparison"]["asset_id"] == "asset-2"
    assert by_role["worked-example"]["drive_file_id"] == "file-1"
    assert by_role["comparison"]["drive_file_id"] == "file-2"


# ---------------------------------------------------------------------------
# 9: partial retry does not duplicate already completed placement
# ---------------------------------------------------------------------------


def test_partial_retry_does_not_duplicate(tmp_path):
    """Matrices 12-13: retry recovers the placed binding and continues only the failed one."""
    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role("comparison"), marker_for_role("worked-example")])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides, fail_for_roles={"worked-example"})
    bindings = [_binding("comparison"), _binding("worked-example")]
    with pytest.raises(PlacementExecutionError, match="placement-transport-failed"):
        _execute(bindings, artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=tmp_path / "receipts")
    # comparison placed exactly once; worked-example failed with no receipt.
    assert len(transport.calls) == 2  # comparison ok, worked-example raised
    records = load_placement_records(tmp_path / "receipts", "k" * 64)
    assert [r["role_id"] for r in records] == ["comparison"]

    transport2 = FakePlacementTransport(docs=docs, slides=slides)
    outcomes = _execute(bindings, artifact_type="docs", artifact_id="doc-1",
                       drive=drive, docs=docs, slides=slides, transport=transport2,
                       receipts_dir=tmp_path / "receipts")
    by_role = {o.binding.role_id: o for o in outcomes}
    assert by_role["comparison"].status == "recovered"
    assert by_role["worked-example"].status == "placed"
    # No duplicate insertion for the recovered binding.
    assert [c.role_id for c in transport2.calls] == ["worked-example"]
    assert len(load_placement_records(tmp_path / "receipts", "k" * 64)) == 2


# ---------------------------------------------------------------------------
# Real-producer helpers: bindings through the governed plan (#3248/#3252/#3256)
# ---------------------------------------------------------------------------


def _repo_fixture(name: str) -> dict[str, Any]:
    from pathlib import Path
    root = Path(__file__).parents[3]
    fixture = root / "tests" / "fixtures" / "instructional_workflow_contracts" / name
    return json.loads(fixture.read_text(encoding="utf-8"))


def _real_plan(teacher_decisions: tuple = ()):
    """Run the real governed reuse planner (no hand-built intermediate state)."""
    from instructional_materials_coach.visual_reuse import plan_governed_visual_reuse
    return plan_governed_visual_reuse(
        _repo_fixture("valid_material_requirement_v2.json"),
        visual_candidates=[_repo_fixture("valid_visual_asset_compatibility_v2.json")],
        source_revision="visual-library-snapshot-v2",
        teacher_decisions=tuple(teacher_decisions),
    )


def _real_bindings(teacher_decisions: tuple = ()):
    plan = _real_plan(teacher_decisions)
    assert plan.outcome == "visuals-ready", plan.outcome
    assert not plan.final_production_blocked
    bindings = plan_visual_placement_bindings(plan)
    assert bindings, "expected at least one placement binding from the real plan"
    return plan, bindings


# ---------------------------------------------------------------------------
# 10-11: teacher-selected and automatic selections share the identity contract
# ---------------------------------------------------------------------------


def test_teacher_selected_asset_survives_continuation(tmp_path):
    """Matrices 2+14: a durable teacher decision flows into placement unchanged.

    The placement layer consumes the governed plan (which honors the
    durable decision) -- it never re-runs selection from conversation
    memory. Continuation recovers the same selection and the same receipt.
    """
    from instructional_materials_coach.teacher_decisions import write_teacher_decision
    from instructional_workflow_contracts.teacher_visual_decision import canonical_candidate_set_fingerprint
    requirement = _repo_fixture("valid_material_requirement_v2.json")
    requirement_id = requirement["identity"]["requirement_id"]
    candidate = _repo_fixture("valid_visual_asset_compatibility_v2.json")
    plan_probe = _real_plan()
    role_id = plan_probe.cohesive_visual_plan_result.record.to_dict()["required_role_assignments"][0]["role_id"]
    decisions_dir = tmp_path / "teacher-decisions"
    write_teacher_decision(
        {
            "contract_id": "teacher-visual-decision-v1",
            "decision_id": "decision-1",
            "actor": "teacher",
            "decided_at": "2026-10-03T12:00:00Z",
            "requirement_id": requirement_id,
            "source_revision": "visual-library-snapshot-v2",
            "role": role_id,
            "slot": 0,
            "selected_asset": {
                "asset_id": "asset-1",
                "provider_file_id": "file-1",
                "content_identity": _identity(),
                "revision_identity": "rev-1",
                "provenance": {"source": "teacher-choice-test"},
            },
            "overridden_recommendation": "automatic-pick",
            "candidate_set_fingerprint": canonical_candidate_set_fingerprint([candidate]),
            "scope": "unit",
            "invalidation_rule": "candidate-set-or-content-change",
            "status": "active",
        },
        decisions_dir,
    )
    from instructional_materials_coach.teacher_decisions import load_teacher_decisions
    decisions = load_teacher_decisions(decisions_dir, requirement_id=requirement_id)
    plan, bindings = _real_bindings(tuple(decisions))
    honored = [o for o in plan.teacher_decision_outcomes if o.get("decision_id") == "decision-1"]
    assert honored and honored[0].get("honored") is True, plan.teacher_decision_outcomes
    assert bindings[0].asset_id == "asset-1"
    assert bindings[0].role_id == role_id

    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role(role_id)])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    receipts_dir = tmp_path / "receipts"
    (outcome,) = _execute([bindings[0]], artifact_type="docs", artifact_id="doc-1",
                          drive=drive, docs=docs, slides=slides, transport=transport,
                          receipts_dir=receipts_dir)
    assert outcome.status == "placed"
    assert outcome.record["asset_id"] == "asset-1"

    # Continuation: the same durable decision yields the same binding, and
    # the retry recovers the receipt instead of placing again.
    plan2, bindings2 = _real_bindings(tuple(load_teacher_decisions(decisions_dir, requirement_id=requirement_id)))
    assert bindings2[0].asset_id == "asset-1"
    assert bindings2[0].content_identity == bindings[0].content_identity
    transport2 = FakePlacementTransport(docs=docs, slides=slides)
    (outcome2,) = _execute([bindings2[0]], artifact_type="docs", artifact_id="doc-1",
                           drive=drive, docs=docs, slides=slides, transport=transport2,
                           receipts_dir=receipts_dir)
    assert outcome2.status == "recovered"
    assert transport2.calls == []


def test_automatic_selection_same_identity_contract(tmp_path):
    """Matrix 3: automatic selection carries the full identity contract too."""
    plan, bindings = _real_bindings()
    binding = bindings[0]
    assert binding.asset_id and binding.drive_file_id
    assert binding.content_identity.get("contract_version") == "governed-asset-content-identity-v1"
    assert binding.source_plan_id
    assert binding.eligibility_evidence  # explicit evidence, never inferred
    assert binding.required is True
    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role(binding.role_id)])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    (outcome,) = _execute([binding], artifact_type="docs", artifact_id="doc-1",
                          drive=drive, docs=docs, slides=slides, transport=transport,
                          receipts_dir=tmp_path / "receipts")
    assert outcome.status == "placed"
    assert outcome.record["content_identity"] == binding.content_identity


# ---------------------------------------------------------------------------
# 12: placement failure never authorizes generation
# ---------------------------------------------------------------------------


def test_placement_failure_never_authorizes_generation(tmp_path):
    """Matrix 15: every placement failure keeps its own reason -- never a gap."""
    plan, bindings = _real_bindings()
    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role(bindings[0].role_id)])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides,
                                       fail_for_roles={bindings[0].role_id})
    with pytest.raises(PlacementExecutionError, match="placement-transport-failed") as excinfo:
        _execute([bindings[0]], artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=tmp_path / "receipts")
    message = str(excinfo.value)
    assert "placement-transport-failed" in message
    assert "gap" not in message.lower() or "not a visual gap" in message or "never" in message.lower()
    # No receipt was persisted and the governed plan is untouched: no gap
    # brief was emitted, no generation handoff exists.
    assert load_placement_records(tmp_path / "receipts", "k" * 64) == ()
    assert plan.image_gap_briefs == ()
    assert plan.outcome == "visuals-ready"


# ---------------------------------------------------------------------------
# Runtime unavailable / marker failures
# ---------------------------------------------------------------------------


def test_runtime_unavailable_fails_closed(tmp_path):
    """Matrix 9: no transport -> explicit blocked state, never final."""
    docs, slides, drive, _ = _docs_harness(tmp_path)
    with pytest.raises(PlacementRuntimeUnavailable, match="placement-runtime-unavailable"):
        _execute([_binding("worked-example")], artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=None,
                 receipts_dir=tmp_path / "receipts")


def test_marker_missing_is_placement_failure_not_absence(tmp_path):
    """Matrix 10: a role with no marker is a placement failure, never absence."""
    docs = FakeDocsService()
    docs.add_document("doc-1", ["Worksheet without any visual marker"])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    binding = _binding("worked-example")
    (outcome,) = _execute([binding], artifact_type="docs", artifact_id="doc-1",
                          drive=drive, docs=docs, slides=slides, transport=transport,
                          receipts_dir=tmp_path / "receipts")
    assert outcome.status == "skipped-no-marker"
    assert transport.calls == []
    # The build-level backstop fails closed: required slot not verified-placed.
    with pytest.raises(PlacementExecutionError, match="not verified-placed"):
        require_all_required_visuals_placed(
            bindings=(binding,),
            receipts_dir=str(tmp_path / "receipts"),
            idempotency_key="k" * 64,
            artifact_files={"worksheet": "doc-1"},
        )


def test_marker_ambiguous_fails_closed(tmp_path):
    docs = FakeDocsService()
    docs.add_document("doc-1", [marker_for_role("worked-example"), marker_for_role("worked-example")])
    slides = FakeSlidesService()
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    with pytest.raises(PlacementExecutionError, match="marker-ambiguous"):
        _execute([_binding("worked-example")], artifact_type="docs", artifact_id="doc-1",
                 drive=drive, docs=docs, slides=slides, transport=transport,
                 receipts_dir=tmp_path / "receipts")
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Connected-build regression (matrix 16): the normal imc-build composition
# ---------------------------------------------------------------------------


def _live_build_meta(file_id, mime, role, key):
    return {
        "id": file_id,
        "mimeType": mime,
        "parents": ["folder"],
        "trashed": False,
        "capabilities": {"canCopy": True, "canAddChildren": True},
        "appProperties": {"agent_os_idempotency_key": key, "agent_os_artifact_role": role},
        "webViewLink": f"https://example/{file_id}",
    }


def _run_connected_build(*, bindings, docs, slides, drive, transport, tmp_path,
                         resume_dir=None, copies=([], []), key="k" * 64):
    """Run the real build_live_materials composition with injected fakes."""
    from unittest.mock import patch
    from instructional_materials_coach.artifact_content_qa import TerminalQAExpectations
    from instructional_materials_coach.live_build import LiveBuildInput, build_live_materials
    slides_meta = _live_build_meta("slides-id", "application/vnd.google-apps.presentation", "slides", key)
    doc_meta = _live_build_meta("doc-id", "application/vnd.google-apps.document", "worksheet", key)
    slides_requests = ({"replaceAllText": {}},)
    docs_requests = ({"replaceAllText": {}},)
    build = LiveBuildInput(
        slides_template_id="slides-template", doc_template_id="doc-template",
        target_folder_id="folder", slides_name="Lesson - Slides", doc_name="Lesson - Worksheet",
        idempotency_key=key, slides_requests=slides_requests,
        docs_requests=docs_requests, visual_placements=tuple(bindings),
        # #3258: terminal QA proves the persisted content and placed visuals.
        qa_expectations=TerminalQAExpectations.build_from_requests(
            idempotency_key=key,
            docs_requests=docs_requests,
            slides_requests=slides_requests,
            visual_placements=tuple(bindings),
        ),
    )
    receipts_dir = tmp_path / "receipts"
    with patch("instructional_materials_coach.live_build.verify_template"), \
         patch("instructional_materials_coach.live_build.verify_target_folder"), \
         patch("instructional_materials_coach.live_build.find_idempotent_copies", side_effect=copies), \
         patch("instructional_materials_coach.live_build.duplicate_template",
               side_effect=[slides_meta, doc_meta]), \
         patch("instructional_materials_coach.live_build.apply_slides_requests"), \
         patch("instructional_materials_coach.live_build.apply_docs_requests"), \
         patch("instructional_materials_coach.live_build.verify_final_copy",
               side_effect=[slides_meta, doc_meta]):
        receipt = build_live_materials(
            build,
            drive_service=drive,
            slides_service=slides,
            docs_service=docs,
            resume_dir=str(resume_dir) if resume_dir else None,
            placement_transport=transport,
            placement_receipts_dir=str(receipts_dir),
        )
    return receipt, receipts_dir


def test_connected_build_regression(tmp_path):
    """Matrix 16: MaterialRequirement -> ... -> normal imc-build -> receipt -> success.

    This is the key Wave-3 regression: on pre-repair main the governed CLI
    refused any non-empty visual selection before planning completed, so a
    visuals-required build could never complete. After repair the same
    selection flows through the normal composition into verified placements.
    """
    plan, bindings = _real_bindings()
    role_id = bindings[0].role_id
    docs = FakeDocsService()
    docs.add_document("doc-id", ["Worksheet", marker_for_role(role_id)])
    slides = FakeSlidesService()
    slides.add_presentation("slides-id", [{"objectId": "slide-1", "elements": []}])
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)

    receipt, receipts_dir = _run_connected_build(
        bindings=list(bindings), docs=docs, slides=slides, drive=drive,
        transport=transport, tmp_path=tmp_path,
    )
    assert receipt.succeeded, f"slides={receipt.slides.state} worksheet={receipt.worksheet.state}"
    records = load_placement_records(receipts_dir, "k" * 64)
    assert len(records) == 1
    record = records[0]
    assert record["state"] == "verified"
    assert record["role_id"] == role_id
    assert record["asset_id"] == bindings[0].asset_id
    assert record["content_identity"] == dict(bindings[0].content_identity)
    assert record["artifact_id"] == "doc-id"
    # The governed plan still reports visuals-ready with no gap briefs:
    # placement success never rewrites selection evidence.
    assert plan.outcome == "visuals-ready" and plan.image_gap_briefs == ()


def test_connected_build_fails_closed_without_transport(tmp_path):
    """Matrix 9 at build level: bindings without a transport never report final."""
    _, bindings = _real_bindings()
    docs = FakeDocsService()
    docs.add_document("doc-id", ["Worksheet"])
    slides = FakeSlidesService()
    slides.add_presentation("slides-id", [{"objectId": "slide-1", "elements": []}])
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    receipt, _ = _run_connected_build(
        bindings=list(bindings), docs=docs, slides=slides, drive=drive,
        transport=None, tmp_path=tmp_path,
    )
    assert not receipt.succeeded
    assert "placement-runtime-unavailable" in receipt.slides.error


def test_build_retry_recovers_receipts_without_duplicate_placement(tmp_path):
    """Matrices 12-13 at build level: resume recovery never re-inserts."""
    _, bindings = _real_bindings()
    role_id = bindings[0].role_id
    docs = FakeDocsService()
    docs.add_document("doc-id", ["Worksheet", marker_for_role(role_id)])
    slides = FakeSlidesService()
    slides.add_presentation("slides-id", [{"objectId": "slide-1", "elements": []}])
    drive = FakeDriveService({"file-1": _drive_metadata("file-1")})
    transport = FakePlacementTransport(docs=docs, slides=slides)
    resume_dir = tmp_path / "resume"

    receipt1, receipts_dir = _run_connected_build(
        bindings=list(bindings), docs=docs, slides=slides, drive=drive,
        transport=transport, tmp_path=tmp_path, resume_dir=resume_dir,
    )
    assert receipt1.succeeded
    assert len(transport.calls) == 1

    # Second run: copies are recovered, resume says updated, placement is
    # recovered from the durable store -- the transport is never called.
    slides_meta = _live_build_meta("slides-id", "application/vnd.google-apps.presentation", "slides", "k" * 64)
    doc_meta = _live_build_meta("doc-id", "application/vnd.google-apps.document", "worksheet", "k" * 64)
    transport2 = FakePlacementTransport(docs=docs, slides=slides)
    receipt2, _ = _run_connected_build(
        bindings=list(bindings), docs=docs, slides=slides, drive=drive,
        transport=transport2, tmp_path=tmp_path, resume_dir=resume_dir,
        copies=([[slides_meta], [doc_meta]]),
    )
    assert receipt2.succeeded
    assert transport2.calls == []
    assert len(load_placement_records(receipts_dir, "k" * 64)) == 1
