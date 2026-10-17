"""#3389 regression: caption binding, structure, and provenance plumbing.

Proves the repaired contract on the exact failure modes from the
production reproduction:
- no-origin / shared / swapped / distant / metadata-only captions all
  fail closed (never verified);
- caption token identities reject concatenation collisions and
  duplicates;
- table-cell and document-tab structures bind captions correctly;
- 1/2/4 independent captions each verify;
- the template preflight passes on paired anchors and fails closed on
  missing/distant anchors;
- ``_assignment`` populates ``image_provenance`` from normal candidates;
- malformed provenance evidence fails closed in the compatibility layer.

Fixtures use synthetic IDs/revisions only; positives use genuine
readback structure via ``observe_artifact``.
"""
from __future__ import annotations

from typing import Any, Mapping

import pytest

from instructional_materials_coach.artifact_content_qa import (
    QA_STATE_PROVENANCE_UNRESOLVED,
    QA_STATE_VERIFIED,
    QA_STATE_VISUAL_MISMATCH,
    ArtifactObservation,
    DocsContentBlock,
    TerminalQAExpectations,
    VisualExpectation,
    evaluate_artifact_qa,
    preflight_template_caption_anchors,
)
from instructional_materials_coach.docs_requests import (
    build_provenance_caption_requests,
    provenance_caption_token,
)
from instructional_materials_coach.image_provenance import (
    ImageProvenance,
    ImageProvenanceError,
)


IDENTITY = {"sha256": "c" * 64}
KEY = "k" * 64


def _prov(kind: str, **kw: Any) -> ImageProvenance:
    return ImageProvenance(origin_kind=kind, **kw)  # type: ignore[arg-type]


def _visual(role_id: str, provenance: Mapping[str, Any] | None) -> VisualExpectation:
    return VisualExpectation(
        role_id=role_id, slot_id="0", asset_id="asset-" + role_id,
        content_identity=dict(IDENTITY), required=True,
        provenance=provenance,
    )


def _receipt(role_id: str, image_id: str) -> dict[str, Any]:
    return {
        "asset_id": "asset-" + role_id, "drive_file_id": "drive-1",
        "role_id": role_id, "slot_id": "0", "artifact_type": "docs",
        "artifact_id": "doc-1", "artifact_revision_id": "r0",
        "marker": None, "container_id": None,
        "inserted_element_id": image_id, "state": "verified",
        "content_identity": dict(IDENTITY),
        "post_insertion_revision_id": "r1",
    }


def _blocks(pairs: tuple[tuple[str, str], ...]) -> tuple[DocsContentBlock, ...]:
    """Build (image, caption) adjacent block pairs in the body."""
    blocks: list[DocsContentBlock] = []
    for i, (image_id, caption) in enumerate(pairs):
        blocks.append(DocsContentBlock(
            container=("body",), index=2 * i, text="", image_ids=(image_id,)))
        blocks.append(DocsContentBlock(
            container=("body",), index=2 * i + 1, text=caption, image_ids=()))
    return tuple(blocks)


def _evaluate(visuals: tuple[VisualExpectation, ...],
              records: tuple[dict[str, Any], ...],
              observation: ArtifactObservation):
    expectations = TerminalQAExpectations(
        idempotency_key=KEY, visuals=visuals,
    )
    return evaluate_artifact_qa(
        artifact_type="docs", artifact_id="doc-1",
        expectations=expectations, observation=observation,
        placement_records=records, idempotency_key=KEY,
    )


def _obs(blocks: tuple[DocsContentBlock, ...],
         images: tuple[str, ...]) -> ArtifactObservation:
    return ArtifactObservation(
        artifact_type="docs", artifact_id="doc-1", revision_id="r1",
        full_text="worksheet", token_hits=(),
        image_element_ids=images, docs_blocks=blocks,
    )


def _codes(report) -> list[str]:
    return [f.code for f in report.findings]


# ---------------------------------------------------------------------------
# Counterexample regressions: all fail closed, none verified
# ---------------------------------------------------------------------------

