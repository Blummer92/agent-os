"""Governed visual-asset content identity (#3256).

Canonical contract for binding an approved, selected, or placed visual asset to
the exact bytes that were reviewed. Lane D owns this contract; Lane A (#3252)
consumes it for persistence, continuation, and idempotency.

Identity model
--------------
A content identity is a small mapping::

    {
        "contract_version": "governed-asset-content-identity-v1",
        "source": "drive-sha256" | "drive-md5" | "drive-head-revision" | "local-hash",
        "algorithm": "sha256" | "md5" | "drive-revision",
        "value": "<hex digest or Drive revision id>",
    }

Canonical precedence (D7 decision): Drive ``sha256Checksum`` is preferred;
when absent, fall back to ``md5Checksum``, then ``headRevisionId``, then a
locally computed SHA-256 over bytes the caller holds. The precedence is fixed
so every consumer derives the same identity from the same metadata.

Recording: the identity is recorded in the repository manifest and in governed
evidence. No Notion governed field exists for it and no Drive/Notion writes are
performed by this contract.

Verification outcomes (all explicit, never absence)
--------------------------------------------------
- ``content-identity-match``: expected and current identities agree.
- ``content-identity-mismatch``: comparable identities disagree. Fails closed
  per asset. A mismatch is never absence and never authorizes a generation
  handoff.
- ``content-identity-unverifiable``: the current metadata carries no usable
  identity fields, or the expected/current algorithms are incomparable. Fails
  closed per asset as a distinct non-absence state.
- ``content-identity-not-recorded``: no expected identity was supplied.
  Callers that choose to verify treat this as a pass-through; callers that
  require binding treat it as a failure.

Drive lookup outcomes are classified separately (see
``instructional_materials_coach.drive_client``): ``not-found`` (deleted),
``no-access`` (permission gap), and ``lookup-failed`` are distinct from any
content outcome.

Revision semantics
-----------------
A legitimate provider revision advances the content identity (new hash and/or
new ``headRevisionId``) while the logical asset identity (``asset_id`` /
``stable_ref`` from ``reusable_visual_identity``) is unchanged. Consumers must
treat a changed content identity as a *different selected content*, never as
the same bytes. Drift detection is therefore: re-derive the current identity
from live metadata and compare it to the recorded one.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

CONTENT_IDENTITY_CONTRACT_ID = "governed-asset-content-identity-v1"

SOURCE_DRIVE_SHA256 = "drive-sha256"
SOURCE_DRIVE_MD5 = "drive-md5"
SOURCE_DRIVE_HEAD_REVISION = "drive-head-revision"
SOURCE_LOCAL_HASH = "local-hash"

#: Canonical precedence, highest first (D7 decision).
SOURCE_PRECEDENCE = (
    SOURCE_DRIVE_SHA256,
    SOURCE_DRIVE_MD5,
    SOURCE_DRIVE_HEAD_REVISION,
    SOURCE_LOCAL_HASH,
)

OUTCOME_MATCH = "content-identity-match"
OUTCOME_MISMATCH = "content-identity-mismatch"
OUTCOME_UNVERIFIABLE = "content-identity-unverifiable"
OUTCOME_NOT_RECORDED = "content-identity-not-recorded"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MD5_RE = re.compile(r"^[0-9a-f]{32}$")


def _identity(source: str, algorithm: str, value: str) -> dict[str, Any]:
    return {
        "contract_version": CONTENT_IDENTITY_CONTRACT_ID,
        "source": source,
        "algorithm": algorithm,
        "value": value,
    }


def is_valid_content_identity(value: object) -> bool:
    """Return True when ``value`` is a well-formed content identity mapping."""
    if not isinstance(value, Mapping):
        return False
    if value.get("contract_version") != CONTENT_IDENTITY_CONTRACT_ID:
        return False
    source = value.get("source")
    algorithm = value.get("algorithm")
    digest = value.get("value")
    if source == SOURCE_DRIVE_SHA256 or source == SOURCE_LOCAL_HASH:
        return algorithm == "sha256" and isinstance(digest, str) and bool(_SHA256_RE.fullmatch(digest))
    if source == SOURCE_DRIVE_MD5:
        return algorithm == "md5" and isinstance(digest, str) and bool(_MD5_RE.fullmatch(digest))
    if source == SOURCE_DRIVE_HEAD_REVISION:
        return (
            algorithm == "drive-revision"
            and isinstance(digest, str)
            and bool(digest.strip())
            and len(digest) <= 256
        )
    return False


def select_content_identity(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Derive the canonical content identity from Drive file metadata.

    Applies the fixed precedence: ``sha256Checksum`` > ``md5Checksum`` >
    ``headRevisionId``. Returns None when the metadata carries no usable
    identity field.
    """
    if not isinstance(metadata, Mapping):
        return None
    sha256 = metadata.get("sha256Checksum")
    if isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256):
        return _identity(SOURCE_DRIVE_SHA256, "sha256", sha256)
    # Drive may return uppercase hex; normalize to lowercase canonical form.
    if isinstance(sha256, str) and _SHA256_RE.fullmatch(sha256.lower()):
        return _identity(SOURCE_DRIVE_SHA256, "sha256", sha256.lower())
    md5 = metadata.get("md5Checksum")
    if isinstance(md5, str) and _MD5_RE.fullmatch(md5.lower()):
        return _identity(SOURCE_DRIVE_MD5, "md5", md5.lower())
    revision = metadata.get("headRevisionId")
    if isinstance(revision, str) and revision.strip() and len(revision) <= 256:
        return _identity(SOURCE_DRIVE_HEAD_REVISION, "drive-revision", revision)
    return None


