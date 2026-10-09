"""Focused acceptance tests for #3253: coursewide/cross-unit eligibility scope.

Covers the governed reuse-scope vocabulary, the assembler's scope admission
policy, the resolver's out-of-scope (non-absence) outcome codes, the
orchestrator's coursewide read route, and IMC scoping admission of
scope-eligible assets. The Photography Foundations fixture retains the
#3104 Scenario B acceptance shape.
"""

from __future__ import annotations

import pytest

from instructional_workflow_contracts.common import ContractValidationError, ValidationStatus
from instructional_workflow_contracts.current_curriculum_evidence import (
    REUSE_SCOPES,
    REUSE_STATUSES,
    assemble_current_curriculum_evidence,
)
from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)
from instructional_materials_coach.visual_reuse import (
    _scope_candidates_to_current_assets,
)
from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CANONICAL_UNIT,
    VISUAL_ASSETS,
    CurriculumReadError,
    CurriculumReadRequest,
    build_curriculum_read_plan,
    orchestrate_curriculum_evidence,
)

UNIT_PAGE = "3907ac78-3131-8129-8c73-cd9f6b8e8a7d"


def unit() -> dict[str, object]:
    return {"stable_id": "photography-foundations", "status": "active"}


def request(*, assets: bool = True) -> dict[str, object]:
    return {
        "action": "what-images-exist",
        "artifact_type": "images",
        "relative_time": "none",
        "requires_reusable_assets": assets,
    }


def asset(
    asset_id: str,
    *,
    scope: str | None = "unit-specific",
    status: str = "reusable",
    related: bool = True,
    scope_unit_ids: list[str] | None = None,
    approved: bool = True,
) -> dict[str, object]:
    record: dict[str, object] = {
        "asset_id": asset_id,
        "exists": True,
        "approved_for_requested_use": approved,
        "approved_student_reuse": approved,
        "source_revision": 1,
        "canonical_unit_relation": related,
    }
    if scope is not None:
        record["reuse_scope"] = scope
    record["reuse_status"] = status
    if scope_unit_ids is not None:
        record["scope_unit_ids"] = scope_unit_ids
    return record


def assemble(asset_evidence, **kwargs):
    return assemble_current_curriculum_evidence(
        request=request(), canonical_unit=unit(), asset_evidence=asset_evidence, **kwargs
    )


def resolve(packet):
    result = resolve_current_curriculum_state(packet)
    assert result.status is not ValidationStatus.INVALID, result.reason_codes
    assert result.record is not None
    return result.record.to_dict()


# --- scope vocabulary -------------------------------------------------------


def test_scope_vocabulary_is_complete_and_status_is_separate() -> None:
    assert REUSE_SCOPES == {
        "unit-specific", "coursewide", "cross-unit", "global", "unrelated", "unknown",
    }
    assert REUSE_STATUSES == {"reusable", "single-use", "unknown"}
    packet = assemble([asset("icon-camera", scope="coursewide", related=False)])
    admitted = packet["asset_evidence"][0]
    # Scope and reuse status ride as separate contract fields; the provider
    # relation marker is stripped.
    assert admitted["reuse_scope"] == "coursewide"
    assert admitted["reuse_status"] == "reusable"
    assert "canonical_unit_relation" not in admitted


def test_invalid_scope_and_status_fail_closed() -> None:
    with pytest.raises(ContractValidationError, match="reuse_scope"):
        assemble([asset("bad", scope="everywhere", related=False)])
    with pytest.raises(ContractValidationError, match="reuse_status"):
        assemble([asset("bad", scope="coursewide", status="forever", related=False)])


# --- assembler admission policy ----------------------------------------------


def test_coursewide_icon_without_unit_relation_is_admitted() -> None:
    packet = assemble([asset("icon-camera", scope="coursewide", related=False)])
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["icon-camera"]
    assert packet["scope_excluded_asset_ids"] == []


def test_global_asset_without_unit_relation_is_admitted() -> None:
    packet = assemble([asset("brand-mark", scope="global", related=False)])
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["brand-mark"]


def test_cross_unit_asset_admitted_only_for_listed_units() -> None:
    packet = assemble([
        asset("icon-grid", scope="cross-unit", related=False,
              scope_unit_ids=["photography-foundations", "motion-spot"]),
    ])
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["icon-grid"]
    packet = assemble([
        asset("icon-grid", scope="cross-unit", related=False,
              scope_unit_ids=["motion-spot"]),
    ])
    assert packet["asset_evidence"] == []
    assert packet["scope_excluded_asset_ids"] == ["icon-grid"]