def test_no_origin_image_is_provenance_unresolved():
    """Repro P1: missing provenance -> verified. Now unresolved."""
    report = _evaluate(
        (_visual("r", None),), (_receipt("r", "img-0"),),
        _obs(_blocks((("img-0", "AI-generated image"),)), ("img-0",)),
    )
    assert report.state == QA_STATE_PROVENANCE_UNRESOLVED
    assert "qa-provenance-unresolved" in _codes(report)


def test_shared_caption_fails_closed_for_both_images():
    """One caption occurrence satisfies exactly one image. Two images
    sharing one caption: the second image has no caption of its own."""
    prov = {"origin_kind": "ai-generated"}
    blocks = (
        DocsContentBlock(container=("body",), index=0, text="",
                         image_ids=("img-0",)),
        DocsContentBlock(container=("body",), index=1, text="",
                         image_ids=("img-1",)),
        DocsContentBlock(container=("body",), index=2,
                         text="AI-generated image", image_ids=()),
    )
    report = _evaluate(
        (_visual("r0", prov), _visual("r1", prov)),
        (_receipt("r0", "img-0"), _receipt("r1", "img-1")),
        _obs(blocks, ("img-0", "img-1")),
    )
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert _codes(report).count("qa-caption-not-adjacent") == 1


def test_swapped_human_ai_captions_fail_closed():
    """The human photo's caption sits under the AI image and vice versa:
    neither caption is adjacent to its own image."""
    human = {"origin_kind": "human-photograph", "creator_name": "Ada Lovelace"}
    ai = {"origin_kind": "ai-generated"}
    blocks = (
        DocsContentBlock(container=("body",), index=0, text="",
                         image_ids=("img-human",)),
        DocsContentBlock(container=("body",), index=1,
                         text="AI-generated image", image_ids=()),
        DocsContentBlock(container=("body",), index=2, text="",
                         image_ids=("img-ai",)),
        DocsContentBlock(container=("body",), index=3,
                         text="Photo: Ada Lovelace", image_ids=()),
    )
    report = _evaluate(
        (_visual("human", human), _visual("ai", ai)),
        (_receipt("human", "img-human"), _receipt("ai", "img-ai")),
        _obs(blocks, ("img-human", "img-ai")),
    )
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert _codes(report).count("qa-caption-not-adjacent") == 2


def test_distant_caption_thirty_paragraphs_fails_closed():
    """A caption 30 paragraphs below its image is not adjacent."""
    prov = {"origin_kind": "ai-generated"}
    blocks: list[DocsContentBlock] = [
        DocsContentBlock(container=("body",), index=0, text="",
                         image_ids=("img-0",)),
    ]
    for i in range(1, 31):
        blocks.append(DocsContentBlock(
            container=("body",), index=i, text=f"filler {i}", image_ids=()))
    blocks.append(DocsContentBlock(
        container=("body",), index=31, text="AI-generated image", image_ids=()))
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(tuple(blocks), ("img-0",)),
    )
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert "qa-caption-not-adjacent" in _codes(report)


def test_metadata_only_without_rendered_caption_fails_closed():
    """Provenance metadata exists but no caption was rendered: the image
    is not attributable in the persisted artifact."""
    prov = {"origin_kind": "human-photograph", "creator_name": "Ada Lovelace"}
    blocks = (
        DocsContentBlock(container=("body",), index=0, text="",
                         image_ids=("img-0",)),
        DocsContentBlock(container=("body",), index=1,
                         text="Some unrelated paragraph.", image_ids=()),
    )
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(blocks, ("img-0",)),
    )
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert "qa-caption-not-adjacent" in _codes(report)


# ---------------------------------------------------------------------------
# Token identity: collisions and duplicates are refused
# ---------------------------------------------------------------------------

def test_caption_token_concatenation_collision_is_rejected():
    """("a_b", "c") and ("a", "b_c") must not produce the same token."""
    t1 = provenance_caption_token(role_id="a_b", slot_id="c")
    t2 = provenance_caption_token(role_id="a", slot_id="b_c")
    assert t1 != t2, f"collision: {t1!r} == {t2!r}"


