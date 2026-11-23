"""#3672: source-bound title survives compatibility and governs context selection."""
import copy
import hashlib
import json
from pathlib import Path

from instructional_workflow_contracts import ValidationStatus
from instructional_workflow_contracts.artifact_manifest import (
    artifact_manifest_idempotency_key,
    artifact_manifest_source_fingerprint,
    validate_artifact_manifest,
)
from instructional_workflow_contracts.common import (
    FINGERPRINT_ALGORITHM,
    ValidatedRecord,
    ValidationResult,
    freeze_json,
    sha256_hex,
)
from instructional_workflow_contracts.material_requirement import material_requirement_source_fingerprint
from instructional_workflow_contracts.visual_needs import plan_visual_needs
from instructional_workflow_contracts.visual_asset_compatibility import validate_visual_asset_compatibility_evidence
from instructional_workflow_contracts.visual_asset_candidates import V2_CONTRACT_ID, filter_approved_visual_candidates
from instructional_workflow_contracts.cohesive_visual_plan import plan_cohesive_visual_set

FIXTURES = Path(__file__).parent / "fixtures" / "instructional_workflow_contracts"


def fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def concept_plan():
    requirement = fixture("valid_material_requirement_v2.json")
    requirement["visual_direction"]["roles"][0]["concept"] = "Rule of Thirds"
    requirement["identity"]["source_fingerprint"] = material_requirement_source_fingerprint(requirement)
    result = plan_visual_needs(requirement)
    assert result.status is ValidationStatus.VALID
    return result


def evaluate(title, *, extra_fields=None):
    visual = fixture("valid_visual_asset_compatibility_v2.json")
    visual["library_record"]["asset_title"] = title
    visual["library_record"]["extra_fields"] = extra_fields or {}
    compatible = validate_visual_asset_compatibility_evidence(visual)
    assert compatible.status is ValidationStatus.VALID
    candidates = filter_approved_visual_candidates(
        concept_plan(), [visual], source_revision="3672-fixture-snapshot",
        contract_version=V2_CONTRACT_ID,
    )
    assert candidates.status is ValidationStatus.VALID
    result = plan_cohesive_visual_set(concept_plan(), candidates)
    return compatible, candidates, result


def test_verified_title_survives_compatibility_filter_and_is_selected():
    compatibility, candidates, result = evaluate("Rule of Thirds - Off Center Subject")
    payload = compatibility.record.to_dict()
    assert payload["source_context"] == {"asset_title": "Rule of Thirds - Off Center Subject"}
    assert candidates.record.to_dict()["eligible"][0]["source_context"] == payload["source_context"]
    assert result.status is ValidationStatus.VALID
    assignment = result.record.to_dict()["required_role_assignments"][0]
    assert assignment["selected_candidate"]["asset_reference"]["asset_id"] == "asset-1"
    assert assignment["authority"]["external_write_authorized"] is False


def test_changed_source_title_changes_identity_and_blocks_mismatched_concept():
    good, _, _ = evaluate("Rule of Thirds - Example")
    wrong, _, result = evaluate("Leading Lines - Example")
    assert good.record.fingerprint != wrong.record.fingerprint
    assert good.record.record_id != wrong.record.record_id
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    payload = result.record.to_dict()
    assert not payload["required_role_assignments"]
    assert not payload["image_gap_briefs"]
    assert payload["unfilled_required_roles"][0]["outcome_code"] == "review-pending"


def test_missing_title_does_not_trust_unmapped_extra_concept():
    compatible, _, result = evaluate(None, extra_fields={"concept": "Rule of Thirds"})
    assert "source_context" not in compatible.record.to_dict()
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert result.record.to_dict()["required_role_assignments"] == []
    assert result.record.to_dict()["image_gap_briefs"] == []


# ---------------------------------------------------------------------------
# #3672 Phase 5: adversarial + ranking regression coverage.
#
# Every candidate below is a real envelope validated by the real
# compatibility producer, with its own re-signed artifact manifest, exactly
# as governed retrieval would produce. No hand-built planner payloads.
# ---------------------------------------------------------------------------

EXACT_TITLE = "Rule of Thirds - Off Center Subject"
RELATED_TITLE = "The Rule and the Thirds of Composition"


