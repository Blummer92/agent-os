from copy import deepcopy

from instructional_workflow_contracts.reusable_visual_identity import (
    IDENTITY_CONTRACT_ID,
    issue_reusable_visual_identity,
    validate_standalone_artifact_manifest,
    validate_standalone_visual_asset_compatibility_evidence,
)


def evidence(*, file_id="drive-file-1", fingerprint="a" * 64, kind="original", existing=None):
    lineage = {"kind": kind, "predecessor_asset_id": None, "predecessor_stable_ref": None}
    if kind != "original":
        lineage.update(predecessor_asset_id="visual-asset-parent", predecessor_stable_ref="visual-ref-parent")
    value = {
        "contract_version": IDENTITY_CONTRACT_ID,
        "external_identity": {"provider": "google-drive", "file_id": file_id, "exact_reference": f"drive:{file_id}", "verified": True},
        "content_fingerprint": fingerprint,
        "provenance": {"source_reference": "source-1", "source_fingerprint": "source-fingerprint-1", "evidence_reference": "review-1"},
        "lineage": lineage,
    }
    if existing is not None:
        value["existing_identity"] = existing
    return value


def test_identity_is_deterministic_and_drive_id_is_distinct():
    first = issue_reusable_visual_identity(evidence())
    second = issue_reusable_visual_identity(evidence())
    assert first == second
    assert first["status"] == "valid"
    assert first["identity"]["asset_id"] != "drive-file-1"
    assert first["identity"]["stable_ref"] != "drive-file-1"


def test_existing_identity_reconciles_and_conflict_fails_closed():
    issued = issue_reusable_visual_identity(evidence())["identity"]
    assert issue_reusable_visual_identity(evidence(existing=issued))["status"] == "valid"
    conflicting = dict(issued, asset_id="visual-asset-wrong")
    result = issue_reusable_visual_identity(evidence(existing=conflicting))
    assert result["status"] == "manual-review-required"
    assert "identity.conflict" in result["reason_codes"]


def test_untrusted_descriptive_fields_cannot_mint_identity():
    value = evidence()
    value["filename"] = "Add Content.png"
    result = issue_reusable_visual_identity(value)
    assert result["status"] == "manual-review-required"
    assert result["reason_codes"] == ["identity.untrusted-fields"]


def test_changed_content_and_rendition_get_new_explicit_identity():
    original = issue_reusable_visual_identity(evidence())["identity"]
    rendition = issue_reusable_visual_identity(evidence(file_id="drive-file-2", fingerprint="b" * 64, kind="rendition"))["identity"]
    assert rendition["asset_id"] != original["asset_id"]
    assert rendition["lineage"]["kind"] == "rendition"


def manifest_for(identity_evidence):
    identity = issue_reusable_visual_identity(identity_evidence)["identity"]
    asset = {
        "asset_id": identity["asset_id"], "stable_ref": identity["stable_ref"],
        "content_fingerprint": identity["content_fingerprint"], "perceptual_match_evidence": None,
        "duplicate_group_id": None, "duplicate_relationship": "unique", "disposition": "canonical",
        "canonical_asset_ref": None, "comparison_evidence": "exact governed identity", "confidence": 1.0,
        "rights_classification": "permission-documented", "rights_basis": "permission-evidence", "warning_signals": [],
        "privacy_observations": [], "privacy_mitigation": "none", "privacy_resolved": True,
        "residual_privacy_risk": False, "content_findings": [], "repair_source_status": "not-needed",
        "direct_use_status": "student-ready", "correction_requirement": None, "replacement_required": False,
        "transformations": [], "required_context_flags": [], "preserved_context_flags": [],
        "context_preservation_complete": True,
    }
    return {
        "contract_version": "curriculum-artifact-manifest-v2", "subject": "standalone-reusable-visual",
        "identity_evidence": identity_evidence,
        "identity": {"manifest_id": "standalone-manifest-1", "record_revision": 1, "verified_at": "2026-08-25T14:00:00Z", "fingerprint": "f" * 64},
        "artifact": {"artifact_type": "reusable-visual", "mime_type": "image/png"},
        "external_identity": {
            "provider": "google-drive", "file_id": identity["external_file_id"], "drive_id": "drive-1",
            "resource_key_required": False, "resource_key": None, "parent_folder_ref": "folder-1",
            "exact_reference": identity["external_exact_reference"], "web_view_link": None, "external_revision": "revision-1",
            "modified_time": "2026-08-25T13:00:00Z", "last_verified_at": "2026-08-25T14:00:00Z",
            "verification_scope": "shared-drive", "access_state": "verified", "trashed": False,
        },
        "duplicates": {"candidates": [], "selected_candidate_ref": None},
        "lineage": {"revisions": [], "predecessor_ref": None, "successor_ref": None, "supersession_reason": None},
        "statuses": {"quality_state": "pass", "teacher_approval": "approved", "classroom_readiness": "ready", "production_state": "not-authorized", "publication_state": "not-published", "sharing_state": "private-observed"},
        "quality_rows": [{"row_id": "quality-1", "state": "pass", "reason_codes": []}],
        "assets": [asset],
        "references": [{"reference_id": "source-reference-1", "kind": "source-evidence", "stable_ref": "source-1", "fingerprint": "e" * 64}],
        "authority": {"execution_authorized": False, "external_write_authorized": False, "production_authorized": False, "publication_authorized": False, "side_effects_performed": False},
    }


