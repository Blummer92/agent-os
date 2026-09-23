"""``LiveRepositoryEvidenceReader`` evidence-mapping tests (#1155, #1320).

The #1155 contract -- truthfully ``UNAVAILABLE`` with no structured source --
is preserved verbatim below. AOS-GCE2F (#1320) adds the structured mapping over
the two existing canonical owners (#1185/#1197 ``DependencyReadinessEvidence``
and the existing advisory pre-PR validation evidence) and proves every
fail-closed edge. Offline and deterministic: no GitHub, network, cloud, IAM,
VM, SSH, or subprocess effect.
"""

from __future__ import annotations

import pytest

from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet_live_input.repository_reader import (
    DEPENDENCY_ENVIRONMENT_MISMATCH_REASON,
    DEPENDENCY_EVIDENCE_MALFORMED_REASON,
    DEPENDENCY_EVIDENCE_NOT_CURRENT_REASON,
    DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,
    DEPENDENCY_SUBJECT_MISMATCH_REASON,
    VALIDATION_NO_STRUCTURED_SOURCE_REASON,
    VALIDATION_PLAN_MISMATCH_REASON,
    VALIDATION_STATUS_UNKNOWN_REASON,
    VALIDATION_SUBJECT_MISMATCH_REASON,
    LiveRepositoryEvidenceReader,
)
from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyArtifactIdentity,
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
    RequiredEnvironmentSpec,
)
from scripts.agent_os_execution_capabilities.models import RepositoryIdentity
from scripts.agent_os_remote_validation.advisory_gate import AdvisoryEvidenceResult

_REPOSITORY = "Blummer92/agent-os"
_ISSUE_NUMBER = 1155
_EVALUATED_AT = "2026-08-21T12:00:00Z"
_PLAN_ID = "validation-plan:" + "e" * 64


def _spec(**changes) -> RequiredEnvironmentSpec:
    values = dict(
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        package_root=".",
        runtime_requirement=">=3.11",
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="requirements-dev.txt", sha256="a" * 64
        ),
        lock_or_constraints_identity=None,
        install_mode=DependencyInstallMode.NORMAL,
        approved_source_identity="pypi.org/simple",
        required_validation_command_ids=("pytest",),
    )
    values.update(changes)
    return RequiredEnvironmentSpec(**values)


def _readiness(spec: RequiredEnvironmentSpec, **changes) -> DependencyReadinessEvidence:
    values = dict(
        execution_surface_id="execution-surface:governed-runner",
        workspace_identity="workspace:1320",
        source_sha="b" * 40,
        required_environment_id=spec.required_environment_id,
        package_root=spec.package_root,
        ecosystem=spec.ecosystem,
        runtime_version="3.11.15",
        package_manager_version="25.2",
        declared_dependency_identity="declared:" + "c" * 64,
        lock_or_constraints_identity=None,
        install_mode=spec.install_mode,
        source_or_registry_identity="pypi.org/simple",
        cache_state=DependencyCacheState.CURRENT_COMPLETE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity="resolved:" + "d" * 64,
        environment_health_evidence_id="environment-health:" + "f" * 64,
        observed_at="2026-08-21T11:00:00Z",
        expires_at="2026-08-21T13:00:00Z",
        reproducibility_level=ReproducibilityLevel.LOCKED,
    )
    values.update(changes)
    return DependencyReadinessEvidence(**values)


def _advisory(status: str = "passed", **changes) -> AdvisoryEvidenceResult:
    values = dict(
        schema_name="agent-os.advisory-evidence",
        schema_version="1.0",
        status=status,
        result_id="advisory-evidence:" + "1" * 64,
        repository_identity=RepositoryIdentity(
            host="github.com", owner="Blummer92", repository="agent-os"
        ),
        pull_request=1321,
        base_branch="main",
        base_sha="2" * 40,
        source_head_sha="3" * 40,
        tested_sha="3" * 40,
        repository_evidence_type=None,
        projection_id="projection:" + "4" * 64,
        proposal_id="proposal:" + "5" * 64,
        approval_id="approval:" + "6" * 64,
        repository_state_evidence_id="repository-state:" + "7" * 64,
        implementation_contract_fingerprint="contract:" + "8" * 64,
        selector_version="v1",
        profile="python",
        command_set_digest="9" * 64,
        plan_id=_PLAN_ID,
        bundle_id="validation-evidence-bundle:" + "a" * 64,
        runner_id="runner:governed",
        invocation_id="invocation:" + "b" * 64,
        command_result_ids=(),
        command_result_statuses=(),
        reason_codes=(),
        details=(),
    )
    values.update(changes)
    return AdvisoryEvidenceResult(**values)