def _hex(seed):
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_candidate(index, title, *, cognitive=2, orientation="landscape",
                    stale=False, approved_state="approved"):
    envelope = fixture("valid_visual_asset_compatibility_v2.json")
    envelope = copy.deepcopy(envelope)
    asset_id = f"asset-{index:03d}"
    stable_ref = f"asset-ref-{index:03d}"
    content_fp = _hex(f"asset-content-{index:03d}")
    page_id = f"page-{index:03d}"
    drive_file_id = f"drive-file-{index:03d}"

    manifest = envelope["artifact_manifest"]
    manifest["identity"]["manifest_id"] = f"manifest-{index:03d}"
    manifest["external_identity"]["file_id"] = drive_file_id
    manifest["external_identity"]["exact_reference"] = f"drive:{drive_file_id}"
    manifest["external_identity"]["web_view_link"] = f"https://example.invalid/{drive_file_id}"
    asset = manifest["assets"][0]
    asset["asset_id"] = asset_id
    asset["stable_ref"] = stable_ref
    asset["content_fingerprint"] = content_fp
    manifest["operation"]["idempotency_key"] = artifact_manifest_idempotency_key(manifest)
    manifest["custom_properties"]["manifest_id"] = f"manifest-{index:03d}"
    manifest["custom_properties"]["idempotency_key"] = manifest["operation"]["idempotency_key"]
    manifest["identity"]["source_fingerprint"] = artifact_manifest_source_fingerprint(manifest)
    manifest_result = validate_artifact_manifest(manifest)
    assert manifest_result.status is ValidationStatus.VALID
    manifest_record = manifest_result.record

    library = envelope["library_record"]
    library["page_id"] = page_id
    library["drive_file_id"] = drive_file_id
    library["page_url"] = f"https://example.invalid/{page_id}"
    library["drive_url"] = f"https://example.invalid/{drive_file_id}"
    library["asset_title"] = title

    evidence = envelope["compatibility_evidence"]
    evidence["manifest_reference"] = {
        "manifest_id": manifest_record.record_id,
        "record_revision": manifest_record.record_revision,
        "fingerprint": manifest_record.fingerprint,
        "verified_at": manifest["identity"]["verified_at"],
        "external_file_id": drive_file_id,
    }
    evidence["freshness"]["manifest_record_revision"] = manifest_record.record_revision
    evidence["freshness"]["manifest_fingerprint"] = manifest_record.fingerprint
    evidence["freshness"]["manifest_verified_at"] = manifest["identity"]["verified_at"]
    evidence["freshness"]["stale"] = stale
    evidence["asset_reference"] = {
        "asset_id": asset_id,
        "stable_ref": stable_ref,
        "content_fingerprint": content_fp,
    }
    evidence["library_reference"] = {"page_id": page_id, "drive_file_id": drive_file_id}
    evidence["orientation"]["orientation"] = orientation
    evidence["approved_use"]["state"] = approved_state
    evidence["cohesion_profile"]["cognitive_load_rating"] = cognitive

    result = validate_visual_asset_compatibility_evidence(envelope)
    # Stale / pending-licensing envelopes validate structurally but classify
    # as manual-review-required; the record still exists for the filter to
    # classify. Denied envelopes stay VALID with a rejected classification.
    assert result.status in (
        ValidationStatus.VALID,
        ValidationStatus.MANUAL_REVIEW_REQUIRED,
    ), (index, result.status, result.reason_codes)
    assert result.record is not None
    return envelope


def plan_with(envelopes, *, needs=None, projections=None):
    needs = needs or concept_plan()
    candidates = filter_approved_visual_candidates(
        needs, envelopes, source_revision="3672-fixture-snapshot",
        contract_version=V2_CONTRACT_ID,
    )
    # Manual-review classifications (stale, pending licensing) still carry
    # a record the planner must classify without selecting the candidate.
    assert candidates.status in (
        ValidationStatus.VALID,
        ValidationStatus.MANUAL_REVIEW_REQUIRED,
    )
    result = plan_cohesive_visual_set(needs, candidates, candidate_projections=projections)
    return candidates, result


