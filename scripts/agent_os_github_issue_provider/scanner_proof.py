"""Bounded live scanner-proof composition for #531 / #1762.

This module owns no credential retrieval. A host-owned ``GitHubAppSecretProvider``
is injected by the separately authorized runtime. The proof is fixed to the Agent
OS repository/App/installation and performs one installation-scope acquisition
followed by one issue-page read with no automatic retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol

from .auth import GitHubAppConfig, GitHubAppSecretProvider, build_installation_client
from .installation_repository_identity import (
    build_installation_repository_identity,
    trusted_repository_identity_from_evidence,
)
from .provider import PyGithubIssuePageProvider
from .transport import PyGithubRestTransport

REPOSITORY = "Blummer92/agent-os"
APP_ID = 4371154
INSTALLATION_ID = 148403885
PAGE = 1
PER_PAGE = 30
STATE = "open"


class InstallationSnapshotReader(Protocol):
    def read(self, client: object) -> tuple[Mapping[str, object], bool, bool, int]: ...


@dataclass(frozen=True, slots=True)
class ScannerProofEvidence:
    status: str
    reason: str
    repository: str = REPOSITORY
    page: int = PAGE
    per_page: int = PER_PAGE
    state: str = STATE
    installation_id: int = INSTALLATION_ID
    repository_id: int | None = None
    item_count: int = 0
    next_page: int | None = None
    terminal_page_proven: bool = False
    same_invocation_identity: bool = False
    external_side_effects_performed: bool = False
    production_state_mutated: bool = False
    execution_authorized: bool = False
    publication_authorized: bool = False
    complete_scan_authorized: bool = False
    automatic_retry: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_scanner_proof(
    *,
    secrets: GitHubAppSecretProvider,
    installation_snapshot_reader: InstallationSnapshotReader,
) -> ScannerProofEvidence:
    """Run the fixed one-page proof; return only bounded non-sensitive evidence."""
    try:
        client = build_installation_client(
            GitHubAppConfig(app_id=APP_ID, installation_id=INSTALLATION_ID), secrets
        )
        snapshot, complete, terminal, observed_installation_id = installation_snapshot_reader.read(client)
        identity_evidence = build_installation_repository_identity(
            installation_repositories_snapshot=snapshot,
            snapshot_complete=complete,
            snapshot_terminal_page_proven=terminal,
            observed_installation_id=observed_installation_id,
            expected_installation_id=INSTALLATION_ID,
            expected_repository=REPOSITORY,
            retrieved_at=_now(),
        )
        trusted = trusted_repository_identity_from_evidence(identity_evidence)
        provider = PyGithubIssuePageProvider(
            PyGithubRestTransport(client=client, max_attempts=1),
            trusted_repository_identities=(trusted,),
        )
        response = provider.read_issue_page(
            REPOSITORY, page=PAGE, per_page=PER_PAGE, state=STATE
        )
        if not response.complete:
            return ScannerProofEvidence(status="blocked", reason="issue-page-unproven")
        return ScannerProofEvidence(
            status="success",
            reason="bounded-page-proven",
            repository_id=trusted.repository_id,
            item_count=len(response.items),
            next_page=response.next_page,
            terminal_page_proven=response.terminal_page_proven,
            same_invocation_identity=True,
        )
    except Exception as error:
        reason = getattr(error, "reason_code", None)
        if not isinstance(reason, str):
            reason = "scanner-proof-failed"
        return ScannerProofEvidence(status="blocked", reason=reason)


__all__ = [
    "APP_ID", "INSTALLATION_ID", "PAGE", "PER_PAGE", "REPOSITORY", "STATE",
    "InstallationSnapshotReader", "ScannerProofEvidence", "run_scanner_proof",
]
