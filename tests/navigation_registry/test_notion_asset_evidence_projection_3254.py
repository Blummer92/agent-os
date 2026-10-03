"""Governed Notion -> eligibility evidence projection tests (#3254).

Every test exercises the real projection
(``navigation_registry.connectors.notion_asset_evidence_projection``) and,
where the acceptance criteria require it, the real producer chain
(orchestrator -> assembler -> resolver). No test invents governed values.
"""

import json
from pathlib import Path

import pytest

from instructional_workflow_contracts.material_type_vocabulary import map_material_type
from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CANONICAL_UNIT,
    VISUAL_ASSETS,
    CurriculumReadRequest,
    orchestrate_curriculum_evidence,
)
from navigation_registry.connectors.notion_asset_evidence_projection import (
    V2_EXPLICIT_GAPS,
    V2_FIELD_SOURCES,
    project_approval,
    project_ingestion_admission,
    project_notion_asset_page,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "notion_asset_projection_3254"
UNIT_PAGE = "3907ac78-3131-8111-9999-000000000001"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _unit():
    return {"stable_id": "photography-foundations", "status": "active", "provider_page_id": UNIT_PAGE}


def _identity(logical_source):
    return {
        "logical_source": logical_source,
        "human_review_required": False,
        "data_source_id": "notion-data-source-fixture",
    }


def _reader_for(pages_by_step):
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        assert step.logical_source == VISUAL_ASSETS
        key = "relation_first" if step.relation_first else "coursewide"
        return {"results": pages_by_step.get(key, [])}
    return reader


# ---------------------------------------------------------------------------
# Acceptance: projection over the recorded live-snapshot fixture.
# ---------------------------------------------------------------------------

def test_live_snapshot_val_page_yields_explicit_incomplete_evidence():
    """The VAL snapshot has no Asset ID and no Drive File ID: the projection
    must name both gaps explicitly. Never a page-UUID substitution, never
    approval, never absence."""
    page = _fixture("live_snapshot_val_page.json")
    result = project_notion_asset_page(page, relation_first=True, reuse_scope="unit-specific")
    assert result.kind == "incomplete-evidence"
    assert result.evidence is None
    assert "identity: no governed Asset ID on the Notion record" in result.gaps
    assert "drive binding: no Drive File ID on the Notion record" in result.gaps
    # The page UUID is never substituted as the asset identity.
    assert not any(UNIT_PAGE in gap or "3907ac78" in gap for gap in result.gaps)


def test_live_snapshot_icon_page_yields_governed_evidence():
    """The approved coursewide icon projects to governed evidence with the
    governed Asset ID (not the page UUID) and explicit approval."""
    page = _fixture("live_snapshot_icon_page.json")
    result = project_notion_asset_page(page, relation_first=False, reuse_scope="coursewide")
    assert result.kind == "evidence"
    evidence = result.evidence
    assert evidence is not None
    assert evidence["asset_id"] == "VA-20261002-0001"
    assert evidence["asset_id"] != page["id"]
    assert evidence["approved_for_requested_use"] is True
    assert evidence["reuse_scope"] == "coursewide"
    assert evidence["reuse_status"] == "reusable"
    assert evidence["library_reference"] == {
        "page_id": page["id"],
        "drive_file_id": "drive-file-checkmark-001",
    }


def test_v2_field_table_names_every_source_and_failure():
    """The mapping table covers the v2 contract; explicit gaps are named."""
    assert "compatibility_evidence.asset_reference.asset_id" in V2_FIELD_SOURCES
    assert "compatibility_evidence.manifest_reference" in V2_FIELD_SOURCES
    # The seven unmappable cohesion enums share one grouped table entry.
    grouped = "compatibility_evidence.cohesion_profile.medium|representation_class|palette_family|line_treatment|rendering_style|perspective|background_treatment"
    assert grouped in V2_FIELD_SOURCES
    assert "GAP" in V2_FIELD_SOURCES[grouped]["failure"]
    for gap in V2_EXPLICIT_GAPS:
        # Every explicit gap is either a table key or covered by the grouped entry.
        assert gap in V2_FIELD_SOURCES or "cohesion_profile" in gap


# ---------------------------------------------------------------------------
# Acceptance: the 8 coursewide icons reach candidate filtering via the real
# producer chain (orchestrator coursewide step -> assembler admission).
# ---------------------------------------------------------------------------

def test_eight_coursewide_icons_reach_candidate_filtering():
    """#3253 matrix acceptance: the 8 approved coursewide icons survive real
    evidence assembly via the coursewide read step and are admitted as
    candidates. No matching_asset_exists: false for coursewide assets."""
    icons = _fixture("coursewide_icons_8.json")
    packet = orchestrate_curriculum_evidence(
        request=CurriculumReadRequest("images", "images"),
        canonical_unit=_unit(),
        resolve_identity=_identity,
        execute_read=_reader_for({"coursewide": icons}),
    )
    asset_ids = [item["asset_id"] for item in packet["asset_evidence"]]
    assert len(asset_ids) == 8
    assert asset_ids == sorted(asset_ids)
    for item in packet["asset_evidence"]:
        assert item["reuse_scope"] == "coursewide"
        assert item["approved_for_requested_use"] is True
        assert "library_reference" in item
    # None are scope-excluded; none are incomplete.
    assert packet.get("scope_excluded_asset_ids", []) == []
    assert "incomplete_asset_evidence" not in packet


def test_raw_page_join_without_drive_binding_never_admits():
    """Join test: a page without a Drive File ID produces no library_reference
    and, without a governed Asset ID, is explicit incomplete-evidence rather
    than a silent non-join or a false gap."""
    page = _fixture("live_snapshot_val_page.json")
    result = project_notion_asset_page(page, relation_first=False, reuse_scope="coursewide")
    assert result.kind == "incomplete-evidence"
    # Even if identity existed, the missing drive binding is named.
    assert any("drive binding" in gap for gap in result.gaps)


# ---------------------------------------------------------------------------
# Acceptance: ingest -> next-plan-selects.
# ---------------------------------------------------------------------------

def test_ingest_admission_projects_to_eligible_evidence():
    """An ingested, approved asset (governed Asset ID minted at admission)
    projects to evidence the orchestrator admits on the next run."""
    admission = project_ingestion_admission({
        "page_id": "3907ac78-3131-8111-9999-dddddddddddd",
        "asset_id": "VA-20261002-0100",
        "drive_file_id": "drive-file-ingested-100",
        "reuse_status": "approved",
        "source_approved": True,
        "reusable_across_units": True,
        "reuse_scope": "coursewide",
        "concept": "rule-of-thirds example",
    })
    assert admission.kind == "evidence"
    evidence = admission.evidence
    assert evidence is not None
    assert evidence["asset_id"] == "VA-20261002-0100"
    assert evidence["approved_for_requested_use"] is True
    assert evidence["reuse_scope"] == "coursewide"
    assert evidence["concept"] == "rule-of-thirds example"
    assert evidence["library_reference"]["drive_file_id"] == "drive-file-ingested-100"


def test_ingest_admission_without_minted_asset_id_is_incomplete():
    """The minting authority is an open decision: without a governed Asset ID
    the admission projection is explicit incomplete-evidence, never invented."""
    admission = project_ingestion_admission({
        "page_id": "3907ac78-3131-8111-9999-dddddddddddd",
        "drive_file_id": "drive-file-ingested-100",
    })
    assert admission.kind == "incomplete-evidence"
    assert any("minting authority" in gap for gap in admission.gaps)


def test_ingested_asset_selects_on_next_plan_run():
    """End-to-end: admission evidence fed through the orchestrator's
    normalization is admitted by the #3253 assembler for the same role."""
    from instructional_workflow_contracts.current_curriculum_evidence import (
        assemble_current_curriculum_evidence,
    )
    admission = project_ingestion_admission({
        "page_id": "3907ac78-3131-8111-9999-dddddddddddd",
        "asset_id": "VA-20261002-0100",
        "drive_file_id": "drive-file-ingested-100",
        "reuse_status": "approved",
        "source_approved": True,
        "reusable_across_units": True,
        "reuse_scope": "coursewide",
    })
    assert admission.kind == "evidence" and admission.evidence is not None
    packet = assemble_current_curriculum_evidence(
        request={"action": "images", "artifact_type": "images", "relative_time": "none", "requires_reusable_assets": True},
        canonical_unit={"stable_id": "photography-foundations", "status": "active"},
        owner_evidence=[],
        asset_evidence=[admission.evidence],
    )
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["VA-20261002-0100"]


# ---------------------------------------------------------------------------
# Approval three-state: never invented, never caller-asserted.
# ---------------------------------------------------------------------------

def test_approval_unknown_without_governed_fields():
    """No governed approval fields -> (None, None): ambiguous, not denied,
    not approved. Caller-asserted approval cannot produce True."""
    requested, student = project_approval({"properties": {}})
    assert requested is None
    assert student is None


def test_approval_explicit_denial_is_false():
    requested, student = project_approval({
        "Reuse status": {"type": "status", "status": {"name": "denied"}},
    })
    assert requested is False
    assert student is False


def test_caller_asserted_approval_alone_is_rejected():
    """A caller-supplied approved_use flag is not a governed field: the
    projection ignores it (unknown), it can never yield True."""
    requested, _ = project_approval({
        "caller_asserted_approved": True,
        "Approved use": {"type": "multi_select", "multi_select": [{"name": "worksheet"}]},
    })
    assert requested is None


# ---------------------------------------------------------------------------
# Material-type vocabulary: single mapping.
# ---------------------------------------------------------------------------

def test_material_type_vocabulary_single_mapping():
    assert map_material_type("teacher-reference", "imc") == "teacher-guide"
    assert map_material_type("teacher-guide", "material_requirement") == "teacher-guide"
    assert map_material_type("slide", "val") == "slide-deck"
    assert map_material_type("worksheet", "val") == "worksheet"
    assert map_material_type("poster", "val") == "poster"
    assert map_material_type("teacher-facing", "val") == "teacher-guide"
    assert map_material_type("student-facing", "val") == "student-facing"
    # Unknown values -> None (manual review), never invented.
    assert map_material_type("hologram", "val") is None
    assert map_material_type("", "val") is None
    assert map_material_type(None, "val") is None