def _structured_reader(**changes) -> LiveRepositoryEvidenceReader:
    spec = changes.pop("spec", None) or _spec()
    values = dict(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        required_environment_spec=spec,
        dependency_readiness=_readiness(spec),
        validation_result=_advisory(),
        evaluated_at=_EVALUATED_AT,
        expected_validation_plan_id=_PLAN_ID,
    )
    values.update(changes)
    return LiveRepositoryEvidenceReader(**values)


# --- #1155 unconfigured reader stays truthfully UNAVAILABLE -------------------


def test_dependency_evidence_is_always_unavailable_with_exact_reason_code() -> None:
    reader = LiveRepositoryEvidenceReader()

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, DependencyEvidence)
    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,)


def test_validation_evidence_is_always_unavailable_with_exact_reason_code() -> None:
    reader = LiveRepositoryEvidenceReader()

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, ValidationEvidence)
    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_NO_STRUCTURED_SOURCE_REASON,)


def test_dependency_evidence_never_reports_resolved_clear() -> None:
    reader = LiveRepositoryEvidenceReader()
    for issue_number in (1, 42, 91105, 1155):
        result = reader.read_dependency_evidence(_REPOSITORY, issue_number)
        assert result.status is not EvidenceStatus.RESOLVED_CLEAR


def test_validation_evidence_never_reports_resolved_clear() -> None:
    reader = LiveRepositoryEvidenceReader()
    for issue_number in (1, 42, 91105, 1155):
        result = reader.read_validation_evidence(_REPOSITORY, issue_number)
        assert result.status is not EvidenceStatus.RESOLVED_CLEAR


def test_reader_execution_authorized_is_always_false() -> None:
    assert LiveRepositoryEvidenceReader().execution_authorized is False
    assert _structured_reader().execution_authorized is False


# --- AOS-GCE2F (#1320) structured dependency evidence -------------------------


def test_current_ready_readiness_resolves_clear_through_the_existing_vocabulary() -> None:
    spec = _spec()
    reader = _structured_reader(spec=spec)

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, DependencyEvidence)
    assert result.status is EvidenceStatus.RESOLVED_CLEAR
    assert result.reason_codes == ()
    assert f"required-environment-id={spec.required_environment_id}" in result.details


@pytest.mark.parametrize(
    ("preparation_status", "expected_reason"),
    (
        (DependencyPreparationStatus.PREPARATION_REQUIRED, "dependency.preparation-required"),
        (
            DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED,
            "dependency.source-update-required",
        ),
        (DependencyPreparationStatus.BLOCKED, "dependency.preparation-blocked"),
        (DependencyPreparationStatus.FAILED, "dependency.preparation-failed"),
    ),
)
def test_not_ready_readiness_resolves_blocked(
    preparation_status: DependencyPreparationStatus, expected_reason: str
) -> None:
    spec = _spec()
    reader = _structured_reader(
        spec=spec,
        dependency_readiness=_readiness(
            spec,
            preparation_status=preparation_status,
            resolved_dependency_identity=None,
            reason_codes=("dependency.lock-required",),
        ),
    )

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.RESOLVED_BLOCKED
    assert result.reason_codes[0] == expected_reason
    assert "dependency.lock-required" in result.reason_codes


def test_required_environment_alone_never_proves_runtime_readiness() -> None:
    reader = LiveRepositoryEvidenceReader(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        required_environment_spec=_spec(),
        validation_result=_advisory(),
        evaluated_at=_EVALUATED_AT,
    )

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_NO_STRUCTURED_SOURCE_REASON,)


def test_stale_required_environment_identity_cannot_satisfy_the_current_spec() -> None:
    current = _spec()
    stale = _spec(
        dependency_manifest_identity=DependencyArtifactIdentity(
            relative_path="requirements-dev.txt", sha256="e" * 64
        )
    )
    assert stale.required_environment_id != current.required_environment_id
    reader = _structured_reader(spec=current, dependency_readiness=_readiness(stale))

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_ENVIRONMENT_MISMATCH_REASON,)


def test_readiness_declaring_a_different_package_root_fails_closed() -> None:
    spec = _spec()
    reader = _structured_reader(
        spec=spec,
        dependency_readiness=_readiness(spec, package_root="08_Tooling"),
    )

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_ENVIRONMENT_MISMATCH_REASON,)