def compute_local_content_identity(content: bytes) -> dict[str, Any]:
    """Compute the fallback content identity over locally held bytes.

    This is the last-resort precedence step, used only when Drive supplies no
    hash or revision. The caller performs the byte fetch; this function never
    touches the network.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("content must be bytes")
    return _identity(SOURCE_LOCAL_HASH, "sha256", hashlib.sha256(bytes(content)).hexdigest())


def content_identity_from_fingerprint(fingerprint: str) -> dict[str, Any]:
    """Build an expected identity from a recorded SHA-256 content fingerprint.

    Manifest and compatibility evidence record the approved bytes as a SHA-256
    ``content_fingerprint``; this lifts it into the canonical identity shape so
    selection, slot resolution, and placement verify against the same model.
    """
    if not isinstance(fingerprint, str) or not _SHA256_RE.fullmatch(fingerprint):
        raise ValueError("content fingerprint must be lowercase SHA-256")
    return _identity(SOURCE_DRIVE_SHA256, "sha256", fingerprint)


def _comparable(expected: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Two identities are comparable only when their algorithms can be equated."""
    if expected.get("algorithm") == current.get("algorithm"):
        return True
    # A locally computed SHA-256 and Drive's SHA-256 are the same measurement.
    sha_sources = {SOURCE_DRIVE_SHA256, SOURCE_LOCAL_HASH}
    return (
        expected.get("algorithm") == "sha256"
        and current.get("algorithm") == "sha256"
        and expected.get("source") in sha_sources
        and current.get("source") in sha_sources
    )


def verify_content_identity(
    *,
    expected: Mapping[str, Any] | None,
    metadata: Mapping[str, Any],
) -> str:
    """Verify an expected content identity against current Drive metadata.

    Returns one of ``content-identity-match``, ``content-identity-mismatch``,
    ``content-identity-unverifiable``, or ``content-identity-not-recorded``.
    Never raises for malformed input: malformed evidence is unverifiable, not
    a match.
    """
    if expected is None:
        return OUTCOME_NOT_RECORDED
    if not is_valid_content_identity(expected):
        return OUTCOME_UNVERIFIABLE
    current = select_content_identity(metadata)
    if current is None:
        return OUTCOME_UNVERIFIABLE
    if not _comparable(expected, current):
        return OUTCOME_UNVERIFIABLE
    if expected["value"] == current["value"]:
        return OUTCOME_MATCH
    return OUTCOME_MISMATCH


def identity_evidence_for_drive_file(
    *,
    metadata: Mapping[str, Any],
    provenance: Mapping[str, Any],
    lineage: Mapping[str, Any],
    existing_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build ``issue_reusable_visual_identity`` evidence from Drive metadata.

    Captures the content identity at ingestion/approval time using the canonical
    precedence. Only SHA-256 identities can mint v1 reusable-visual identity
    (the issuance contract requires a SHA-256 content fingerprint); when Drive
    yields only an md5 or revision, this raises instead of minting a weaker
    binding.

    ``provenance`` must carry ``source_reference``/``source_fingerprint``/
    ``evidence_reference``; ``lineage`` follows the reusable-visual identity
    contract. No external writes are performed.
    """
    identity = select_content_identity(metadata)
    if identity is None or identity["algorithm"] != "sha256":
        raise ValueError(
            "cannot mint reusable-visual identity: Drive metadata carries no SHA-256 "
            "content hash (sha256Checksum or local-hash required)"
        )
    external = metadata.get("id")
    web_link = metadata.get("webViewLink")
    evidence: dict[str, Any] = {
        "contract_version": "governed-reusable-visual-identity-v1",
        "external_identity": {
            "provider": "google-drive",
            "file_id": external,
            "exact_reference": web_link if isinstance(web_link, str) and web_link else f"drive:{external}",
            "verified": True,
        },
        "content_fingerprint": identity["value"],
        "provenance": dict(provenance),
        "lineage": dict(lineage),
    }
    if existing_identity is not None:
        evidence["existing_identity"] = existing_identity
    return evidence
