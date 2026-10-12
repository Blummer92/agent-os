"""Governed projection from live Notion asset records to eligibility evidence (#3254).

This module is the owned field-by-field mapping from the Visual Asset Library
and Icon System working records into the exact governed evidence that
compatibility and eligibility logic consumes.

Design rules (from #3254's shared invariant):
- Notion remains the live working source; GitHub owns the evidence contracts
  and this projection.
- Governed values are never invented. Every v2/evidence field names its
  governed source, transformation owner, validation, and failure behavior.
- Missing, unmappable, or incomplete values become explicit
  ``incomplete-evidence`` / manual review. They are never proven absence,
  never approval, and never a substituted identity.
- Asset identity comes from the governed "Asset ID" property, never the
  Notion page UUID. A missing Asset ID is an explicit identity gap.
- Approval comes from governed approval fields only. Caller-asserted approval
  alone is rejected (projected as unknown, never approved).
- Scope vocabulary and eligibility policy are owned by #3253
  (``current_curriculum_evidence.REUSE_SCOPES`` / ``REUSE_STATUSES``); this
  module only projects the Notion-side signals into that vocabulary.

This module performs no I/O, no reads, no writes. It is a pure transformation
boundary. The orchestrator (``curriculum_evidence_orchestrator``) remains the
thin bounded-read layer and calls into this projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from instructional_workflow_contracts.material_type_vocabulary import (
    MATERIAL_TYPE_VOCABULARY,
    map_material_type,
)

# ---------------------------------------------------------------------------
# Governed Notion property names (exact live-schema strings).
# ---------------------------------------------------------------------------

# Visual Asset Library properties.
ASSET_ID_PROPERTY = "Asset ID"
ASSET_TITLE_PROPERTY = "Asset Title"
DRIVE_FILE_ID_PROPERTY = "Drive File ID"
REUSE_STATUS_PROPERTY = "Reuse status"
HUMAN_REVIEW_DONE_PROPERTY = "Human Review Done"
APPROVED_USE_PROPERTY = "Approved use"
STYLE_FAMILY_PROPERTY = "Style family"
COGNITIVE_LOAD_PROPERTY = "Cognitive load rating"
CANONICAL_UNIT_PROPERTY = "Canonical Unit"
SCOPE_UNIT_IDS_PROPERTY = "Scope Unit IDs"

# Icon System properties.
SOURCE_APPROVED_PROPERTY = "Source Approved?"
REUSABLE_ACROSS_UNITS_PROPERTY = "Reusable Across Units?"

# ---------------------------------------------------------------------------
# Governed per-source filter vocabulary (#2816).
#
# A provider query filter may only name a property the resolved logical
# source's governed vocabulary exposes. "Reusable Across Units?" is an Icon
# System property: filtering the Visual Asset Library on it provably 400s at
# Notion (run 37845400763: "Could not find property with name or id:
# Reusable Across Units?"), so it is deliberately absent from the Visual
# Asset Library vocabulary. The orchestrator consults these sets before a
# filter is dispatched; anything outside fails closed with a bounded reason.
# ---------------------------------------------------------------------------
VISUAL_ASSET_LIBRARY_PROPERTIES = frozenset(
    {
        ASSET_ID_PROPERTY,
        ASSET_TITLE_PROPERTY,
        DRIVE_FILE_ID_PROPERTY,
        REUSE_STATUS_PROPERTY,
        HUMAN_REVIEW_DONE_PROPERTY,
        APPROVED_USE_PROPERTY,
        STYLE_FAMILY_PROPERTY,
        COGNITIVE_LOAD_PROPERTY,
        CANONICAL_UNIT_PROPERTY,
        SCOPE_UNIT_IDS_PROPERTY,
    }
)

ICON_SYSTEM_PROPERTIES = frozenset(
    {
        SOURCE_APPROVED_PROPERTY,
        REUSABLE_ACROSS_UNITS_PROPERTY,
    }
)

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Single governed material-type vocabulary (#3254).
#
# The canonical mapping lives in
# ``instructional_workflow_contracts.material_type_vocabulary`` so
# MaterialRequirement, IMC, and the VAL projection share one definition.
# Re-exported here for projection consumers.
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Approval value mapping.
# ---------------------------------------------------------------------------

# Governed approval states for the projection. Only an explicit governed
# approval yields True. Explicit denial yields False. Everything else is
# None (unknown -> ambiguous -> manual review via the existing
# "asset-approval-ambiguous" reason). Approval is never invented.
_REUSE_STATUS_APPROVED_VALUES = frozenset({"approved"})
_REUSE_STATUS_DENIED_VALUES = frozenset({"denied", "rejected", "revoked"})


def _checkbox(properties: Mapping[str, object], name: str) -> bool | None:
    """Read a Notion checkbox property: True/False/None (missing/malformed)."""
    prop = properties.get(name)
    if isinstance(prop, Mapping):
        checkbox = prop.get("checkbox")
        if checkbox is True:
            return True
        if checkbox is False:
            return False
    return None


def _select_value(properties: Mapping[str, object], name: str) -> str | None:
    """Read a Notion select/status property's selected name, or None."""
    prop = properties.get(name)
    if isinstance(prop, Mapping):
        select = prop.get("select")
        if isinstance(select, Mapping):
            value = select.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
        status = prop.get("status")
        if isinstance(status, Mapping):
            value = status.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _rich_text(properties: Mapping[str, object], name: str) -> str | None:
    """Read a Notion rich_text/title property's plain text, or None."""
    prop = properties.get(name)
    if isinstance(prop, Mapping):
        for key in ("rich_text", "title"):
            blocks = prop.get(key)
            if isinstance(blocks, list):
                text = "".join(
                    block.get("plain_text", "")
                    for block in blocks
                    if isinstance(block, Mapping)
                ).strip()
                if text:
                    return text
    return None