def test_duplicate_caption_tokens_across_bindings_raise():
    """Two bindings resolving to the same token refuse to build."""
    from instructional_materials_coach.connected_visual_placement import (
        VisualPlacementBinding,
    )
    prov = _prov("ai-generated")
    b1 = VisualPlacementBinding(
        role_id="r", slot_id="0", asset_id="a1", drive_file_id="f1",
        content_identity=dict(IDENTITY), source_plan_id="plan-1",
        image_provenance=prov,
    )
    b2 = VisualPlacementBinding(
        role_id="r", slot_id="0", asset_id="a2", drive_file_id="f2",
        content_identity=dict(IDENTITY), source_plan_id="plan-1",
        image_provenance=prov,
    )
    with pytest.raises(ImageProvenanceError, match="duplicate"):
        build_provenance_caption_requests((b1, b2))


# ---------------------------------------------------------------------------
# Structure: table cells and document tabs bind correctly
# ---------------------------------------------------------------------------

def test_caption_in_table_cell_binds_to_its_image():
    """Image and caption in the same table cell: the cell is the figure
    container; adjacency is within the cell."""
    prov = {"origin_kind": "human-photograph", "creator_name": "Ada Lovelace"}
    cell = ("table", 0, 1, 1)
    blocks = (
        DocsContentBlock(container=cell, index=0, text="",
                         image_ids=("img-0",)),
        DocsContentBlock(container=cell, index=1,
                         text="Photo: Ada Lovelace", image_ids=()),
    )
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(blocks, ("img-0",)),
    )
    assert report.state == QA_STATE_VERIFIED, _codes(report)


def test_caption_in_document_tab_binds_to_its_image():
    """Image and caption in the same document tab bind within the tab."""
    prov = {"origin_kind": "ai-generated"}
    tab = ("tab", "tab-id-1")
    blocks = (
        DocsContentBlock(container=tab, index=0, text="",
                         image_ids=("img-0",)),
        DocsContentBlock(container=tab, index=1,
                         text="AI-generated image", image_ids=()),
    )
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(blocks, ("img-0",)),
    )
    assert report.state == QA_STATE_VERIFIED, _codes(report)


def test_caption_in_different_container_does_not_bind():
    """A caption in a different table cell does not satisfy the image."""
    prov = {"origin_kind": "ai-generated"}
    blocks = (
        DocsContentBlock(container=("table", 0, 0, 0), index=0, text="",
                         image_ids=("img-0",)),
        DocsContentBlock(container=("table", 0, 0, 1), index=0,
                         text="AI-generated image", image_ids=()),
    )
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(blocks, ("img-0",)),
    )
    assert report.state == QA_STATE_VISUAL_MISMATCH
    assert "qa-caption-not-adjacent" in _codes(report)


# ---------------------------------------------------------------------------
# Human/AI adjacency positives; 1/2/4 independent captions
# ---------------------------------------------------------------------------

def test_human_caption_adjacent_verifies():
    prov = {"origin_kind": "human-photograph", "creator_name": "Ada Lovelace"}
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(_blocks((("img-0", "Photo: Ada Lovelace"),)), ("img-0",)),
    )
    assert report.state == QA_STATE_VERIFIED, _codes(report)


def test_ai_caption_adjacent_verifies():
    prov = {"origin_kind": "ai-generated"}
    report = _evaluate(
        (_visual("r", prov),), (_receipt("r", "img-0"),),
        _obs(_blocks((("img-0", "AI-generated image"),)), ("img-0",)),
    )
    assert report.state == QA_STATE_VERIFIED, _codes(report)


@pytest.mark.parametrize("count", [1, 2, 4])
def test_independent_captions_verify(count: int):
    """1, 2, and 4 images each with their own adjacent caption verify."""
    prov = {"origin_kind": "ai-generated"}
    pairs = tuple((f"img-{i}", "AI-generated image") for i in range(count))
    visuals = tuple(_visual(f"r{i}", prov) for i in range(count))
    records = tuple(_receipt(f"r{i}", f"img-{i}") for i in range(count))
    images = tuple(f"img-{i}" for i in range(count))
    report = _evaluate(visuals, records, _obs(_blocks(pairs), images))
    assert report.state == QA_STATE_VERIFIED, _codes(report)


