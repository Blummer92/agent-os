import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from instructional_workflow_contracts.reusable_visual_identity import (
    IDENTITY_CONTRACT_ID,
    issue_reusable_visual_identity,
    validate_standalone_artifact_manifest,
    validate_standalone_visual_asset_compatibility_evidence,
)

SOURCE_FILE_ID = "1RCIn3aDHfafrtyCQjfqFqJsu5gVuVP0Y"
SOURCE_SHA256 = "d0a72869d60024921876261a545c00a2e943ac767a7ef71978bcf2048835802e"
DERIVATIVE_FILE_ID = "1ovc70FMLRyNS-ibqmlErHQ0HPK6Elqeg"
DERIVATIVE_SHA256 = "ae911a2c036a9c288b194f6c2e6b7b4591ddf148c113f28d40cfeb3c9b192497"
DERIVATIVE_PARENT = "1VhOY60BuuNOEjD3CcLCxSf4NhqN6Wqqz"
LIBRARY_PAGE_ID = "3c67ac78-3131-81da-bb80-e256a36fd3de"
MANIFEST_ID = "standalone-manifest-1377-add-content"
MANIFEST_FINGERPRINT = "4310b3c44c71f129cfec3d144c6abc27954cd29c378390a3f6bc70819f685588"
VERIFIED_AT = "2026-08-28T21:15:00Z"
DERIVATIVE_MODIFIED_AT = "2026-08-24T21:33:35Z"


def identity_evidence(*, file_id, fingerprint, evidence_reference, lineage):
    return {
        "contract_version": IDENTITY_CONTRACT_ID,
        "external_identity": {
            "provider": "google-drive",
            "file_id": file_id,
            "exact_reference": f"drive:{file_id}",
            "verified": True,
        },
        "content_fingerprint": fingerprint,
        "provenance": {
            "source_reference": f"drive:{SOURCE_FILE_ID}",
            "source_fingerprint": SOURCE_SHA256,
            "evidence_reference": evidence_reference,
        },
        "lineage": lineage,
    }