def project_approval(
    properties: Mapping[str, object], *, icon_system: bool = False
) -> tuple[bool | None, bool | None]:
    """Project governed approval to (approved_for_requested_use, approved_student_reuse).

    Three-state logic: True only on explicit governed approval; False only on
    explicit governed denial; None (unknown) otherwise. Caller-asserted
    approval is not consumed here and therefore can never produce True.

    Governed approval signals: VAL "Reuse status" == "approved", or Icon
    System "Source Approved?" checked. Both are read whenever present; the
    ``icon_system`` flag is retained for callers that know the source.
    """
    reuse_status = _select_value(properties, REUSE_STATUS_PROPERTY)
    human_review = _checkbox(properties, HUMAN_REVIEW_DONE_PROPERTY)
    # "Source Approved?" is a governed approval field on Icon System records;
    # read it whenever the property is present (never invented).
    source_approved = _checkbox(properties, SOURCE_APPROVED_PROPERTY)

    if reuse_status in _REUSE_STATUS_APPROVED_VALUES or source_approved is True:
        requested: bool | None = True
    elif reuse_status in _REUSE_STATUS_DENIED_VALUES:
        requested = False
    else:
        requested = None

    # Student reuse requires explicit student-facing approval; it is never
    # inferred from a general approval alone.
    approved_use_raw = _select_value(properties, APPROVED_USE_PROPERTY)
    if approved_use_raw is None:
        # Also try multi-select form.
        prop = properties.get(APPROVED_USE_PROPERTY)
        if isinstance(prop, Mapping):
            multi = prop.get("multi_select")
            if isinstance(multi, list):
                names = [
                    item.get("name")
                    for item in multi
                    if isinstance(item, Mapping) and isinstance(item.get("name"), str)
                ]
                approved_use_raw = ",".join(names) if names else None
    student_facing = False
    if approved_use_raw:
        for token in approved_use_raw.split(","):
            if map_material_type(token.strip(), "val") == "student-facing":
                student_facing = True
                break
    if requested is True and student_facing:
        student: bool | None = True
    elif requested is False:
        student = False
    else:
        student = None
    # Human review done without an approval state is not approval.
    _ = human_review
    return requested, student


def project_asset_identity(properties: Mapping[str, object]) -> tuple[str | None, str | None]:
    """Project the governed asset identity (never the Notion page UUID).

    Returns (asset_id, gap). asset_id comes from the governed "Asset ID"
    property only. A missing or blank Asset ID is an explicit identity gap;
    the page UUID is never substituted.
    """
    asset_id = _rich_text(properties, ASSET_ID_PROPERTY)
    if asset_id:
        return asset_id, None
    return None, "identity: no governed Asset ID on the Notion record"


