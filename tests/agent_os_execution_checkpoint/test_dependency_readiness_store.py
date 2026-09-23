from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
)
from scripts.agent_os_execution_checkpoint.dependency_readiness_store import (
    DependencyReadinessIntegrityError,
    DependencyReadinessNotFound,
    append_dependency_readiness,
    load_dependency_readiness,
)


def _evidence() -> DependencyReadinessEvidence:
    return DependencyReadinessEvidence(
        execution_surface_id="surface:gce",
        workspace_identity="workspace:abc",
        source_sha="a" * 40,
        required_environment_id="required-environment:" + "b" * 64,
        package_root=".",
        ecosystem=DependencyEcosystem.PYTHON_PIP,
        runtime_version="3.12.1",
        package_manager_version="24.0",
        declared_dependency_identity="manifest:" + "c" * 64,
        lock_or_constraints_identity="lock:" + "d" * 64,
        install_mode=DependencyInstallMode.NORMAL,
        source_or_registry_identity="pypi.org",
        cache_state=DependencyCacheState.CURRENT_COMPLETE,
        preparation_status=DependencyPreparationStatus.READY,
        resolved_dependency_identity="pip-freeze:" + "e" * 64,
        environment_health_evidence_id="environment-health:" + "f" * 64,
        observed_at="2026-08-18T18:00:00Z",
        expires_at="2026-08-18T20:00:00Z",
        reproducibility_level=ReproducibilityLevel.LOCKED,
    )


def test_round_trip_is_exact_and_idempotent(tmp_path) -> None:
    evidence = _evidence()
    first = append_dependency_readiness(tmp_path, evidence)
    second = append_dependency_readiness(tmp_path, evidence)
    assert first.evidence_id == evidence.dependency_readiness_evidence_id
    assert second.already_present is True
    assert load_dependency_readiness(tmp_path, first.evidence_id) == evidence


def test_missing_identity_fails_closed(tmp_path) -> None:
    with pytest.raises(DependencyReadinessNotFound):
        load_dependency_readiness(tmp_path, "dependency-readiness:" + "0" * 64)


def test_tampered_payload_fails_closed(tmp_path) -> None:
    evidence = _evidence()
    outcome = append_dependency_readiness(tmp_path, evidence)
    outcome.path.write_text("{}", encoding="utf-8")
    with pytest.raises(DependencyReadinessIntegrityError):
        load_dependency_readiness(tmp_path, evidence.dependency_readiness_evidence_id)


def test_identity_change_is_a_distinct_record(tmp_path) -> None:
    evidence = _evidence()
    append_dependency_readiness(tmp_path, evidence)
    changed = replace(evidence, workspace_identity="workspace:def", dependency_readiness_evidence_id="")
    outcome = append_dependency_readiness(tmp_path, changed)
    assert outcome.evidence_id != evidence.dependency_readiness_evidence_id
    assert load_dependency_readiness(tmp_path, outcome.evidence_id) == changed


def test_store_never_serializes_pilot_input(tmp_path) -> None:
    evidence = _evidence()
    outcome = append_dependency_readiness(tmp_path, evidence)
    text = outcome.path.read_text(encoding="utf-8")
    assert "SingleIssuePilotInput" not in text
    assert "execution_authorized\":true" not in text
