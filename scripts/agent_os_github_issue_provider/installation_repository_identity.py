"""Same-invocation installation-repository identity evidence (#555).

Implements the binding decision from #551
(``approve-same-invocation-installation-snapshot``): trusted numeric
repository identity is constructed only from the same invocation's bounded
``GET /installation/repositories`` response, obtained with the exact
installation token used for the issue-page request.

This module performs no network access, retry, caching, or persistence. It
validates an already-retrieved bounded snapshot and, on success, produces one
immutable evidence record plus a :class:`TrustedRepositoryIdentity` for the
existing :mod:`.provider` and :mod:`.pagination` primitives. The matching
rules mirror the same-invocation identity verification already proven in
:mod:`.sprint_evidence` (``_verify_repository_identity``): exact,
case-insensitive ``full_name`` match against exactly one entry, a positive
numeric ``id`` on that entry, and fail-closed on any duplicate or
case-colliding match.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from .models import TrustedRepositoryIdentity

INSTALLATION_REPOSITORY_IDENTITY_CONTRACT_VERSION = (
    "agent-os-installation-repository-identity/v1"
)

#: Endpoint-family identifier recorded in evidence instead of a raw URL.
SOURCE_ENDPOINT_FAMILY = "installation-repositories"

SUPPORTED_SELECTION_MODES = frozenset({"all", "selected"})

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

INSTALLATION_REPOSITORY_IDENTITY_REASON_CODES = frozenset(
    {
        "installation:mismatch",
        "pagination:ambiguous",
        "pagination:incomplete",
        "repository:absent",
        "repository:duplicate",
        "repository:id-invalid",
        "repository:name-invalid",
        "selection-mode:unsupported",
        "snapshot:malformed",
    }
)


class InstallationRepositoryIdentityError(ValueError):
    """Fail-closed rejection carrying one bounded, non-sensitive reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        if reason_code not in INSTALLATION_REPOSITORY_IDENTITY_REASON_CODES:
            raise ValueError("unknown installation repository identity reason code")
        super().__init__(message)
        self.reason_code = reason_code


def _reject(reason_code: str, message: str) -> None:
    raise InstallationRepositoryIdentityError(reason_code, message)


