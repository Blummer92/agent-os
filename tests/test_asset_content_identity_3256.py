"""Focused tests for the #3256 asset content identity contract (Lane D)."""
import pytest

from instructional_workflow_contracts.asset_content_identity import (
    CONTENT_IDENTITY_CONTRACT_ID,
    OUTCOME_MATCH,
    OUTCOME_MISMATCH,
    OUTCOME_NOT_RECORDED,
    OUTCOME_UNVERIFIABLE,
    compute_local_content_identity,
    content_identity_from_fingerprint,
    identity_evidence_for_drive_file,
    is_valid_content_identity,
    select_content_identity,
    verify_content_identity,
)
from instructional_workflow_contracts.reusable_visual_identity import (
    IDENTITY_CONTRACT_ID,
    issue_reusable_visual_identity,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _metadata(**overrides):
    meta = {"id": "drive-file-1", "trashed": False}
    meta.update(overrides)
    return meta


# --- precedence -----------------------------------------------------------

def test_sha256_checksum_wins_precedence():
    identity = select_content_identity(_metadata(sha256Checksum=SHA_A, md5Checksum="c" * 32, headRevisionId="rev-9"))
    assert identity["source"] == "drive-sha256"
    assert identity["algorithm"] == "sha256"
    assert identity["value"] == SHA_A
    assert identity["contract_version"] == CONTENT_IDENTITY_CONTRACT_ID


def test_md5_is_fallback_when_sha256_absent():
    identity = select_content_identity(_metadata(md5Checksum="c" * 32, headRevisionId="rev-9"))
    assert (identity["source"], identity["algorithm"], identity["value"]) == ("drive-md5", "md5", "c" * 32)


def test_head_revision_id_is_last_resort():
    identity = select_content_identity(_metadata(headRevisionId="rev-9"))
    assert (identity["source"], identity["algorithm"], identity["value"]) == ("drive-head-revision", "drive-revision", "rev-9")


def test_no_identity_fields_returns_none():
    assert select_content_identity(_metadata(name="icon.png")) is None
    assert select_content_identity({}) is None


def test_local_hash_computes_sha256():
    identity = compute_local_content_identity(b"bytes")
    assert identity["source"] == "local-hash"
    assert identity["algorithm"] == "sha256"
    assert len(identity["value"]) == 64
    assert compute_local_content_identity(b"bytes") == compute_local_content_identity(b"bytes")
    assert compute_local_content_identity(b"bytes")["value"] != compute_local_content_identity(b"other")["value"]


# --- verification ----------------------------------------------------------

def test_match_when_hashes_agree():
    expected = content_identity_from_fingerprint(SHA_A)
    assert verify_content_identity(expected=expected, metadata=_metadata(sha256Checksum=SHA_A)) == OUTCOME_MATCH


def test_modified_after_approval_is_mismatch():
    # The approved bytes were SHA_A; Drive now serves SHA_B.
    expected = content_identity_from_fingerprint(SHA_A)
    outcome = verify_content_identity(expected=expected, metadata=_metadata(sha256Checksum=SHA_B))
    assert outcome == OUTCOME_MISMATCH


def test_revision_advance_is_mismatch():
    expected = {"contract_version": CONTENT_IDENTITY_CONTRACT_ID, "source": "drive-head-revision",
                "algorithm": "drive-revision", "value": "rev-1"}
    outcome = verify_content_identity(expected=expected, metadata=_metadata(headRevisionId="rev-2"))
    assert outcome == OUTCOME_MISMATCH


def test_missing_hash_fields_is_unverifiable_not_absence():
    expected = content_identity_from_fingerprint(SHA_A)
    outcome = verify_content_identity(expected=expected, metadata=_metadata(name="icon.png"))
    assert outcome == OUTCOME_UNVERIFIABLE


def test_incomparable_algorithms_are_unverifiable():
    expected = {"contract_version": CONTENT_IDENTITY_CONTRACT_ID, "source": "drive-md5",
                "algorithm": "md5", "value": "c" * 32}
    outcome = verify_content_identity(expected=expected, metadata=_metadata(sha256Checksum=SHA_A))
    assert outcome == OUTCOME_UNVERIFIABLE


def test_no_expected_identity_is_not_recorded():
    assert verify_content_identity(expected=None, metadata=_metadata(sha256Checksum=SHA_A)) == OUTCOME_NOT_RECORDED


def test_malformed_expected_identity_is_unverifiable():
    assert verify_content_identity(expected={"bogus": True}, metadata=_metadata(sha256Checksum=SHA_A)) == OUTCOME_UNVERIFIABLE


def test_local_hash_and_drive_sha256_are_comparable():
    expected = compute_local_content_identity(b"bytes")
    import hashlib
    digest = hashlib.sha256(b"bytes").hexdigest()
    assert verify_content_identity(expected=expected, metadata=_metadata(sha256Checksum=digest)) == OUTCOME_MATCH


# --- identity evidence capture ---------------------------------------------

def _provenance():
    return {"source_reference": "source-1", "source_fingerprint": "fp-1", "evidence_reference": "review-1"}


def _lineage():
    return {"kind": "original", "predecessor_asset_id": None, "predecessor_stable_ref": None}


def test_evidence_builder_captures_sha256_from_drive_metadata():
    evidence = identity_evidence_for_drive_file(
        metadata=_metadata(sha256Checksum=SHA_A, webViewLink="https://drive.example/f1"),
        provenance=_provenance(),
        lineage=_lineage(),
    )
    assert evidence["contract_version"] == IDENTITY_CONTRACT_ID
    assert evidence["content_fingerprint"] == SHA_A
    assert evidence["external_identity"]["file_id"] == "drive-file-1"
    result = issue_reusable_visual_identity(evidence)
    assert result["status"] == "valid"


def test_evidence_builder_refuses_without_sha256():
    with pytest.raises(ValueError, match="no SHA-256"):
        identity_evidence_for_drive_file(
            metadata=_metadata(md5Checksum="c" * 32),
            provenance=_provenance(),
            lineage=_lineage(),
        )


# --- identity basis stability (#3256 root cause) ----------------------------

def _identity_evidence(*, file_id="drive-file-1", fingerprint=SHA_A, exact_reference="https://drive.example/f1", evidence_reference="review-1", existing_identity=None):
    value = {
        "contract_version": IDENTITY_CONTRACT_ID,
        "external_identity": {"provider": "google-drive", "file_id": file_id, "exact_reference": exact_reference, "verified": True},
        "content_fingerprint": fingerprint,
        "provenance": {"source_reference": "source-1", "source_fingerprint": "fp-1", "evidence_reference": evidence_reference},
        "lineage": {"kind": "original", "predecessor_asset_id": None, "predecessor_stable_ref": None},
    }
    if existing_identity is not None:
        value["existing_identity"] = existing_identity
    return value


def test_resync_through_different_reference_preserves_identity():
    first = issue_reusable_visual_identity(_identity_evidence())["identity"]
    assert first is not None
    # Same bytes, same Drive file, re-synced through a different URL and
    # evidence reference: the logical identity must be stable.
    second = issue_reusable_visual_identity(_identity_evidence(
        exact_reference="https://drive.example/changed-url",
        evidence_reference="review-2",
    ))["identity"]
    assert second["asset_id"] == first["asset_id"]
    assert second["stable_ref"] == first["stable_ref"]
    assert second["basis_fingerprint"] == first["basis_fingerprint"]


def test_resync_with_existing_identity_reconciles_without_conflict():
    issued = issue_reusable_visual_identity(_identity_evidence())["identity"]
    result = issue_reusable_visual_identity(_identity_evidence(
        exact_reference="https://drive.example/other",
        evidence_reference="review-9",
        existing_identity=issued,
    ))
    assert result["status"] == "valid"
    assert "identity.conflict" not in result.get("reason_codes", [])


def test_changed_bytes_still_change_identity():
    first = issue_reusable_visual_identity(_identity_evidence())["identity"]
    second = issue_reusable_visual_identity(_identity_evidence(fingerprint=SHA_B))["identity"]
    # Logical identity is preserved across content revisions; the content
    # fingerprint advances to distinguish the selected content.
    assert second["asset_id"] == first["asset_id"]
    assert second["stable_ref"] == first["stable_ref"]
    assert second["content_fingerprint"] != first["content_fingerprint"]


def test_mutable_references_remain_reported_but_outside_digest():
    issued = issue_reusable_visual_identity(_identity_evidence(
        exact_reference="https://drive.example/f1", evidence_reference="review-1"))["identity"]
    assert issued["external_exact_reference"] == "https://drive.example/f1"
    # The digest must not move when only the mutable references move.
    again = issue_reusable_visual_identity(_identity_evidence(
        exact_reference="https://drive.example/f2", evidence_reference="review-2"))["identity"]
    assert again["basis_fingerprint"] == issued["basis_fingerprint"]