def required_assignment(result):
    payload = result.record.to_dict()
    assert payload["required_role_assignments"], payload
    return payload["required_role_assignments"][0]


# 1. Verified exact title wins over an otherwise equivalent related title.
def test_exact_title_wins_over_equivalent_related_title():
    _, result = plan_with([
        build_candidate(2, RELATED_TITLE),
        build_candidate(1, EXACT_TITLE),
    ])
    assert result.status is ValidationStatus.VALID
    assignment = required_assignment(result)
    assert assignment["selected_candidate"]["asset_reference"]["asset_id"] == "asset-001"
    assert assignment["score_evidence"]["concept_match"] == "exact"


# 2. Exact match outranks a supported related match even when the related
# candidate is stronger on every secondary signal.
def test_exact_match_outranks_related_despite_secondary_signals():
    _, result = plan_with([
        build_candidate(2, RELATED_TITLE, cognitive=1, orientation="landscape"),
        build_candidate(1, EXACT_TITLE, cognitive=5, orientation="flexible"),
    ])
    assert result.status is ValidationStatus.VALID
    assignment = required_assignment(result)
    assert assignment["selected_candidate"]["asset_reference"]["asset_id"] == "asset-001"
    assert assignment["score_evidence"]["concept_match"] == "exact"


# 2b. A lone supported-related candidate is selectable, ranked as related.
def test_supported_related_match_is_selectable_when_no_exact_match():
    _, result = plan_with([build_candidate(2, RELATED_TITLE)])
    assert result.status is ValidationStatus.VALID
    assignment = required_assignment(result)
    assert assignment["selected_candidate"]["asset_reference"]["asset_id"] == "asset-002"
    assert assignment["score_evidence"]["concept_match"] == "supported-related"


# 3. Unsupported related matches are not invented: partial word overlap and
# unrelated titles stay insufficient evidence and route to review.
def test_unsupported_related_matches_are_not_invented():
    _, result = plan_with([
        build_candidate(3, "Rule of Composition - Partial Overlap"),
        build_candidate(4, "Leading Lines - Example"),
    ])
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    payload = result.record.to_dict()
    assert payload["required_role_assignments"] == []
    assert payload["image_gap_briefs"] == []
    assert payload["unfilled_required_roles"][0]["outcome_code"] == "review-pending"


# 11 (planner leg). A restricted image with a perfect title match remains
# ineligible: relevance never overrides an approved-use denial.
def test_restricted_image_with_perfect_title_remains_ineligible():
    _, result = plan_with([build_candidate(1, EXACT_TITLE, approved_state="denied")])
    payload = result.record.to_dict()
    assert payload["required_role_assignments"] == []
    assert payload["selected_candidates"] == []


# 12 (planner leg). Missing licensing evidence (pending approval) blocks.
def test_missing_licensing_evidence_remains_blocking():
    _, result = plan_with([build_candidate(1, EXACT_TITLE, approved_state="pending")])
    payload = result.record.to_dict()
    assert payload["required_role_assignments"] == []
    assert payload["selected_candidates"] == []


# 10 (planner leg). Stale source evidence is escalated, never selected.
def test_stale_source_evidence_is_escalated_not_selected():
    _, result = plan_with([build_candidate(1, EXACT_TITLE, stale=True)])
    payload = result.record.to_dict()
    assert payload["required_role_assignments"] == []
    assert payload["selected_candidates"] == []


# 13. Two equally supported candidates preserve ambiguity handling.
def test_equally_supported_candidates_preserve_ambiguity():
    _, result = plan_with([
        build_candidate(1, EXACT_TITLE),
        build_candidate(2, EXACT_TITLE),
    ])
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    payload = result.record.to_dict()
    assert payload["required_role_assignments"] == []
    assert payload["image_gap_briefs"] == []
    assert payload["unfilled_required_roles"][0]["outcome_code"] == "review-pending"