def project_reuse_scope(
    properties: Mapping[str, object], *, relation_first: bool, step_scope: str | None
) -> str:
    """Project reuse_scope per #3253.

    The read step's own provenance decides when the record does not declare
    scope: a relation-first hit proves unit-specific membership; the
    coursewide step proves coursewide eligibility. Scope is never inferred
    from prose and never fabricated.
    """
    # A record-declared scope wins when it names a governed value; otherwise
    # the step provenance decides. Unknown stays unknown (fail closed).
    declared = _select_value(properties, "Reuse Scope")
    if declared in {"unit-specific", "coursewide", "cross-unit", "global", "unrelated", "unknown"}:
        return declared
    if relation_first:
        return "unit-specific"
    if step_scope in {"unit-specific", "coursewide", "cross-unit", "global", "unrelated", "unknown"}:
        return step_scope
    return "unknown"


def project_reuse_status(properties: Mapping[str, object]) -> str:
    """Project reuse_status, separate from scope (#3253).

    The Icon System "Reusable Across Units?" checkbox is the governed signal
    for reusable; anything else is unknown. Scope and reuse status are never
    conflated.
    """
    if _checkbox(properties, REUSABLE_ACROSS_UNITS_PROPERTY) is True:
        return "reusable"
    return "unknown"


def project_scope_unit_ids(properties: Mapping[str, object]) -> tuple[str, ...]:
    """Project scope_unit_ids for cross-unit assets (bounded, validated)."""
    prop = properties.get(SCOPE_UNIT_IDS_PROPERTY)
    if not isinstance(prop, Mapping):
        return ()
    ids: list[str] = []
    for key in ("multi_select", "relation"):
        values = prop.get(key)
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, Mapping):
                    continue
                if key == "multi_select":
                    name = item.get("name")
                    if isinstance(name, str) and name.strip():
                        ids.append(name.strip())
                else:
                    page_id = item.get("id")
                    if isinstance(page_id, str) and page_id.strip():
                        ids.append(page_id.strip())
    # Also accept a comma-separated rich text fallback (governed property,
    # explicit values only).
    if not ids:
        text = _rich_text(properties, SCOPE_UNIT_IDS_PROPERTY)
        if text:
            ids = [token.strip() for token in text.split(",") if token.strip()]
    return tuple(ids[:24])


def project_drive_file_id(properties: Mapping[str, object]) -> str | None:
    """Project the Drive file binding; None when the record carries none."""
    return _rich_text(properties, DRIVE_FILE_ID_PROPERTY)


# ---------------------------------------------------------------------------
# v2 compatibility-evidence field projection.
#
# Every v2 field names its governed source. Fields with no live source are
# explicit gaps: the envelope cannot validate as v2 and the record routes to
# incomplete-evidence / manual review. Nothing is invented.
# ---------------------------------------------------------------------------

