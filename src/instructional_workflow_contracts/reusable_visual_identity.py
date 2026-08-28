"""Governed reusable-visual identity and standalone manifest helpers (#1387)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .artifact_manifest import (
    _assets as _manifest_assets,
    _authority as _manifest_authority,
    _external as _manifest_external,
    _lineage as _manifest_lineage,
    _quality_rows as _manifest_quality_rows,
    _references as _manifest_references,
    _statuses as _manifest_statuses,
)
from .common import ContractValidationError, ValidationStatus
from .visual_asset_compatibility import (
    V2_CONTRACT_ID,
    _accessibility,
    _approved_use,
    _authority as _compatibility_authority,
    _bind_freshness,
    _bind_library_reference,
    _classification,
    _cohesion_profile,
    _freshness,
    _library_record,
    _match_asset,
    _orientation,
    _purpose,
)

IDENTITY_CONTRACT_ID = "governed-reusable-visual-identity-v1"
STANDALONE_MANIFEST_CONTRACT_ID = "curriculum-artifact-manifest-v2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LINEAGE_KINDS = {"original", "sanitized-derivative", "rendition", "superseding-version"}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _fail(reason: str, detail: str, *, status: str = "manual-review-required") -> dict[str, Any]:
    return {"status": status, "reason_codes": [reason], "detail": detail}


def issue_reusable_visual_identity(value: object) -> dict[str, Any]:
    """Issue or reconcile canonical identity from governed exact identity evidence."""
    if type(value) is not dict:
        return _fail("identity.wrong-type", "identity evidence must be a mapping")
    allowed = {
        "contract_version", "external_identity", "content_fingerprint", "provenance",
        "lineage", "existing_identity",
    }
    if set(value) - allowed:
        return _fail("identity.untrusted-fields", "identity evidence contains unsupported fields")
    if value.get("contract_version") != IDENTITY_CONTRACT_ID:
        return _fail("identity.contract-version", "unsupported identity contract version")
    external = value.get("external_identity")
    provenance = value.get("provenance")
    lineage = value.get("lineage")
    fingerprint = value.get("content_fingerprint")
    if type(external) is not dict or type(provenance) is not dict or type(lineage) is not dict:
        return _fail("identity.evidence-incomplete", "external identity, provenance, and lineage are required")
    if type(fingerprint) is not str or not SHA256_RE.fullmatch(fingerprint):
        return _fail("identity.content-fingerprint", "content fingerprint must be lowercase SHA-256")
    required_external = ("provider", "file_id", "exact_reference", "verified")
    if any(key not in external for key in required_external) or external.get("verified") is not True:
        return _fail("identity.external-unverified", "exact verified external identity is required")
    if any(type(external.get(key)) is not str or not external.get(key) for key in ("provider", "file_id", "exact_reference")):
        return _fail("identity.external-invalid", "external provider/file/reference must be non-empty strings")
    required_provenance = ("source_reference", "source_fingerprint", "evidence_reference")
    if any(type(provenance.get(key)) is not str or not provenance.get(key) for key in required_provenance):
        return _fail("identity.provenance-incomplete", "exact source provenance is required")
    kind = lineage.get("kind")
    if kind not in LINEAGE_KINDS:
        return _fail("identity.lineage-kind", "unsupported lineage kind")
    predecessor_asset_id = lineage.get("predecessor_asset_id")
    predecessor_stable_ref = lineage.get("predecessor_stable_ref")
    if kind == "original":
        if predecessor_asset_id is not None or predecessor_stable_ref is not None:
            return _fail("identity.lineage-conflict", "original identity cannot have a predecessor")
    elif not (type(predecessor_asset_id) is str and predecessor_asset_id and type(predecessor_stable_ref) is str and predecessor_stable_ref):
        return _fail("identity.predecessor-required", "derivative/rendition identity requires exact predecessor identity")

    basis = {
        "contract_version": IDENTITY_CONTRACT_ID,
        "external_identity": {key: external.get(key) for key in ("provider", "file_id", "exact_reference")},
        "content_fingerprint": fingerprint,
        "provenance": {key: provenance.get(key) for key in required_provenance},
        "lineage": {
            "kind": kind,
            "predecessor_asset_id": predecessor_asset_id,
            "predecessor_stable_ref": predecessor_stable_ref,
        },
    }
    digest = hashlib.sha256(_canonical(basis)).hexdigest()
    asset_id = f"visual-asset-{digest[:24]}"
    stable_ref = f"visual-ref-{digest}"
    if asset_id == external["file_id"] or stable_ref in {external["file_id"], external["exact_reference"]}:
        return _fail("identity.external-alias", "canonical identity cannot alias external identity")

    existing = value.get("existing_identity")
    revision = 1
    if existing is not None:
        if type(existing) is not dict:
            return _fail("identity.existing-wrong-type", "existing identity must be a mapping")
        expected = (existing.get("asset_id"), existing.get("stable_ref"))
        if expected != (asset_id, stable_ref):
            return _fail("identity.conflict", "existing canonical identity conflicts with governed evidence")
        if existing.get("basis_fingerprint") != digest:
            return _fail("identity.binding-conflict", "existing identity basis fingerprint conflicts")
        revision_value = existing.get("record_revision", 1)
        if type(revision_value) is not int or revision_value < 1:
            return _fail("identity.revision-invalid", "existing record revision is invalid")
        revision = revision_value

    return {
        "status": "valid",
        "reason_codes": [],
        "identity": {
            "contract_version": IDENTITY_CONTRACT_ID,
            "asset_id": asset_id,
            "stable_ref": stable_ref,
            "basis_fingerprint": digest,
            "content_fingerprint": fingerprint,
            "record_revision": revision,
            "external_file_id": external["file_id"],
            "external_exact_reference": external["exact_reference"],
            "lineage": basis["lineage"],
        },
    }


def _standalone_operation(identity: dict[str, Any]) -> dict[str, Any]:
    """Project identity lineage into the existing lifecycle validator's operation shape."""
    kind = identity["lineage"]["kind"]
    operation_kind = "discover-existing" if kind == "original" else "revise-existing"
    return {
        "kind": operation_kind,
        "idempotency_key": "0" * 64,
        "approved_request_id": None,
        "approved_scope": "standalone-reusable-visual" if operation_kind == "revise-existing" else None,
        "current_file_ref": identity["lineage"].get("predecessor_stable_ref"),
        "template_ref": None,
        "template_permission_state": None,
        "discovery_evidence": ["governed reusable-visual identity evidence"],
    }


