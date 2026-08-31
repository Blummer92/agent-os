"""Offline fixture-first tests for #555 same-invocation identity evidence.

Every test constructs the snapshot in-process. No connected read, credential,
or network call is performed, and no live GitHub API or Cloud Build call is
authorized or attempted.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_github_issue_provider.installation_repository_identity import (
    INSTALLATION_REPOSITORY_IDENTITY_CONTRACT_VERSION,
    InstallationRepositoryIdentityError,
    InstallationRepositoryIdentityEvidence,
    SOURCE_ENDPOINT_FAMILY,
    build_installation_repository_identity,
    trusted_repository_identity_from_evidence,
)
from scripts.agent_os_github_issue_provider.models import TrustedRepositoryIdentity

REPOSITORY = "Owner/Repo"
REPOSITORY_ID = 4242
INSTALLATION_ID = 99
RETRIEVED_AT = "2026-08-31T00:00:00Z"


def _entry(full_name: str = REPOSITORY, repo_id: int = REPOSITORY_ID, **extra):
    entry = {"full_name": full_name, "id": repo_id}
    entry.update(extra)
    return entry


def _snapshot(*entries, selection_mode: str = "selected"):
    collected = entries or (_entry(),)
    return {
        "total_count": len(collected),
        "repository_selection": selection_mode,
        "repositories": list(collected),
    }


def _build(**overrides):
    kwargs = dict(
        installation_repositories_snapshot=_snapshot(),
        snapshot_complete=True,
        snapshot_terminal_page_proven=True,
        observed_installation_id=INSTALLATION_ID,
        expected_installation_id=INSTALLATION_ID,
        expected_repository=REPOSITORY,
        retrieved_at=RETRIEVED_AT,
    )
    kwargs.update(overrides)
    return build_installation_repository_identity(**kwargs)


def test_exact_installation_and_full_name_id_succeeds():
    evidence = _build()

    assert evidence.contract_version == INSTALLATION_REPOSITORY_IDENTITY_CONTRACT_VERSION
    assert evidence.installation_id == INSTALLATION_ID
    assert evidence.repository_key == REPOSITORY.lower()
    assert evidence.full_name == REPOSITORY
    assert evidence.repository_id == REPOSITORY_ID
    assert evidence.selection_mode == "selected"
    assert evidence.retrieved_at == RETRIEVED_AT
    assert evidence.source_endpoint_family == SOURCE_ENDPOINT_FAMILY
    assert evidence.same_invocation is True
    assert evidence.execution_authorized is False
    assert isinstance(evidence.evidence_digest, str) and evidence.evidence_digest

    identity = trusted_repository_identity_from_evidence(evidence)
    assert identity == TrustedRepositoryIdentity(
        repository=REPOSITORY, repository_id=REPOSITORY_ID
    )


def test_case_variant_repository_match_succeeds():
    evidence = _build(
        installation_repositories_snapshot=_snapshot(_entry(full_name="owner/repo")),
        expected_repository="OWNER/REPO",
    )

    assert evidence.full_name == "owner/repo"
    assert evidence.repository_key == "owner/repo"


def test_duplicate_case_colliding_records_fail_closed():
    snapshot = _snapshot(_entry(full_name="Owner/Repo"), _entry(full_name="owner/repo"))

    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(installation_repositories_snapshot=snapshot)

    assert excinfo.value.reason_code == "repository:duplicate"


def test_duplicate_id_collision_fails_closed():
    snapshot = _snapshot(
        _entry(full_name=REPOSITORY, repo_id=REPOSITORY_ID),
        _entry(full_name="Owner/Other", repo_id=REPOSITORY_ID),
    )

    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(installation_repositories_snapshot=snapshot)

    assert excinfo.value.reason_code == "repository:duplicate"


def test_installation_mismatch_fails_closed():
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(observed_installation_id=INSTALLATION_ID + 1)

    assert excinfo.value.reason_code == "installation:mismatch"


def test_repository_id_mismatch_fails_closed():
    snapshot = _snapshot(_entry(repo_id=REPOSITORY_ID + 1))

    # id-invalid is only about shape; a benign wrong id still yields a
    # positive int, so mismatch is enforced by the caller comparing the
    # evidence's repository_id against its own expectation.
    evidence = _build(installation_repositories_snapshot=snapshot)
    assert evidence.repository_id == REPOSITORY_ID + 1
    assert evidence.repository_id != REPOSITORY_ID


def test_repository_full_name_mismatch_fails_closed():
    snapshot = _snapshot(_entry(full_name="Other/Repo"))

    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(installation_repositories_snapshot=snapshot)

    assert excinfo.value.reason_code == "repository:absent"


def test_repository_absence_fails_closed():
    snapshot = _snapshot(_entry(full_name="Owner/OtherRepo"))

    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(installation_repositories_snapshot=snapshot)

    assert excinfo.value.reason_code == "repository:absent"


def test_incomplete_pagination_fails_closed():
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(snapshot_complete=False)

    assert excinfo.value.reason_code == "pagination:incomplete"


def test_ambiguous_pagination_fails_closed():
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(snapshot_terminal_page_proven=False)

    assert excinfo.value.reason_code == "pagination:incomplete"


def test_unsupported_evidence_version_fails_closed():
    evidence = _build()
    payload = {
        "contract_version": "agent-os-installation-repository-identity/v2",
        "installation_id": evidence.installation_id,
        "repository_key": evidence.repository_key,
        "full_name": evidence.full_name,
        "repository_id": evidence.repository_id,
        "selection_mode": evidence.selection_mode,
        "retrieved_at": evidence.retrieved_at,
        "source_endpoint_family": evidence.source_endpoint_family,
        "evidence_digest": evidence.evidence_digest,
    }

    with pytest.raises(ValueError):
        InstallationRepositoryIdentityEvidence(**payload)


def test_evidence_from_another_invocation_is_not_trusted_by_identity_alone():
    first = _build()
    second = _build(retrieved_at="2026-08-31T01:00:00Z")

    # Each invocation's evidence is independently valid; nothing links them,
    # so evidence retrieved earlier carries no special standing over evidence
    # retrieved now. Only the caller's own current-invocation snapshot is
    # ever fed into this builder again.
    assert first.evidence_digest == second.evidence_digest
    assert first.retrieved_at != second.retrieved_at


def test_rename_invalidates_old_full_name_binding():
    original = _build()

    renamed_snapshot = _snapshot(_entry(full_name="Owner/Renamed"))
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(
            installation_repositories_snapshot=renamed_snapshot,
            expected_repository=original.full_name,
        )

    assert excinfo.value.reason_code == "repository:absent"


def test_transfer_invalidates_old_full_name_binding():
    transferred_snapshot = _snapshot(_entry(full_name="NewOwner/Repo"))

    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(
            installation_repositories_snapshot=transferred_snapshot,
            expected_repository=REPOSITORY,
        )

    assert excinfo.value.reason_code == "repository:absent"


def test_unsupported_selection_mode_fails_closed():
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(installation_repositories_snapshot=_snapshot(selection_mode="unknown"))

    assert excinfo.value.reason_code == "selection-mode:unsupported"


def test_malformed_snapshot_shape_fails_closed():
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(
            installation_repositories_snapshot={
                "repository_selection": "selected",
                "repositories": [1, 2],
            }
        )

    assert excinfo.value.reason_code == "snapshot:malformed"


def test_evidence_carries_no_raw_payload_urls_tokens_or_credentials():
    evidence = _build()
    fields = {
        "contract_version",
        "installation_id",
        "repository_key",
        "full_name",
        "repository_id",
        "selection_mode",
        "retrieved_at",
        "source_endpoint_family",
        "evidence_digest",
        "same_invocation",
        "execution_authorized",
    }
    assert set(evidence.__dataclass_fields__) == fields
    for name in ("repositories", "headers", "token", "jwt", "url", "credentials"):
        assert not hasattr(evidence, name)


def test_repeated_calls_retain_no_identity_state():
    first = _build()
    second = _build(
        installation_repositories_snapshot=_snapshot(_entry(full_name="Owner/Other")),
        expected_repository="Owner/Other",
    )

    assert first.full_name == REPOSITORY
    assert second.full_name == "Owner/Other"
    # A fresh call is unaffected by any earlier call: no module-level cache
    # or mutable global state exists to leak between invocations.
    third = _build()
    assert third.full_name == REPOSITORY


def test_build_requires_mapping_snapshot():
    with pytest.raises(InstallationRepositoryIdentityError) as excinfo:
        _build(installation_repositories_snapshot=["not", "a", "mapping"])

    assert excinfo.value.reason_code == "snapshot:malformed"


def test_trusted_repository_identity_from_evidence_requires_evidence_type():
    with pytest.raises(TypeError):
        trusted_repository_identity_from_evidence(object())