def test_unit_specific_still_requires_the_relation() -> None:
    packet = assemble([asset("pf-010", scope="unit-specific", related=True)])
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["pf-010"]
    packet = assemble([asset("pf-010", scope="unit-specific", related=False)])
    assert packet["asset_evidence"] == []
    assert packet["scope_excluded_asset_ids"] == ["pf-010"]


def test_unrelated_and_unknown_are_never_admitted() -> None:
    packet = assemble([
        asset("other-course", scope="unrelated", related=False),
        asset("mystery", scope="unknown", related=False),
    ])
    assert packet["asset_evidence"] == []
    assert packet["scope_excluded_asset_ids"] == ["mystery", "other-course"]


def test_legacy_assets_without_scope_keep_relation_first_behavior() -> None:
    packet = assemble([asset("pf-010", scope=None, related=True)])
    assert [item["asset_id"] for item in packet["asset_evidence"]] == ["pf-010"]
    packet = assemble([asset("pf-010", scope=None, related=False)])
    assert packet["asset_evidence"] == []
    # Legacy drops are not mislabeled as scope exclusions.
    assert packet["scope_excluded_asset_ids"] == []


# --- resolver outcome codes --------------------------------------------------


def test_coursewide_eligible_icon_is_never_reported_absent() -> None:
    record = resolve(assemble([
        asset("icon-camera", scope="coursewide", related=False),
    ]))
    assets = record["assets"]
    assert assets["matching_asset_exists"] is True
    assert assets["approved_reusable_student_facing_exists"] is True
    assert "asset-out-of-scope" not in record["reason_codes"]
    assert "asset-reusable-unavailable" not in record["blockers"]


def test_out_of_scope_assets_get_a_non_absence_outcome_code() -> None:
    record = resolve(assemble([
        asset("other-course", scope="unrelated", related=False),
    ]))
    assets = record["assets"]
    # In-scope absence accounting is untouched by the excluded asset...
    assert assets["matching_asset_exists"] is False
    assert assets["scope_excluded_asset_ids"] == ["other-course"]
    # ...but the outcome is explicitly out-of-scope, never bare absence.
    assert "asset-out-of-scope" in record["reason_codes"]
    assert "asset-reusable-unavailable" in record["blockers"]
    assert record["disposition"] == "blocked"


def test_mixed_fixture_stays_distinguishable_end_to_end() -> None:
    record = resolve(assemble([
        asset("pf-010", scope="unit-specific", related=True),
        asset("icon-camera", scope="coursewide", related=False),
        asset("brand-mark", scope="global", related=False),
        asset("other-course", scope="unrelated", related=False),
    ]))
    assets = record["assets"]
    assert assets["asset_ids"] == ["brand-mark", "icon-camera", "pf-010"]
    assert assets["scope_excluded_asset_ids"] == ["other-course"]
    assert "asset-out-of-scope" in record["reason_codes"]


# --- orchestrator coursewide read route -------------------------------------


def identity(source: str) -> dict[str, object]:
    return {
        "logical_source": source,
        "data_source_id": f"ds-{source}",
        "human_review_required": False,
    }


def test_coursewide_step_fails_closed_instead_of_dispatching_checkbox_filter() -> None:
    """#2816: the coursewide step is still planned (no fabricated relation),
    but dispatching its Icon System checkbox filter against the Visual Asset
    Library — which does not expose that property (live Notion 400,
    run 37845400763) — fails closed with the bounded schema-mismatch reason
    instead of reaching the provider."""
    plan = build_curriculum_read_plan(CurriculumReadRequest("images", "images"))
    coursewide = plan.steps[2]
    assert coursewide.logical_source == VISUAL_ASSETS
    assert coursewide.relation_first is False
    assert coursewide.reuse_scope == "coursewide"
    calls: list[tuple[object, dict[str, object]]] = []

    def reader(step, payload):
        calls.append((step, dict(payload)))
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        return {"results": []}

    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit={
                "stable_id": "photography-foundations",
                "status": "active",
                "provider_page_id": UNIT_PAGE,
            },
            resolve_identity=identity,
            execute_read=reader,
        )
    coursewide_calls = [
        payload for step, payload in calls
        if getattr(step, "reuse_scope", None) == "coursewide"
    ]
    assert coursewide_calls == []
    assert "Reusable Across Units?" not in repr(calls)