def validate_standalone_artifact_manifest(value: object) -> dict[str, Any]:
    """Validate additive standalone ArtifactManifest v2 while preserving v1 evidence semantics."""
    if type(value) is not dict:
        return _fail("manifest.wrong-type", "manifest must be a mapping")
    expected = {
        "contract_version", "subject", "identity_evidence", "artifact", "external_identity",
        "duplicates", "lineage", "statuses", "quality_rows", "assets", "references", "authority",
        "identity",
    }
    if set(value) != expected:
        return _fail("manifest.fields", "standalone manifest fields must be exact")
    if value.get("contract_version") != STANDALONE_MANIFEST_CONTRACT_ID:
        return _fail("manifest.contract-version", "standalone manifest requires v2")
    if value.get("subject") != "standalone-reusable-visual":
        return _fail("manifest.subject", "unsupported standalone manifest subject")
    identity_result = issue_reusable_visual_identity(value.get("identity_evidence"))
    if identity_result.get("status") != "valid":
        return identity_result
    identity = identity_result["identity"]
    try:
        manifest_identity = value["identity"]
        if type(manifest_identity) is not dict or set(manifest_identity) != {"manifest_id", "record_revision", "verified_at", "fingerprint"}:
            return _fail("manifest.identity", "standalone manifest identity fields must be exact")
        if type(manifest_identity["manifest_id"]) is not str or not manifest_identity["manifest_id"]:
            return _fail("manifest.identity", "manifest_id is required")
        if type(manifest_identity["record_revision"]) is not int or manifest_identity["record_revision"] < 1:
            return _fail("manifest.identity", "manifest record_revision must be positive")
        if type(manifest_identity["verified_at"]) is not str or not manifest_identity["verified_at"]:
            return _fail("manifest.identity", "manifest verified_at is required")
        if type(manifest_identity["fingerprint"]) is not str or not SHA256_RE.fullmatch(manifest_identity["fingerprint"]):
            return _fail("manifest.identity", "manifest fingerprint must be lowercase SHA-256")

        if type(value["artifact"]) is not dict or set(value["artifact"]) != {"artifact_type", "mime_type"}:
            return _fail("manifest.artifact", "artifact fields must be exact")
        external = value["external_identity"]
        statuses = value["statuses"]
        assets = value["assets"]
        quality_rows = value["quality_rows"]
        references = value["references"]
        duplicates = value["duplicates"]
        lineage = value["lineage"]
        authority = value["authority"]
        if not all(type(group) is dict for group in (external, statuses, duplicates, lineage, authority)):
            return _fail("manifest.evidence-incomplete", "standalone manifest groups are incomplete")
        if type(assets) is not list or type(quality_rows) is not list or type(references) is not list:
            return _fail("manifest.evidence-incomplete", "standalone manifest collections are incomplete")

        _manifest_external(external)
        operation = _standalone_operation(identity)
        manual = _manifest_lineage(lineage, operation)
        _manifest_statuses(statuses, external)
        _manifest_quality_rows(quality_rows, statuses)
        manual |= _manifest_assets(assets, statuses)
        _manifest_references(references)
        _manifest_authority(authority)

        if type(duplicates) is not dict or set(duplicates) != {"candidates", "selected_candidate_ref"}:
            return _fail("manifest.duplicates", "standalone duplicate evidence fields must be exact")
        if type(duplicates["candidates"]) is not list:
            return _fail("manifest.duplicates", "standalone duplicate candidates must be a list")
        if duplicates["selected_candidate_ref"] is not None and type(duplicates["selected_candidate_ref"]) is not str:
            return _fail("manifest.duplicates", "selected duplicate candidate must be a string or null")

        exact_assets = [
            asset for asset in assets
            if asset.get("asset_id") == identity["asset_id"]
            and asset.get("stable_ref") == identity["stable_ref"]
            and asset.get("content_fingerprint") == identity["content_fingerprint"]
        ]
        if len(exact_assets) != 1:
            return _fail("manifest.asset-identity-mismatch", "standalone manifest must contain exactly one exact governed asset")
        if external.get("file_id") != identity["external_file_id"] or external.get("exact_reference") != identity["external_exact_reference"]:
            return _fail("manifest.external-identity-mismatch", "Drive/external identity must match issuance evidence exactly")
        if statuses.get("classroom_readiness") != "ready":
            manual.add("readiness-classroom-manual-review")
        if manual:
            return {
                "status": "manual-review-required",
                "reason_codes": sorted(manual),
                "identity": identity,
                "manifest": value,
            }
        return {"status": "valid", "reason_codes": [], "identity": identity, "manifest": value}
    except ContractValidationError as exc:
        return _fail(exc.reason_code, exc.detail, status="invalid")