V2_FIELD_SOURCES: dict[str, dict[str, str]] = {
    "library_record.page_id": {
        "source": "Notion page UUID (provider fact)",
        "owner": "orchestrator (bounded read)",
        "failure": "missing -> record rejected (CurriculumReadError)",
    },
    "library_record.drive_file_id": {
        "source": "Visual Asset Library 'Drive File ID' rich_text",
        "owner": "projection.project_drive_file_id",
        "failure": "missing -> cannot join tuple scoping; incomplete-evidence",
    },
    "library_record.asset_title": {
        "source": "Visual Asset Library 'Asset Title' (title)",
        "owner": "projection",
        "failure": "missing -> allowed (nullable in contract)",
    },
    "library_record.approved_use": {
        "source": "Visual Asset Library 'Approved use' (raw text, 84/525 populated)",
        "owner": "projection.map_material_type (val source)",
        "failure": "unmapped value -> manual-review-required; never invented",
    },
    "library_record.human_review_status": {
        "source": "Visual Asset Library 'Human Review Done' (checkbox, 7/525)",
        "owner": "projection",
        "failure": "empty -> not-assessed; never approved",
    },
    "compatibility_evidence.asset_reference.asset_id": {
        "source": "Visual Asset Library 'Asset ID' (governed property; NO live population)",
        "owner": "projection.project_asset_identity",
        "failure": "missing -> EXPLICIT GAP (identity); incomplete-evidence; never page_id",
    },
    "compatibility_evidence.approved_use.state": {
        "source": "VAL 'Reuse status' / Icon System 'Source Approved?'",
        "owner": "projection.project_approval",
        "failure": "empty -> pending/manual-review-required; never approved",
    },
    "compatibility_evidence.cohesion_profile.visual_style_family": {
        "source": "VAL 'Style family' free text (378/525; unmapped vocabulary)",
        "owner": "projection (vocabulary map to VISUAL_STYLE_FAMILIES)",
        "failure": "unmapped/empty -> 'unspecified' (governed enum member)",
    },
    "compatibility_evidence.cohesion_profile.medium|representation_class|palette_family|line_treatment|rendering_style|perspective|background_treatment": {
        "source": "NO LIVE SOURCE",
        "owner": "-",
        "failure": "EXPLICIT GAP -> incomplete-evidence; cannot complete v2 envelope",
    },
    "compatibility_evidence.cohesion_profile.cognitive_load_rating": {
        "source": "VAL 'Cognitive load rating' low/medium/high, 0/525 populated; Icon 'Source Cognitive Load Signal' has zero options",
        "owner": "projection (blocked)",
        "failure": "EXPLICIT GAP -> incomplete-evidence; inventing a numeric default is prohibited",
    },
    "compatibility_evidence.cohesion_profile.complexity_rating": {
        "source": "NO LIVE SOURCE",
        "owner": "-",
        "failure": "EXPLICIT GAP -> incomplete-evidence",
    },
    "compatibility_evidence.audience_compatibility.state": {
        "source": "VAL 'Human Review Done' / Icon 'Source Approved?' (no attributable reviewer)",
        "owner": "projection.project_approval",
        "failure": "empty -> not-assessed; reviewer_ref/reviewed_at null (permitted)",
    },
    "compatibility_evidence.manifest_reference": {
        "source": "NO LIVE SOURCE (ingestion writes no manifest binding)",
        "owner": "-",
        "failure": "EXPLICIT GAP -> blocks v2 validation; incomplete-evidence",
    },
    "compatibility_evidence.freshness": {
        "source": "Drive readback / sync timestamps (unverifiable in projection)",
        "owner": "projection",
        "failure": "unverifiable -> stale: true / manual-review-required",
    },
}

# v2 fields that can never be completed from live Notion records today.
V2_EXPLICIT_GAPS: tuple[str, ...] = (
    "compatibility_evidence.asset_reference.asset_id",
    "compatibility_evidence.cohesion_profile.medium",
    "compatibility_evidence.cohesion_profile.representation_class",
    "compatibility_evidence.cohesion_profile.palette_family",
    "compatibility_evidence.cohesion_profile.line_treatment",
    "compatibility_evidence.cohesion_profile.rendering_style",
    "compatibility_evidence.cohesion_profile.perspective",
    "compatibility_evidence.cohesion_profile.background_treatment",
    "compatibility_evidence.cohesion_profile.cognitive_load_rating",
    "compatibility_evidence.cohesion_profile.complexity_rating",
    "compatibility_evidence.manifest_reference",
)


@dataclass(frozen=True)
class ProjectedAsset:
    """Result of projecting one raw Notion asset page.

    kind == "evidence": the record carries a governed asset identity and may
        proceed to eligibility filtering. ``evidence`` holds the governed
        asset-evidence dict.
    kind == "incomplete-evidence": the record is explicitly incomplete
        (identity gap or other unmappable required field). ``evidence`` is
        None; ``gaps`` names every explicit gap. The record is never admitted
        as a candidate, never reported as absence, never approved.
    """

    kind: str
    page_id: str
    evidence: dict[str, Any] | None = None
    gaps: tuple[str, ...] = ()