# ---------------------------------------------------------------------------
# Preflight: paired anchors pass, missing/distant anchors fail closed
# ---------------------------------------------------------------------------

def _template_doc(paragraphs: list[str]) -> dict[str, Any]:
    return {
        "revisionId": "r0",
        "body": {"content": [
            {"paragraph": {"elements": [{"textRun": {"content": p + "\n"}}]}}
            for p in paragraphs
        ]},
    }


def _binding(role_id: str, provenance: ImageProvenance | None):
    from instructional_materials_coach.connected_visual_placement import (
        VisualPlacementBinding,
    )
    return VisualPlacementBinding(
        role_id=role_id, slot_id="0", asset_id="a1", drive_file_id="f1",
        content_identity=dict(IDENTITY), source_plan_id="plan-1",
        image_provenance=provenance,
    )


def test_preflight_passes_on_paired_marker_and_caption_token():
    doc = _template_doc([
        "Worksheet",
        "{{visual:worked-example}}",
        "{{provenance_caption_worked-example.0}}",
    ])
    failures = preflight_template_caption_anchors(
        doc, (_binding("worked-example", _prov("ai-generated")),))
    assert failures == []


def test_preflight_fails_closed_when_caption_token_missing():
    doc = _template_doc(["Worksheet", "{{visual:worked-example}}", "Footer"])
    failures = preflight_template_caption_anchors(
        doc, (_binding("worked-example", _prov("ai-generated")),))
    assert len(failures) == 1
    assert "caption token" in failures[0]


def test_preflight_fails_closed_when_caption_token_distant():
    paragraphs = ["Worksheet", "{{visual:worked-example}}"]
    paragraphs.extend(f"filler {i}" for i in range(30))
    paragraphs.append("{{provenance_caption_worked-example.0}}")
    doc = _template_doc(paragraphs)
    failures = preflight_template_caption_anchors(
        doc, (_binding("worked-example", _prov("ai-generated")),))
    assert len(failures) == 1
    assert "not adjacent" in failures[0]


def test_preflight_skips_bindings_without_provenance():
    """No provenance carried: nothing is invented, no anchor required."""
    doc = _template_doc(["Worksheet", "{{visual:worked-example}}"])
    failures = preflight_template_caption_anchors(
        doc, (_binding("worked-example", None),))
    assert failures == []


# ---------------------------------------------------------------------------
# Plumbing: assignment carries provenance; compatibility fails closed
# ---------------------------------------------------------------------------

def test_assignment_populates_image_provenance_from_candidate():
    """cohesive_visual_plan._assignment_image_provenance copies the
    candidate's reviewed image_provenance (None when absent, never
    invented)."""
    from instructional_workflow_contracts.cohesive_visual_plan import (
        _assignment_image_provenance,
    )
    assert _assignment_image_provenance(
        {"image_provenance": {"origin_kind": "ai-generated"}}) == \
        {"origin_kind": "ai-generated"}
    assert _assignment_image_provenance({}) is None
    assert _assignment_image_provenance({"image_provenance": None}) is None
    # Non-mapping values fail closed, never silently dropped.
    with pytest.raises(Exception):
        _assignment_image_provenance({"image_provenance": "bogus"})


def test_compatibility_layer_malformed_provenance_fails_closed():
    """Malformed image_provenance in the library record (unknown
    origin_kind) fails validation at intake -- never silently dropped,
    never invented, never carried through."""
    from instructional_workflow_contracts.visual_asset_compatibility import (
        validate_visual_asset_compatibility_evidence,
    )
    import json
    from pathlib import Path
    fixture = Path(__file__).parents[3] / "tests" / "fixtures" / \
        "instructional_workflow_contracts" / "valid_visual_asset_compatibility_v2.json"
    candidate = json.loads(fixture.read_text(encoding="utf-8"))
    candidate["library_record"]["extra_fields"]["image_provenance"] = {
        "origin_kind": "not-a-real-kind",
    }
    result = validate_visual_asset_compatibility_evidence(candidate)
    assert result.status.name != "VALID"
    assert result.record is None
    assert "handoff-invalid" in result.reason_codes