def _require_positive_int(value: object, *, reason_code: str, message: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        _reject(reason_code, message)
    return value  # type: ignore[return-value]


def _require_timestamp(value: object) -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        _reject("snapshot:malformed", "retrieved_at must be RFC3339 UTC")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        _reject("snapshot:malformed", "retrieved_at must be RFC3339 UTC")
        raise AssertionError("unreachable") from error  # pragma: no cover
    return value  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class InstallationRepositoryIdentityEvidence:
    """Immutable bounded same-invocation repository identity evidence.

    Contains only the normalized selected record and fixed provenance
    markers. Raw repository payloads, repository lists, headers, URLs,
    permissions payloads, installation tokens, JWTs, and credentials are
    never carried by this record.
    """

    contract_version: str
    installation_id: int
    repository_key: str
    full_name: str
    repository_id: int
    selection_mode: str
    retrieved_at: str
    source_endpoint_family: str
    evidence_digest: str
    same_invocation: bool = field(default=True, init=False)
    execution_authorized: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.contract_version != INSTALLATION_REPOSITORY_IDENTITY_CONTRACT_VERSION:
            raise ValueError(
                "unsupported installation repository identity contract version"
            )
        _require_positive_int(
            self.installation_id,
            reason_code="installation:mismatch",
            message="installation_id must be a positive integer",
        )
        if not _REPOSITORY_RE.fullmatch(self.repository_key):
            raise ValueError("repository_key must use lowercase owner/name form")
        if self.repository_key != self.repository_key.lower():
            raise ValueError("repository_key must be ASCII lowercase")
        if not _REPOSITORY_RE.fullmatch(self.full_name):
            raise ValueError("full_name must use owner/name form")
        if self.full_name.lower() != self.repository_key:
            raise ValueError("full_name must match repository_key case-insensitively")
        _require_positive_int(
            self.repository_id,
            reason_code="repository:id-invalid",
            message="repository_id must be a positive integer",
        )
        if self.selection_mode not in SUPPORTED_SELECTION_MODES:
            raise ValueError("selection_mode must be a supported selection mode")
        _require_timestamp(self.retrieved_at)
        if self.source_endpoint_family != SOURCE_ENDPOINT_FAMILY:
            raise ValueError("source_endpoint_family must be the installation-repositories family")
        if not isinstance(self.evidence_digest, str) or not self.evidence_digest:
            raise ValueError("evidence_digest is required")


def _evidence_digest(*, repository_key: str, full_name: str, repository_id: int) -> str:
    """Bounded digest derived only from the normalized selected record."""

    canonical = f"{repository_key}\n{full_name}\n{repository_id}".encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _entries(snapshot: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    raw_entries = snapshot.get("repositories")
    if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
        _reject("snapshot:malformed", "installation repositories snapshot is malformed")
    entries = [entry for entry in raw_entries if isinstance(entry, Mapping)]
    if len(entries) != len(raw_entries):
        _reject("snapshot:malformed", "installation repositories snapshot is malformed")
    return entries


def build_installation_repository_identity(
    *,
    installation_repositories_snapshot: Mapping[str, object],
    snapshot_complete: bool,
    snapshot_terminal_page_proven: bool,
    observed_installation_id: int,
    expected_installation_id: int,
    expected_repository: str,
    retrieved_at: str,
) -> InstallationRepositoryIdentityEvidence:
    """Construct immutable identity evidence from one same-invocation snapshot.

    ``installation_repositories_snapshot`` must be the complete JSON payload
    of exactly one same-invocation, bounded ``GET /installation/repositories``
    response (all pages merged by the caller under the existing pagination
    bounds). ``snapshot_complete`` and ``snapshot_terminal_page_proven`` must
    both be proven by that same bounded retrieval; an incomplete or
    pagination-ambiguous retrieval fails closed here rather than being
    silently accepted. ``observed_installation_id`` is the installation ID
    the same invocation's installation token was issued for;
    ``expected_installation_id`` is the invocation's configured installation
    ID. This function performs no network access, retry, caching, or
    persistence, and never reads a parser- or provider-owned endpoint.
    """

    if not isinstance(installation_repositories_snapshot, Mapping):
        _reject("snapshot:malformed", "installation repositories snapshot is malformed")
    if not snapshot_complete or not snapshot_terminal_page_proven:
        _reject(
            "pagination:incomplete",
            "installation repositories retrieval is incomplete or unproven",
        )

    _require_positive_int(
        observed_installation_id,
        reason_code="installation:mismatch",
        message="observed_installation_id must be a positive integer",
    )
    _require_positive_int(
        expected_installation_id,
        reason_code="installation:mismatch",
        message="expected_installation_id must be a positive integer",
    )
    if observed_installation_id != expected_installation_id:
        _reject(
            "installation:mismatch",
            "installation token does not match the invocation's configured installation",
        )

    if not isinstance(expected_repository, str) or not _REPOSITORY_RE.fullmatch(
        expected_repository
    ):
        _reject("repository:name-invalid", "expected_repository must use owner/name form")
    expected_key = expected_repository.lower()

    selection_mode = installation_repositories_snapshot.get("repository_selection")
    if selection_mode not in SUPPORTED_SELECTION_MODES:
        _reject(
            "selection-mode:unsupported",
            "installation repository-selection mode is unsupported",
        )

    entries = _entries(installation_repositories_snapshot)
    matches = [
        entry
        for entry in entries
        if isinstance(entry.get("full_name"), str)
        and entry["full_name"].lower() == expected_key
    ]
    if not matches:
        _reject("repository:absent", "expected repository is absent from the snapshot")
    if len(matches) > 1:
        _reject(
            "repository:duplicate",
            "expected repository has duplicate or case-colliding snapshot records",
        )

    selected = matches[0]
    selected_id = selected.get("id")
    if (
        not isinstance(selected_id, int)
        or isinstance(selected_id, bool)
        or selected_id <= 0
    ):
        _reject("repository:id-invalid", "selected repository id is not a positive integer")
    if any(
        other is not selected and other.get("id") == selected_id for other in entries
    ):
        _reject("repository:duplicate", "selected repository id collides with another record")

    full_name = selected["full_name"]
    if not _REPOSITORY_RE.fullmatch(full_name):
        _reject("repository:name-invalid", "selected repository full_name is malformed")

    retrieved_at = _require_timestamp(retrieved_at)
    digest = _evidence_digest(
        repository_key=expected_key, full_name=full_name, repository_id=selected_id
    )

    return InstallationRepositoryIdentityEvidence(
        contract_version=INSTALLATION_REPOSITORY_IDENTITY_CONTRACT_VERSION,
        installation_id=expected_installation_id,
        repository_key=expected_key,
        full_name=full_name,
        repository_id=selected_id,
        selection_mode=selection_mode,
        retrieved_at=retrieved_at,
        source_endpoint_family=SOURCE_ENDPOINT_FAMILY,
        evidence_digest=digest,
    )


def trusted_repository_identity_from_evidence(
    evidence: InstallationRepositoryIdentityEvidence,
) -> TrustedRepositoryIdentity:
    """Construct the existing provider's identity type from proven evidence."""

    if not isinstance(evidence, InstallationRepositoryIdentityEvidence):
        raise TypeError("evidence must be InstallationRepositoryIdentityEvidence")
    return TrustedRepositoryIdentity(
        repository=evidence.full_name, repository_id=evidence.repository_id
    )