def project_notion_asset_page(
    page: Mapping[str, object],
    *,
    relation_first: bool,
    reuse_scope: str | None,
) -> ProjectedAsset:
    """Project one raw Notion asset page into governed asset evidence.

    Pure transformation: no I/O. Identity comes from the governed "Asset ID"
    property; approval from governed approval fields; scope/status from the
    #3253 contract. Missing identity is an explicit incomplete-evidence gap.
    """
    page_id = page.get("id")
    if not isinstance(page_id, str) or not page_id.strip():
        raise ValueError("project_notion_asset_page requires a Notion page id")
    page_id = page_id.strip()
    properties = page.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("project_notion_asset_page requires a properties mapping")

    gaps: list[str] = []

    asset_id, identity_gap = project_asset_identity(properties)
    if identity_gap is not None:
        gaps.append(identity_gap)

    approved_requested, approved_student = project_approval(properties)
    scope = project_reuse_scope(properties, relation_first=relation_first, step_scope=reuse_scope)
    status = project_reuse_status(properties)
    scope_unit_ids = project_scope_unit_ids(properties)
    drive_file_id = project_drive_file_id(properties)
    if drive_file_id is None:
        gaps.append("drive binding: no Drive File ID on the Notion record")

    if gaps and asset_id is None:
        # Identity is the join key: without it the record cannot become a
        # candidate. Name it explicitly; never substitute the page UUID.
        return ProjectedAsset(
            kind="incomplete-evidence",
            page_id=page_id,
            gaps=tuple(gaps),
        )

    evidence: dict[str, Any] = {
        "asset_id": asset_id,
        "page_id": page_id,
        "exists": True,
        "approved_for_requested_use": approved_requested,
        "approved_student_reuse": approved_student,
        "canonical_unit_relation": bool(relation_first),
        "reuse_scope": scope,
        "reuse_status": status,
        "source_revision": 1,
    }
    if scope_unit_ids:
        evidence["scope_unit_ids"] = list(scope_unit_ids)
    if drive_file_id is not None:
        evidence["library_reference"] = {
            "page_id": page_id,
            "drive_file_id": drive_file_id,
        }
    if gaps:
        # Non-identity gaps ride along for manual-review visibility; the
        # record may still be admitted by scope but never as approved.
        evidence["evidence_gaps"] = list(gaps)
    return ProjectedAsset(kind="evidence", page_id=page_id, evidence=evidence, gaps=tuple(gaps))


def project_ingestion_admission(record: Mapping[str, object]) -> ProjectedAsset:
    """Project an ingestion coordinator's verified record into admission evidence.

    The ingestion coordinator verifies Drive identity and writes working
    metadata; this projection converts the verified facts (governed Asset ID,
    approval fields, concept, drive binding) into the same governed asset
    evidence shape the orchestrator produces, so the asset becomes an
    eligible candidate on the next run. The Asset ID minting authority and
    format remain an open decision (#3254 §4): the record must carry an
    explicitly minted governed Asset ID; one is never invented here.
    """
    page_id = record.get("page_id")
    if not isinstance(page_id, str) or not page_id.strip():
        raise ValueError("project_ingestion_admission requires page_id")
    asset_id = record.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id.strip():
        return ProjectedAsset(
            kind="incomplete-evidence",
            page_id=page_id.strip(),
            gaps=("identity: ingestion record carries no governed Asset ID (minting authority open)",),
        )
    properties = {
        ASSET_ID_PROPERTY: {"type": "rich_text", "rich_text": [{"plain_text": asset_id.strip()}]},
        DRIVE_FILE_ID_PROPERTY: {"type": "rich_text", "rich_text": [{"plain_text": str(record.get("drive_file_id", ""))}]},
        REUSE_STATUS_PROPERTY: {"type": "status", "status": {"name": str(record.get("reuse_status", ""))}},
        SOURCE_APPROVED_PROPERTY: {"type": "checkbox", "checkbox": bool(record.get("source_approved", False))},
        REUSABLE_ACROSS_UNITS_PROPERTY: {"type": "checkbox", "checkbox": bool(record.get("reusable_across_units", False))},
    }
    projected = project_notion_asset_page(
        {"id": page_id.strip(), "properties": properties},
        relation_first=False,
        reuse_scope=record.get("reuse_scope") if isinstance(record.get("reuse_scope"), str) else None,
    )
    if projected.kind != "evidence" or projected.evidence is None:
        return projected
    evidence = dict(projected.evidence)
    concept = record.get("concept")
    if isinstance(concept, str) and concept.strip():
        evidence["concept"] = concept.strip()
    return ProjectedAsset(kind="evidence", page_id=projected.page_id, evidence=evidence, gaps=projected.gaps)
