"""Regression tests for #3255: candidate / result size limits.

The shared 16 KiB result bound made `filter_approved_visual_candidates`
fail the entire query at ~7 eligible v2 candidates, and the 32-candidate
count bound failed it at 33. This module proves, through the real
producers and consumers:

* >=64 realistic serialized eligible v2 candidates reach cohesive planning
  and selection without a size failure, handed off by reference;
* the by-reference plan is identical to an unbounded reference run;
* overflow produces the explicit `capacity-exceeded` outcome per item --
  never the whole query for transport overflow, never absence or review;
* every producer maximum is <= its consumer's maximum along the
  Picker / filter / planner / curriculum-evidence chain;
* IMC reports capacity failure as capacity, not manual review.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.artifact_manifest import (
    artifact_manifest_idempotency_key,
    artifact_manifest_source_fingerprint,
    validate_artifact_manifest,
)
from instructional_workflow_contracts.cohesive_visual_plan import (
    MAX_ELIGIBLE_CANDIDATES as PLANNER_MAX_ELIGIBLE_CANDIDATES,
)
from instructional_workflow_contracts.cohesive_visual_plan import (
    plan_cohesive_visual_set,
)
from instructional_workflow_contracts.current_curriculum_evidence import (
    MAX_ASSET_EVIDENCE,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    MAX_CANDIDATES as FILTER_MAX_CANDIDATES,
)
from instructional_workflow_contracts.visual_asset_candidates import (
    PROJECTION_TRANSPORT_BY_REFERENCE,
    PROJECTION_TRANSPORT_INLINE,
    V2_CONTRACT_ID,
    _filter_with_transport_bound,
    filter_approved_visual_candidates,
)
from instructional_workflow_contracts.visual_asset_compatibility import (
    validate_visual_asset_compatibility_evidence,
)
from instructional_workflow_contracts.visual_asset_picker import (
    MAX_CANDIDATES as PICKER_MAX_CANDIDATES,
)
from instructional_workflow_contracts.visual_needs import plan_visual_needs

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"


def _hex(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _plan():
    result = plan_visual_needs(_load("valid_material_requirement_v2.json"))
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return result.record


def _build_candidate(index: int, *, role_types: list[str] | None = None) -> tuple[dict, object]:
    """Build one realistic distinct v2 envelope, validated by the real producer.

    Each candidate carries its own re-signed artifact manifest and library
    record with distinct identities, exactly as a real retrieval would
    produce. The returned record is the validated compatibility record.
    """
    envelope = _load("valid_visual_asset_compatibility_v2.json")
    asset_id = f"asset-{index:03d}"
    stable_ref = f"asset-ref-{index:03d}"
    content_fp = _hex(f"asset-content-{index:03d}")
    page_id = f"page-{index:03d}"
    drive_file_id = f"drive-file-{index:03d}"

    manifest = envelope["artifact_manifest"]
    manifest["identity"]["manifest_id"] = f"manifest-{index:03d}"
    manifest["external_identity"]["file_id"] = drive_file_id
    manifest["external_identity"]["exact_reference"] = f"drive:{drive_file_id}"
    manifest["external_identity"]["web_view_link"] = (
        f"https://example.invalid/{drive_file_id}"
    )
    asset = manifest["assets"][0]
    asset["asset_id"] = asset_id
    asset["stable_ref"] = stable_ref
    asset["content_fingerprint"] = content_fp
    manifest["operation"]["idempotency_key"] = artifact_manifest_idempotency_key(
        manifest
    )
    manifest["custom_properties"]["manifest_id"] = f"manifest-{index:03d}"
    manifest["custom_properties"]["idempotency_key"] = manifest["operation"][
        "idempotency_key"
    ]
    manifest["identity"]["source_fingerprint"] = artifact_manifest_source_fingerprint(
        manifest
    )
    manifest_result = validate_artifact_manifest(manifest)
    assert manifest_result.status is ValidationStatus.VALID
    assert manifest_result.record is not None
    manifest_record = manifest_result.record

    library = envelope["library_record"]
    library["page_id"] = page_id
    library["drive_file_id"] = drive_file_id
    library["page_url"] = f"https://example.invalid/{page_id}"
    library["drive_url"] = f"https://example.invalid/{drive_file_id}"
    library["asset_title"] = f"Test Asset {index:03d}"

    roles = role_types if role_types is not None else ["worked-example"]
    evidence = envelope["compatibility_evidence"]
    evidence["manifest_reference"] = {
        "manifest_id": manifest_record.record_id,
        "record_revision": manifest_record.record_revision,
        "fingerprint": manifest_record.fingerprint,
        "verified_at": manifest["identity"]["verified_at"],
        "external_file_id": drive_file_id,
    }
    evidence["freshness"]["manifest_record_revision"] = (
        manifest_record.record_revision
    )
    evidence["freshness"]["manifest_fingerprint"] = manifest_record.fingerprint
    evidence["freshness"]["manifest_verified_at"] = manifest["identity"]["verified_at"]
    evidence["asset_reference"] = {
        "asset_id": asset_id,
        "stable_ref": stable_ref,
        "content_fingerprint": content_fp,
    }
    evidence["library_reference"] = {
        "page_id": page_id,
        "drive_file_id": drive_file_id,
    }
    # Flexible orientation and both plan role types so the candidate is
    # planner-eligible for every role in the fixture visual-needs plan.
    evidence["purpose"]["role_types"] = roles
    evidence["approved_use"]["role_types"] = roles
    evidence["orientation"]["orientation"] = "flexible"

    result = validate_visual_asset_compatibility_evidence(envelope)
    assert result.status is ValidationStatus.VALID, (
        index,
        result.status,
        result.reason_codes,
    )
    assert result.record is not None
    return envelope, result.record


def _build_population(count: int) -> tuple[list[dict], dict[tuple[str, str], object]]:
    """Build `count` realistic candidates and their projection store.

    Candidate 1 is the deterministic required-role winner (exact
    landscape orientation, lowest cognitive load). Candidates 2..N are
    flexible-orientation rating-1 candidates matching both plan roles;
    they tie deterministically on the optional role. All candidates pass
    the fixture plan's load ceiling (2), so the population exercises the
    transport -- not Lane C's decision-blocked load model.
    """
    envelopes: list[dict] = []
    store: dict[tuple[str, str], object] = {}
    for index in range(1, count + 1):
        if index == 1:
            envelope, record = _build_candidate(
                index, role_types=["worked-example"]
            )
            evidence = envelope["compatibility_evidence"]
            evidence["orientation"]["orientation"] = "landscape"
            evidence["cohesion_profile"]["cognitive_load_rating"] = 1
        else:
            envelope, record = _build_candidate(
                index, role_types=["comparison", "worked-example"]
            )
            evidence = envelope["compatibility_evidence"]
            evidence["cohesion_profile"]["cognitive_load_rating"] = 1
        revalidated = validate_visual_asset_compatibility_evidence(envelope)
        assert revalidated.status is ValidationStatus.VALID, (
            index,
            revalidated.reason_codes,
        )
        assert revalidated.record is not None
        record = revalidated.record
        envelopes.append(envelope)
        store[(record.record_id, record.fingerprint)] = record
    return envelopes, store


def test_64_eligible_v2_candidates_reach_planning_by_reference() -> None:
    plan = _plan()
    envelopes, store = _build_population(64)

    result = filter_approved_visual_candidates(
        plan,
        envelopes,
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["projection_transport"] == PROJECTION_TRANSPORT_BY_REFERENCE
    assert payload["candidate_count"] == 64
    assert len(payload["eligible"]) == 64
    assert payload["capacity_exceeded"] == []
    assert {entry["classification"] for entry in payload["eligible"]} == {"eligible"}

    plan_result = plan_cohesive_visual_set(
        plan, result, candidate_projections=store
    )
    assert plan_result.record is not None
    plan_payload = plan_result.record.to_dict()
    # Candidate 1 (lowest cognitive load) wins the required role outright.
    assert len(plan_payload["required_role_assignments"]) == 1
    selected = plan_payload["required_role_assignments"][0]["selected_candidate"]
    assert selected["asset_reference"]["asset_id"] == "asset-001"


def test_bounded_plan_is_identical_to_unbounded_reference_run() -> None:
    # The unbounded inline record cannot exist as a ValidatedRecord (the
    # record type itself enforces the 16 KiB bound), so the reference run
    # forces the by-reference transport on a small population with a tiny
    # bound and proves selection is identical to the inline form.
    plan = _plan()
    envelopes, store = _build_population(6)

    inline = filter_approved_visual_candidates(
        plan,
        copy.deepcopy(envelopes),
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )
    assert inline.status is ValidationStatus.VALID
    assert inline.record is not None
    assert (
        inline.record.to_dict()["projection_transport"]
        == PROJECTION_TRANSPORT_INLINE
    )
    inline_plan = plan_cohesive_visual_set(plan, inline)
    assert inline_plan.record is not None

    by_reference = _filter_with_transport_bound(
        plan,
        copy.deepcopy(envelopes),
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
        transport_bound=2048,
    )
    assert by_reference.status is ValidationStatus.VALID
    assert by_reference.record is not None
    assert (
        by_reference.record.to_dict()["projection_transport"]
        == PROJECTION_TRANSPORT_BY_REFERENCE
    )
    by_reference_plan = plan_cohesive_visual_set(
        plan, by_reference, candidate_projections=store
    )
    assert by_reference_plan.record is not None

    inline_payload = inline_plan.record.to_dict()
    by_reference_payload = by_reference_plan.record.to_dict()
    assert (
        inline_payload["selected_candidates"]
        == by_reference_payload["selected_candidates"]
    )
    assert (
        inline_payload["required_role_assignments"]
        == by_reference_payload["required_role_assignments"]
    )
    assert (
        inline_payload["optional_role_assignments"]
        == by_reference_payload["optional_role_assignments"]
    )
    assert inline_payload["outcome"] == by_reference_payload["outcome"]
    assert inline_plan.status == by_reference_plan.status


def test_count_bound_reports_explicit_capacity_exceeded() -> None:
    plan = _plan()
    envelopes, _ = _build_population(64)
    envelopes.append(copy.deepcopy(envelopes[0]))

    result = filter_approved_visual_candidates(
        plan,
        envelopes,
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )

    assert result.status is ValidationStatus.INVALID
    assert result.record is None
    # Explicit capacity code: not absence, not review, not generic oversized.
    assert result.reason_codes == ("capacity-exceeded",)


def test_small_populations_keep_inline_transport_unchanged() -> None:
    plan = _plan()
    envelopes, _ = _build_population(6)

    result = filter_approved_visual_candidates(
        plan,
        envelopes,
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )

    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["projection_transport"] == PROJECTION_TRANSPORT_INLINE
    assert len(payload["eligible"]) == 6
    # Inline entries keep the full validated projection.
    assert "cohesion_profile" in payload["eligible"][0]
    assert "matched_asset" in payload["eligible"][0]

    # The planner consumes inline results without a projection store.
    plan_result = plan_cohesive_visual_set(plan, result)
    assert plan_result.record is not None


def test_transport_overflow_degrades_per_item_not_whole_query() -> None:
    plan = _plan()
    # 64 candidates that all mismatch the plan on role and material: every
    # entry carries multiple rejection reason codes, so even the
    # by-reference form overflows the 16 KiB bound and the filter must
    # degrade per item.
    envelopes: list[dict] = []
    for index in range(1, 65):
        envelope, _ = _build_candidate(index, role_types=["teacher-model"])
        envelope["compatibility_evidence"]["approved_use"]["material_types"] = [
            "slides"
        ]
        revalidated = validate_visual_asset_compatibility_evidence(envelope)
        assert revalidated.status is ValidationStatus.VALID
        envelopes.append(envelope)

    result = filter_approved_visual_candidates(
        plan,
        envelopes,
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )

    # Not a whole-query failure...
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    payload = result.record.to_dict()
    assert payload["projection_transport"] == PROJECTION_TRANSPORT_BY_REFERENCE
    # ...but per-item capacity-exceeded markers for what did not fit.
    assert len(payload["capacity_exceeded"]) > 0
    for marker in payload["capacity_exceeded"]:
        assert marker["classification"] == "capacity-exceeded"
        assert marker["reason_codes"] == ["capacity-exceeded"]
    # Transported entries plus markers still account for every candidate.
    transported = (
        len(payload["eligible"])
        + len(payload["rejected"])
        + len(payload["manual_review"])
        + len(payload["capacity_exceeded"])
    )
    assert transported == 64


def test_by_reference_result_requires_projection_store() -> None:
    plan = _plan()
    envelopes, _ = _build_population(64)

    result = filter_approved_visual_candidates(
        plan,
        envelopes,
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )
    assert result.status is ValidationStatus.VALID

    plan_result = plan_cohesive_visual_set(plan, result)
    assert plan_result.status is ValidationStatus.INVALID
    assert plan_result.record is None
    assert plan_result.reason_codes == (
        "asset-cohesive-plan-missing-projections",
    )


def test_tampered_projection_fails_closed() -> None:
    plan = _plan()
    envelopes, store = _build_population(64)

    result = filter_approved_visual_candidates(
        plan,
        envelopes,
        source_revision="visual-library-snapshot-3255",
        contract_version=V2_CONTRACT_ID,
    )
    assert result.status is ValidationStatus.VALID

    payload = result.record.to_dict()
    victim = payload["eligible"][0]
    tampered_store = dict(store)
    tampered_store.pop((victim["compatibility_id"], victim["fingerprint"]))

    plan_result = plan_cohesive_visual_set(
        plan, result, candidate_projections=tampered_store
    )
    assert plan_result.status is ValidationStatus.INVALID
    assert plan_result.record is None
    assert plan_result.reason_codes == (
        "asset-cohesive-plan-projection-mismatch",
    )


def test_producer_maxima_do_not_exceed_consumer_maxima() -> None:
    """Chain test (#3255 acceptance): every producer maximum <= its consumer.

    The maxima are read from the owning modules, never hardcoded, so a
    sibling lane (notably #3251 multi-slot) may raise values without
    breaking this test -- only the producer<=consumer relationship is
    pinned. The curriculum asset-evidence bound (24) against the 51 Icon
    System records is #3253's coursewide reconciliation point and is
    intentionally not raised here.
    """
    assert MAX_ASSET_EVIDENCE <= PICKER_MAX_CANDIDATES
    assert PICKER_MAX_CANDIDATES <= FILTER_MAX_CANDIDATES
    assert FILTER_MAX_CANDIDATES <= PLANNER_MAX_ELIGIBLE_CANDIDATES


def test_imc_reports_capacity_failure_as_capacity_not_review() -> None:
    pytest.importorskip("instructional_materials_coach")
    from instructional_materials_coach import visual_reuse

    envelopes, _ = _build_population(64)
    envelopes.append(copy.deepcopy(envelopes[0]))

    plan = visual_reuse.plan_governed_visual_reuse(
        _load("valid_material_requirement_v2.json"),
        artifact_manifests=[_load("valid_artifact_manifest.json")],
        visual_candidates=envelopes,
        source_revision="visual-library-snapshot-3255",
    )

    assert plan.outcome == "capacity-exceeded"
    assert plan.final_production_blocked is True
    assert plan.candidate_filter_result is not None
    assert (
        "capacity-exceeded" in plan.candidate_filter_result.reason_codes
    )


def test_imc_end_to_end_by_reference_reaches_planning() -> None:
    pytest.importorskip("instructional_materials_coach")
    from instructional_materials_coach import visual_reuse

    envelopes, _ = _build_population(64)

    plan = visual_reuse.plan_governed_visual_reuse(
        _load("valid_material_requirement_v2.json"),
        artifact_manifests=[_load("valid_artifact_manifest.json")],
        visual_candidates=envelopes,
        source_revision="visual-library-snapshot-3255",
    )

    assert plan.candidate_filter_result is not None
    assert plan.candidate_filter_result.status is ValidationStatus.VALID
    assert plan.cohesive_visual_plan_result is not None
    # 64 candidates flow through IMC scoping -> filter -> planner.
    assert plan.cohesive_visual_plan_result.record is not None