def compatibility_for(manifest):
    asset = manifest["assets"][0]
    return {
        "library_record": {
            "page_id": "visual-library-page-1", "page_url": "https://example.invalid/page", "drive_file_id": manifest["external_identity"]["file_id"],
            "drive_url": "https://example.invalid/file", "asset_title": "Sanitized interface capture", "approved_use": "approved",
            "asset_type": "screen-capture", "human_review_status": "approved", "review_date": "2026-08-25", "extra_fields": {},
        },
        "compatibility_evidence": {
            "contract_version": "curriculum-visual-asset-compatibility-v2",
            "manifest_reference": {"manifest_id": manifest["identity"]["manifest_id"], "record_revision": 1, "fingerprint": manifest["identity"]["fingerprint"], "verified_at": manifest["identity"]["verified_at"], "external_file_id": manifest["external_identity"]["file_id"]},
            "asset_reference": {"asset_id": asset["asset_id"], "stable_ref": asset["stable_ref"], "content_fingerprint": asset["content_fingerprint"]},
            "library_reference": {"page_id": "visual-library-page-1", "drive_file_id": manifest["external_identity"]["file_id"]},
            "purpose": {"role_types": ["worked-example"], "decorative_only": False},
            "accessibility": {"review_state": "pass", "description_state": "alt-text-present", "description_reference": "alt-text-1"},
            "orientation": {"orientation": "flexible", "aspect_state": "flexible"},
            "approved_use": {"state": "approved", "role_types": ["worked-example"], "material_types": ["presentation"]},
            "freshness": {"manifest_record_revision": 1, "manifest_fingerprint": manifest["identity"]["fingerprint"], "manifest_verified_at": manifest["identity"]["verified_at"], "compatibility_verified_at": "2026-08-25T14:05:00Z", "stale": False},
            "cohesion_profile": {"visual_style_family": "interface", "medium": "screen-capture", "representation_class": "interface-capture", "palette_family": "full-color", "line_treatment": "none", "rendering_style": "realistic", "perspective": "front", "background_treatment": "interface", "complexity_rating": 2, "cognitive_load_rating": 2, "audience_compatibility": {"state": "approved", "reviewer_ref": "reviewer-1", "reviewed_at": "2026-08-25T14:00:00Z", "evidence_reference": "audience-review-1", "stale": False, "contradictory": False}},
            "authority": {"execution_authorized": False, "external_write_authorized": False, "production_authorized": False, "publication_authorized": False, "side_effects_performed": False},
        },
    }


def test_standalone_manifest_has_no_material_requirement_and_binds_identity():
    manifest = manifest_for(evidence())
    assert "requirement_reference" not in manifest
    assert validate_standalone_artifact_manifest(manifest)["status"] == "valid"
    manifest["requirement_reference"] = {"requirement_id": "fake"}
    assert validate_standalone_artifact_manifest(manifest)["status"] == "manual-review-required"


def test_manifest_rights_privacy_and_readiness_gates_are_preserved():
    base = manifest_for(evidence())
    rights = deepcopy(base); rights["assets"][0]["rights_classification"] = "unclear-provenance"; rights["assets"][0]["rights_basis"] = "unclear"
    assert validate_standalone_artifact_manifest(rights)["status"] == "manual-review-required"
    privacy = deepcopy(base); privacy["assets"][0]["privacy_observations"] = ["names"]; privacy["assets"][0]["privacy_resolved"] = False; privacy["assets"][0]["privacy_mitigation"] = "manual-review"
    assert validate_standalone_artifact_manifest(privacy)["status"] == "manual-review-required"
    readiness = deepcopy(base); readiness["assets"][0]["direct_use_status"] = "teacher-only"; readiness["statuses"]["classroom_readiness"] = "manual-review-required"
    assert validate_standalone_artifact_manifest(readiness)["status"] == "manual-review-required"


def test_interface_capture_passes_real_v2_gates_and_external_binding():
    manifest = manifest_for(evidence(file_id="1ovc70FMLRyNS-ibqmlErHQ0HPK6Elqeg"))
    compatibility = compatibility_for(manifest)
    result = validate_standalone_visual_asset_compatibility_evidence(manifest, compatibility)
    assert result["status"] == "valid"
    compatibility["library_record"]["drive_file_id"] = "wrong-drive-id"
    assert validate_standalone_visual_asset_compatibility_evidence(manifest, compatibility)["status"] == "invalid"


def test_compatibility_stale_accessibility_approved_use_and_cohesion_fail_closed():
    manifest = manifest_for(evidence())
    stale = compatibility_for(manifest); stale["compatibility_evidence"]["freshness"]["stale"] = True
    assert validate_standalone_visual_asset_compatibility_evidence(manifest, stale)["status"] == "manual-review-required"
    accessibility = compatibility_for(manifest); accessibility["compatibility_evidence"]["accessibility"]["review_state"] = "fail"
    assert validate_standalone_visual_asset_compatibility_evidence(manifest, accessibility)["status"] == "hard-rejection"
    approved = compatibility_for(manifest); approved["compatibility_evidence"]["approved_use"]["state"] = "pending"
    assert validate_standalone_visual_asset_compatibility_evidence(manifest, approved)["status"] == "manual-review-required"
    cohesion = compatibility_for(manifest); cohesion["compatibility_evidence"]["cohesion_profile"]["medium"] = "digital"
    assert validate_standalone_visual_asset_compatibility_evidence(manifest, cohesion)["status"] == "hard-rejection"


def test_compatibility_asset_mismatch_fails_closed():
    manifest = manifest_for(evidence())
    compatibility = compatibility_for(manifest)
    compatibility["compatibility_evidence"]["asset_reference"]["content_fingerprint"] = "b" * 64
    result = validate_standalone_visual_asset_compatibility_evidence(manifest, compatibility)
    assert result["status"] == "manual-review-required"
    assert "manual-review-asset-association-missing" in result["reason_codes"]