def validate_standalone_visual_asset_compatibility_evidence(manifest: object, compatibility: object) -> dict[str, Any]:
    """Run standalone manifests through the existing governed compatibility-v2 gates."""
    manifest_result = validate_standalone_artifact_manifest(manifest)
    if manifest_result.get("status") != "valid":
        return manifest_result
    if type(compatibility) is not dict or set(compatibility) != {"library_record", "compatibility_evidence"}:
        return _fail("compatibility.fields", "standalone compatibility envelope fields must be exact")
    try:
        library = _library_record(compatibility["library_record"])
        evidence = compatibility["compatibility_evidence"]
        if type(evidence) is not dict:
            return _fail("compatibility.wrong-type", "compatibility evidence must be a mapping")
        expected = {
            "contract_version", "manifest_reference", "asset_reference", "library_reference",
            "purpose", "accessibility", "orientation", "approved_use", "freshness",
            "cohesion_profile", "authority",
        }
        if set(evidence) != expected:
            return _fail("compatibility.fields", "compatibility-v2 evidence fields must be exact")
        if evidence["contract_version"] != V2_CONTRACT_ID:
            return _fail("compatibility.contract-version", "compatibility v2 is required")

        manifest_payload = manifest_result["manifest"]
        manifest_identity = manifest_payload["identity"]
        manifest_record = _StandaloneManifestRecord(manifest_payload)
        manifest_reference = evidence["manifest_reference"]
        asset_reference = evidence["asset_reference"]
        library_reference = evidence["library_reference"]
        if type(manifest_reference) is not dict or set(manifest_reference) != {"manifest_id", "record_revision", "fingerprint", "verified_at", "external_file_id"}:
            return _fail("compatibility.manifest-reference", "manifest reference fields must be exact")
        if type(asset_reference) is not dict or set(asset_reference) != {"asset_id", "stable_ref", "content_fingerprint"}:
            return _fail("compatibility.asset-reference", "asset reference fields must be exact")
        if type(library_reference) is not dict or set(library_reference) != {"page_id", "drive_file_id"}:
            return _fail("compatibility.library-reference", "library reference fields must be exact")

        purpose = _purpose(evidence["purpose"])
        accessibility = _accessibility(evidence["accessibility"])
        orientation = _orientation(evidence["orientation"])
        approved_use = _approved_use(evidence["approved_use"])
        freshness = _freshness(evidence["freshness"])
        cohesion_profile = _cohesion_profile(evidence["cohesion_profile"])
        _compatibility_authority(evidence["authority"])

        if manifest_reference["manifest_id"] != manifest_record.record_id:
            return _fail("identity-invalid", "manifest reference ID does not match standalone manifest")
        if manifest_reference["record_revision"] != manifest_record.record_revision:
            return _fail("identity-invalid", "manifest reference revision does not match standalone manifest")
        if manifest_reference["fingerprint"] != manifest_record.fingerprint:
            return _fail("identity-invalid", "manifest reference fingerprint does not match standalone manifest")
        if manifest_reference["verified_at"] != manifest_payload["identity"]["verified_at"]:
            return _fail("identity-invalid", "manifest verification timestamp is contradictory")
        if manifest_reference["external_file_id"] != manifest_payload["external_identity"]["file_id"]:
            return _fail("identity-invalid", "manifest external file identity is contradictory")

        _bind_freshness(freshness, manifest_record, manifest_payload)
        _bind_library_reference(library_reference, library, manifest_payload)
        matched_asset = _match_asset(asset_reference, manifest_payload, include_projection_metadata=True)
        classification, reasons = _classification(
            matched_asset=matched_asset,
            purpose=purpose,
            accessibility=accessibility,
            orientation=orientation,
            approved_use=approved_use,
            freshness=freshness,
            cohesion_profile=cohesion_profile,
        )
        if classification == "hard-rejection":
            return {"status": "hard-rejection", "reason_codes": list(reasons)}
        if classification == "manual-review-required":
            return {"status": "manual-review-required", "reason_codes": list(reasons)}
        return {
            "status": "valid",
            "reason_codes": [],
            "identity": manifest_result["identity"],
            "classification": classification,
            "matched_asset": matched_asset,
        }
    except ContractValidationError as exc:
        return _fail(exc.reason_code, exc.detail, status="invalid")


class _StandaloneManifestRecord:
    """Minimal adapter satisfying compatibility binding helpers without fabricating v1."""

    def __init__(self, manifest: dict[str, Any]) -> None:
        self.record_id = manifest["identity"]["manifest_id"]
        self.record_revision = manifest["identity"]["record_revision"]
        self.fingerprint = manifest["identity"]["fingerprint"]