# 16. Inline and by-reference transport produce equivalent selection.
def test_inline_and_by_reference_transport_select_equivalently():
    # Inline leg: a small population the filter transports inline.
    small = [build_candidate(1, EXACT_TITLE), build_candidate(2, RELATED_TITLE)]
    inline_candidates, inline_result = plan_with(small)
    assert inline_candidates.record.to_dict()["projection_transport"] == "inline"
    # By-reference leg: a larger population the filter transports by
    # reference; the same winner must be selected with the same score.
    envelopes = [build_candidate(1, EXACT_TITLE)] + [
        build_candidate(i, RELATED_TITLE) for i in range(2, 8)
    ]
    needs = concept_plan()
    by_ref = filter_approved_visual_candidates(
        needs, envelopes, source_revision="3672-fixture-snapshot",
        contract_version=V2_CONTRACT_ID,
    )
    assert by_ref.status is ValidationStatus.VALID
    assert by_ref.record.to_dict()["projection_transport"] == "by-reference"
    store = {}
    for envelope in envelopes:
        record = validate_visual_asset_compatibility_evidence(envelope).record
        store[(record.record_id, record.fingerprint)] = record
    by_ref_result = plan_cohesive_visual_set(needs, by_ref, candidate_projections=store)
    assert by_ref_result.status is ValidationStatus.VALID
    inline_assignment = required_assignment(inline_result)
    by_ref_assignment = required_assignment(by_ref_result)
    assert (
        by_ref_assignment["selected_candidate"]["asset_reference"]["asset_id"]
        == inline_assignment["selected_candidate"]["asset_reference"]["asset_id"]
        == "asset-001"
    )
    assert by_ref_assignment["assignment_score"] == inline_assignment["assignment_score"]


# 17. A tampered by-reference fingerprint is rejected; the projection store
# record is never trusted under a fingerprint it does not carry.
def test_tampered_reference_fingerprint_is_rejected():
    envelope = build_candidate(1, EXACT_TITLE)
    needs = concept_plan()
    filtered = filter_approved_visual_candidates(
        needs, [envelope], source_revision="3672-fixture-snapshot",
        contract_version=V2_CONTRACT_ID,
    )
    assert filtered.status is ValidationStatus.VALID
    record = validate_visual_asset_compatibility_evidence(envelope).record
    store = {(record.record_id, record.fingerprint): record}
    payload = filtered.record.to_dict()
    payload["projection_transport"] = "by-reference"
    payload["eligible"] = [{
        "compatibility_id": record.record_id,
        "fingerprint": ("0" if record.fingerprint[0] != "0" else "1") + record.fingerprint[1:],
    }]
    tampered = ValidatedRecord(
        contract_version=V2_CONTRACT_ID,
        record_id=payload["candidate_set_id"],
        record_revision=1,
        fingerprint_algorithm=FINGERPRINT_ALGORITHM,
        fingerprint=sha256_hex(payload),
        payload=freeze_json(payload),
    )
    result = plan_cohesive_visual_set(
        needs,
        ValidationResult(ValidationStatus.VALID, tampered),
        candidate_projections=store,
    )
    assert result.status is ValidationStatus.INVALID
    assert result.record is None


# 5 (contract leg). A caller-provided verified flag is never accepted as
# provenance proof: unknown fields fail closed at both envelope levels.
def test_caller_provided_verified_flag_is_not_provenance():
    envelope = build_candidate(1, EXACT_TITLE)
    envelope["compatibility_evidence"]["verified"] = True
    result = validate_visual_asset_compatibility_evidence(envelope)
    assert result.status is ValidationStatus.INVALID

    envelope = build_candidate(1, EXACT_TITLE)
    envelope["verified"] = True
    result = validate_visual_asset_compatibility_evidence(envelope)
    assert result.status is ValidationStatus.INVALID

    envelope = build_candidate(1, EXACT_TITLE)
    envelope["library_record"]["extra_fields"] = {"verified": True, "concept": "Rule of Thirds"}
    result = validate_visual_asset_compatibility_evidence(envelope)
    assert result.status is ValidationStatus.VALID
    assert result.record.to_dict()["source_context"] == {"asset_title": EXACT_TITLE}