def real_evidence():
    source_evidence = identity_evidence(
        file_id=SOURCE_FILE_ID,
        fingerprint=SOURCE_SHA256,
        evidence_reference="github-issue-1377-comment-5401561490",
        lineage={
            "kind": "original",
            "predecessor_asset_id": None,
            "predecessor_stable_ref": None,
        },
    )
    source_result = issue_reusable_visual_identity(source_evidence)
    assert source_result["status"] == "valid", source_result
    source_identity = source_result["identity"]

    derivative_evidence = identity_evidence(
        file_id=DERIVATIVE_FILE_ID,
        fingerprint=DERIVATIVE_SHA256,
        evidence_reference="github-issue-1377-comment-5401660536",
        lineage={
            "kind": "sanitized-derivative",
            "predecessor_asset_id": source_identity["asset_id"],
            "predecessor_stable_ref": source_identity["stable_ref"],
        },
    )
    derivative_result = issue_reusable_visual_identity(derivative_evidence)
    assert derivative_result["status"] == "valid", derivative_result
    derivative_identity = derivative_result["identity"]

    manifest = {
        "contract_version": "curriculum-artifact-manifest-v2",
        "subject": "standalone-reusable-visual",
        "identity_evidence": derivative_evidence,
        "identity": {
            "manifest_id": MANIFEST_ID,
            "record_revision": 1,
            "verified_at": VERIFIED_AT,
            "fingerprint": MANIFEST_FINGERPRINT,
        },
        "artifact": {"artifact_type": "reusable-visual", "mime_type": "image/png"},
        "external_identity": {
            "provider": "google-drive",
            "file_id": DERIVATIVE_FILE_ID,
            "drive_id": None,
            "resource_key_required": False,
            "resource_key": None,
            "parent_folder_ref": DERIVATIVE_PARENT,
            "exact_reference": f"drive:{DERIVATIVE_FILE_ID}",
            "web_view_link": f"https://drive.google.com/file/d/{DERIVATIVE_FILE_ID}/view",
            "external_revision": None,
            "modified_time": DERIVATIVE_MODIFIED_AT,
            "last_verified_at": VERIFIED_AT,
            "verification_scope": "provider-readback",
            "access_state": "verified",
            "trashed": False,
        },
        "duplicates": {"candidates": [], "selected_candidate_ref": None},
        "lineage": {
            "revisions": [
                {
                    "revision_id": "revision-1377-avatar-sanitization",
                    "predecessor_ref": source_identity["stable_ref"],
                    "operation": "revise-existing",
                    "trigger": "privacy sanitization of account avatar region",
                    "changed_sections": ["account-avatar-region"],
                    "preserved_sections": ["interface-identity", "tool-identity", "visible-ui-claims"],
                    "resulting_file_ref": derivative_identity["stable_ref"],
                    "reviewer_owner": "repository-owner",
                    "timestamp": DERIVATIVE_MODIFIED_AT,
                    "rollback_kind": "retained-prior-file",
                    "rollback_ref": source_identity["stable_ref"],
                    "rollback_verified": True,
                }
            ],
            "predecessor_ref": source_identity["stable_ref"],
            "successor_ref": derivative_identity["stable_ref"],
            "supersession_reason": None,
        },
        "statuses": {
            "quality_state": "pass",
            "teacher_approval": "approved",
            "classroom_readiness": "ready",
            "production_state": "not-authorized",
            "publication_state": "not-published",
            "sharing_state": "unknown",
        },
        "quality_rows": [
            {"row_id": "quality-1377-privacy-sanitization", "state": "pass", "reason_codes": []}
        ],
        "assets": [
            {
                "asset_id": derivative_identity["asset_id"],
                "stable_ref": derivative_identity["stable_ref"],
                "content_fingerprint": DERIVATIVE_SHA256,
                "perceptual_match_evidence": "bounded deterministic avatar-region replacement; 880 changed pixels; zero outside mask",
                "duplicate_group_id": None,
                "duplicate_relationship": "unique",
                "disposition": "canonical",
                "canonical_asset_ref": None,
                "comparison_evidence": "exact Drive identity, SHA-256, and deterministic sanitization evidence on issue 1377",
                "confidence": 1.0,
                "rights_classification": "cleared-internal",
                "rights_basis": "internal-evidence",
                "warning_signals": ["brand"],
                "privacy_observations": ["profiles", "account-details"],
                "privacy_mitigation": "anonymize",
                "privacy_resolved": True,
                "residual_privacy_risk": False,
                "content_findings": [],
                "repair_source_status": "completed",
                "direct_use_status": "student-ready",
                "correction_requirement": None,
                "replacement_required": False,
                "transformations": ["replace"],
                "required_context_flags": ["interface-identity", "tool-identity"],
                "preserved_context_flags": ["interface-identity", "tool-identity"],
                "context_preservation_complete": True,
            }
        ],
        "references": [
            {
                "reference_id": "source-review-1377",
                "kind": "source-evidence",
                "stable_ref": source_identity["stable_ref"],
                "fingerprint": SOURCE_SHA256,
            },
            {
                "reference_id": "sanitization-review-1377",
                "kind": "sanitization-evidence",
                "stable_ref": derivative_identity["stable_ref"],
                "fingerprint": DERIVATIVE_SHA256,
            },
        ],
        "authority": {
            "execution_authorized": False,
            "external_write_authorized": False,
            "production_authorized": False,
            "publication_authorized": False,
            "side_effects_performed": False,
        },
    }

    compatibility = {
        "library_record": {
            "page_id": LIBRARY_PAGE_ID,
            "page_url": "https://www.notion.so/3c67ac78313181dabb80e256a36fd3de",
            "drive_file_id": DERIVATIVE_FILE_ID,
            "drive_url": f"https://drive.google.com/file/d/{DERIVATIVE_FILE_ID}/view",
            "asset_title": "2458E788-DDB7-4D2B-B707-DD760A18DB09_sanitized.png",
            "approved_use": "approved",
            "asset_type": "screen-capture",
            "human_review_status": "Done",
            "review_date": "2026-08-24",
            "extra_fields": {},
        },
        "compatibility_evidence": {
            "contract_version": "curriculum-visual-asset-compatibility-v2",
            "manifest_reference": {
                "manifest_id": MANIFEST_ID,
                "record_revision": 1,
                "fingerprint": MANIFEST_FINGERPRINT,
                "verified_at": VERIFIED_AT,
                "external_file_id": DERIVATIVE_FILE_ID,
            },
            "asset_reference": {
                "asset_id": derivative_identity["asset_id"],
                "stable_ref": derivative_identity["stable_ref"],
                "content_fingerprint": DERIVATIVE_SHA256,
            },
            "library_reference": {"page_id": LIBRARY_PAGE_ID, "drive_file_id": DERIVATIVE_FILE_ID},
            "purpose": {"role_types": ["navigation-orientation"], "decorative_only": False},
            "accessibility": {
                "review_state": "pass",
                "description_state": "alt-text-present",
                "description_reference": "visual-library-alt-text-1377",
            },
            "orientation": {"orientation": "wide", "aspect_state": "flexible"},
            "approved_use": {
                "state": "approved",
                "role_types": ["navigation-orientation"],
                "material_types": ["internal-instructional-material"],
            },
            "freshness": {
                "manifest_record_revision": 1,
                "manifest_fingerprint": MANIFEST_FINGERPRINT,
                "manifest_verified_at": VERIFIED_AT,
                "compatibility_verified_at": VERIFIED_AT,
                "stale": False,
            },
            "cohesion_profile": {
                "visual_style_family": "interface",
                "medium": "screen-capture",
                "representation_class": "interface-capture",
                "palette_family": "full-color",
                "line_treatment": "none",
                "rendering_style": "realistic",
                "perspective": "front",
                "background_treatment": "interface",
                "complexity_rating": 2,
                "cognitive_load_rating": 2,
                "audience_compatibility": {
                    "state": "approved",
                    "reviewer_ref": "repository-owner",
                    "reviewed_at": "2026-08-24T00:00:00Z",
                    "evidence_reference": "github-issue-1377-owner-attestation-5401752531",
                    "stale": False,
                    "contradictory": False,
                },
            },
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "production_authorized": False,
                "publication_authorized": False,
                "side_effects_performed": False,
            },
        },
    }
    return source_identity, derivative_identity, manifest, compatibility


def test_issue_1377_real_add_content_evidence_validates_to_eligible():
    source_identity, derivative_identity, manifest, compatibility = real_evidence()

    assert source_identity["content_fingerprint"] == SOURCE_SHA256
    assert derivative_identity["content_fingerprint"] == DERIVATIVE_SHA256
    assert source_identity["asset_id"] != derivative_identity["asset_id"]
    assert derivative_identity["lineage"]["predecessor_asset_id"] == source_identity["asset_id"]
    assert derivative_identity["lineage"]["predecessor_stable_ref"] == source_identity["stable_ref"]

    manifest_result = validate_standalone_artifact_manifest(manifest)
    assert manifest_result["status"] == "valid", manifest_result

    compatibility_result = validate_standalone_visual_asset_compatibility_evidence(manifest, compatibility)
    assert compatibility_result["status"] == "valid", compatibility_result
    assert compatibility_result["classification"] == "eligible"
    assert compatibility_result["matched_asset"]["asset_id"] == derivative_identity["asset_id"]
    assert compatibility_result["matched_asset"]["stable_ref"] == derivative_identity["stable_ref"]