def test_expired_readiness_evidence_is_not_current_and_fails_closed() -> None:
    spec = _spec()
    reader = _structured_reader(
        spec=spec, evaluated_at="2026-08-21T14:00:00Z"
    )

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_EVIDENCE_NOT_CURRENT_REASON,)


def test_malformed_evaluation_moment_fails_closed() -> None:
    reader = _structured_reader(evaluated_at="not-a-timestamp")

    result = reader.read_dependency_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_EVIDENCE_MALFORMED_REASON,)


@pytest.mark.parametrize(
    ("repository", "issue_number"),
    (
        ("Blummer92/other-repo", _ISSUE_NUMBER),
        (_REPOSITORY, 4242),
    ),
)
def test_dependency_evidence_for_another_subject_fails_closed(
    repository: str, issue_number: int
) -> None:
    result = _structured_reader().read_dependency_evidence(repository, issue_number)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (DEPENDENCY_SUBJECT_MISMATCH_REASON,)


def test_repository_case_differences_still_match_the_bound_subject() -> None:
    result = _structured_reader().read_dependency_evidence(
        _REPOSITORY.lower(), _ISSUE_NUMBER
    )

    assert result.status is EvidenceStatus.RESOLVED_CLEAR


# --- AOS-GCE2F (#1320) structured validation evidence -------------------------


@pytest.mark.parametrize(
    ("advisory_status", "expected_status"),
    (
        ("passed", EvidenceStatus.RESOLVED_CLEAR),
        ("failed", EvidenceStatus.RESOLVED_BLOCKED),
        ("incomplete", EvidenceStatus.RESOLVED_BLOCKED),
        ("needs-decision", EvidenceStatus.NEEDS_DECISION),
        ("stale", EvidenceStatus.UNAVAILABLE),
        ("invalid", EvidenceStatus.UNAVAILABLE),
    ),
)
def test_advisory_status_maps_into_the_existing_validation_vocabulary(
    advisory_status: str, expected_status: EvidenceStatus
) -> None:
    reader = _structured_reader(validation_result=_advisory(advisory_status))

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert isinstance(result, ValidationEvidence)
    assert result.status is expected_status
    assert f"advisory-status={advisory_status}" in result.details


def test_unknown_advisory_status_fails_closed_rather_than_guessing() -> None:
    reader = _structured_reader(validation_result=_advisory("probably-fine"))

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_STATUS_UNKNOWN_REASON,)


def test_validation_evidence_for_another_repository_fails_closed() -> None:
    reader = _structured_reader(
        validation_result=_advisory(
            repository_identity=RepositoryIdentity(
                host="github.com", owner="Blummer92", repository="other-repo"
            )
        )
    )

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_SUBJECT_MISMATCH_REASON,)


def test_validation_evidence_without_a_repository_identity_fails_closed() -> None:
    reader = _structured_reader(validation_result=_advisory(repository_identity=None))

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_SUBJECT_MISMATCH_REASON,)


def test_validation_evidence_from_another_plan_fails_closed() -> None:
    reader = _structured_reader(
        validation_result=_advisory(plan_id="validation-plan:" + "0" * 64)
    )

    result = reader.read_validation_evidence(_REPOSITORY, _ISSUE_NUMBER)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_PLAN_MISMATCH_REASON,)


def test_validation_evidence_for_another_issue_fails_closed() -> None:
    result = _structured_reader().read_validation_evidence(_REPOSITORY, 4242)

    assert result.status is EvidenceStatus.UNAVAILABLE
    assert result.reason_codes == (VALIDATION_SUBJECT_MISMATCH_REASON,)


# --- construction-time fail-closed contract -----------------------------------


@pytest.mark.parametrize(
    "changes",
    (
        {"repository": None},
        {"issue_number": None},
        {"required_environment_spec": None},
        {"evaluated_at": None},
    ),
)
def test_structured_evidence_requires_its_exact_binding(changes: dict) -> None:
    with pytest.raises(TypeError):
        _structured_reader(**changes)


@pytest.mark.parametrize(
    "changes",
    (
        {"dependency_readiness": {"preparation_status": "ready"}},
        {"validation_result": {"status": "passed"}},
        {"required_environment_spec": {"required_environment_id": "x"}},
        {"issue_number": 0},
        {"repository": "   "},
    ),
)
def test_reader_rejects_non_canonical_evidence_objects(changes: dict) -> None:
    with pytest.raises(TypeError):
        _structured_reader(**changes)