# 18. No-concept requests preserve existing selection behavior: no concept
# evidence is demanded and legacy scoring decides deterministically.
def test_no_concept_request_preserves_existing_selection():
    requirement = fixture("valid_material_requirement_v2.json")
    needs = plan_visual_needs(requirement)
    assert needs.status is ValidationStatus.VALID
    _, result = plan_with(
        [
            build_candidate(2, "Any Title - Low Load", cognitive=1),
            build_candidate(1, "Any Title - High Load", cognitive=5),
        ],
        needs=needs,
    )
    assert result.status is ValidationStatus.VALID
    assignment = required_assignment(result)
    # Legacy score prefers the lower cognitive load; no concept gate applies.
    assert assignment["selected_candidate"]["asset_reference"]["asset_id"] == "asset-002"
    assert "concept_match" not in assignment["score_evidence"]


# 19 (planner leg). Selection performs no external writes: every authority
# flag on every produced record remains False.
def test_selection_performs_no_external_writes():
    candidates, result = plan_with([build_candidate(1, EXACT_TITLE)])
    for validation in (candidates, result):
        authority = validation.record.to_dict()["authority"]
        assert set(authority.values()) == {False}


# ---------------------------------------------------------------------------
# #3672 Phase 2: authoritative provenance chain — the governed Notion
# projection is the only title source, and normalization preserves the
# title bound to the exact identity it was projected with.
# ---------------------------------------------------------------------------

from instructional_workflow_contracts.current_curriculum_evidence import (
    assemble_current_curriculum_evidence,
)
from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CurriculumReadError,
    _normalize_assets,
)
from navigation_registry.connectors.notion_asset_evidence_projection import (
    project_asset_title,
    project_notion_asset_page,
)

PROJECTION_FIXTURES = Path(__file__).parent / "fixtures" / "notion_asset_projection_3254"


def test_projection_extracts_real_asset_title_from_notion_record():
    page = json.loads((PROJECTION_FIXTURES / "live_snapshot_icon_page.json").read_text(encoding="utf-8"))
    assert project_asset_title(page["properties"]) == "Checkmark Icon"
    result = project_notion_asset_page(page, relation_first=False, reuse_scope="coursewide")
    assert result.kind == "evidence"
    # The title is bound to the same record's governed identity.
    assert result.evidence["asset_title"] == "Checkmark Icon"
    assert result.evidence["asset_id"] == "VA-20261002-0001"
    assert result.evidence["library_reference"] == {
        "page_id": page["id"],
        "drive_file_id": "drive-file-checkmark-001",
    }


def test_projection_without_title_property_carries_no_title():
    page = json.loads((PROJECTION_FIXTURES / "live_snapshot_icon_page.json").read_text(encoding="utf-8"))
    del page["properties"]["Asset Title"]
    assert project_asset_title(page["properties"]) is None
    result = project_notion_asset_page(page, relation_first=False, reuse_scope="coursewide")
    assert result.kind == "evidence"
    assert "asset_title" not in result.evidence


def test_normalization_preserves_title_through_the_chain():
    page = json.loads((PROJECTION_FIXTURES / "live_snapshot_icon_page.json").read_text(encoding="utf-8"))
    assets, incomplete = _normalize_assets([page], relation_first=False, reuse_scope="coursewide")
    assert incomplete == []
    assert assets[0]["asset_title"] == "Checkmark Icon"
    assert assets[0]["asset_id"] == "VA-20261002-0001"
    assert assets[0]["library_reference"]["drive_file_id"] == "drive-file-checkmark-001"
    # The assembled CLI packet keeps the title on the same evidence item.
    packet = assemble_current_curriculum_evidence(
        request={"action": "images", "artifact_type": "images",
                 "relative_time": "none", "requires_reusable_assets": True},
        canonical_unit={"stable_id": "photography-foundations", "status": "active"},
        asset_evidence=assets,
    )
    assert packet["asset_evidence"][0]["asset_title"] == "Checkmark Icon"
    assert packet["asset_evidence"][0]["asset_id"] == "VA-20261002-0001"


def test_normalization_rejects_malformed_title_fail_closed():
    record = {
        "asset_id": "asset-x",
        "exists": True,
        "approved_for_requested_use": True,
        "approved_student_reuse": True,
        "asset_title": 3672,
    }
    try:
        _normalize_assets([record], relation_first=True, reuse_scope=None)
    except CurriculumReadError:
        pass
    else:
        raise AssertionError("malformed asset_title must fail closed")