def test_raw_coursewide_page_never_reaches_provider_filter_2816() -> None:
    """#2816: even when the provider would have returned Icon-System-shaped
    pages, the coursewide checkbox filter is never dispatched against the
    Visual Asset Library — the step fails closed on the schema mismatch
    before any provider query."""
    def reader(step, payload):
        if step.logical_source == CANONICAL_UNIT:
            return {"id": UNIT_PAGE}
        if getattr(step, "reuse_scope", None) == "coursewide":
            return {
                "results": [{
                    "id": "icon-page-camera",
                    "properties": {
                        # #3254: governed identity (not the page UUID) and
                        # governed approval fields. The scope still comes
                        # from the coursewide step's provenance (#3253).
                        "Asset ID": {"type": "rich_text", "rich_text": [{"plain_text": "VA-20261002-0001"}]},
                        "Drive File ID": {"type": "rich_text", "rich_text": [{"plain_text": "drive-icon-camera"}]},
                        "Source Approved?": {"type": "checkbox", "checkbox": True},
                        "Reusable Across Units?": {"type": "checkbox", "checkbox": True},
                    },
                }]
            }
        return {"results": []}

    with pytest.raises(CurriculumReadError, match="filter-property-unavailable"):
        orchestrate_curriculum_evidence(
            request=CurriculumReadRequest("images", "images"),
            canonical_unit={
                "stable_id": "photography-foundations",
                "status": "active",
                "provider_page_id": UNIT_PAGE,
            },
            resolve_identity=identity,
            execute_read=reader,
        )


# --- IMC scoping --------------------------------------------------------------


def candidate(asset_id: str, page_id: str, drive_file_id: str | None) -> dict[str, object]:
    library_reference: dict[str, object] = {"page_id": page_id}
    if drive_file_id is not None:
        library_reference["drive_file_id"] = drive_file_id
    return {
        "compatibility_evidence": {
            "asset_reference": {"asset_id": asset_id},
            "library_reference": library_reference,
        }
    }


def evidence(asset_id: str, page_id: str, drive_file_id: str | None, scope: str) -> dict[str, object]:
    library_reference: dict[str, object] = {"page_id": page_id}
    if drive_file_id is not None:
        library_reference["drive_file_id"] = drive_file_id
    return {
        "asset_id": asset_id,
        "reuse_scope": scope,
        "library_reference": library_reference,
    }


def test_imc_scoping_admits_coursewide_asset_without_drive_binding() -> None:
    state, scoped = _scope_candidates_to_current_assets(
        [candidate("icon-camera", "icon-page-camera", None)],
        [evidence("icon-camera", "icon-page-camera", None, "coursewide")],
        source_revision="rev-1",
    )
    assert state == "ok"
    assert len(scoped) == 1


def test_imc_scoping_keeps_unit_specific_drive_requirement() -> None:
    state, scoped = _scope_candidates_to_current_assets(
        [candidate("pf-010", "page-pf-010", None)],
        [evidence("pf-010", "page-pf-010", None, "unit-specific")],
        source_revision="rev-1",
    )
    # #2816-era strictness: unit-specific evidence without a Drive binding
    # admits nothing.
    assert state == "malformed"
    assert scoped == []


def test_imc_scoping_still_matches_exact_unit_specific_triples() -> None:
    state, scoped = _scope_candidates_to_current_assets(
        [candidate("pf-010", "page-pf-010", "file-pf-010")],
        [evidence("pf-010", "page-pf-010", "file-pf-010", "unit-specific")],
        source_revision="rev-1",
    )
    assert state == "ok"
    assert len(scoped) == 1


# --- Photography Foundations retained scenario (#3104 Scenario B) -------------


def test_photography_foundations_coursewide_icons_reach_filtering() -> None:
    icons = [f"icon-{name}" for name in (
        "camera", "reflection", "critique", "portfolio",
        "rule-of-thirds", "grid", "leading-line", "framing",
    )]
    record = resolve(assemble(
        [asset("pf-010", scope="unit-specific", related=True)]
        + [asset(icon, scope="coursewide", related=False) for icon in icons]
    ))
    assets = record["assets"]
    assert assets["matching_asset_exists"] is True
    assert assets["approved_reusable_student_facing_exists"] is True
    for icon in icons:
        assert icon in assets["eligible_asset_ids"]
    assert assets["scope_excluded_asset_ids"] == []
    assert "asset-reusable-unavailable" not in record["blockers"]
