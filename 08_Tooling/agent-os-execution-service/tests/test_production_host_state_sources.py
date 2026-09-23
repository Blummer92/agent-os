from __future__ import annotations

import ast
import inspect

import agent_os_execution_service.governed_resume_restart_capsule as capsule_module
import agent_os_execution_service.handoff_publication as publication
import agent_os_execution_service.production_host_state_sources as sources


def test_production_source_surface_has_all_seven_slots():
    required = {
        "route_decision",
        "handoff",
        "checkpoint",
        "resume_plan",
        "candidate_packet",
        "runtime_configuration",
        "pilot_input",
    }
    assert required <= set(vars(sources.ProductionHostStateSources))


def test_production_sources_have_no_network_process_or_cloud_imports():
    tree = ast.parse(inspect.getsource(sources))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = ("subprocess", "requests", "httpx", "github", "google.cloud", "paramiko")
    assert not [name for name in imports if name.startswith(forbidden)]


def test_restart_capsule_is_persisted_before_descriptor():
    source = inspect.getsource(publication.publish_governed_handoff)
    assert source.index("append_restart_capsule") < source.index(
        "persist_current_invocation_descriptor"
    )


# --- AOS-GCE2F (#1320) required-environment source consumption ----------------


def _spec():
    from scripts.agent_os_execution_capabilities.dependencies import (
        DependencyArtifactIdentity,
        DependencyEcosystem,
        DependencyInstallMode,
        RequiredEnvironmentSpec,
    )

    return RequiredEnvironmentSpec(
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


def test_required_environment_reader_matches_the_1303_source_slot_signature():
    """#1319 can compose the reader without learning its source-of-truth internals."""
    reader = capsule_module.build_required_environment_spec_reader("/tmp/checkpoints")

    parameters = list(inspect.signature(reader).parameters)
    assert len(parameters) == 1
    annotation = inspect.signature(
        capsule_module.load_required_environment_spec
    ).parameters["descriptor"].annotation
    assert annotation == "GovernedInvocationDescriptor"
    assert sources.RequiredEnvironmentSpecReader is not None


def test_1303_consumes_the_capsule_reader_without_alternate_semantics(tmp_path):
    from scripts.agent_os_candidate_packet.stage_models import (
        DependencyEvidence,
        EvidenceStatus,
        ValidationEvidence,
    )

    class _IssueReader:
        def read_issue(self, repository, issue_number):
            raise AssertionError("state rebuild is not exercised here")

    class _RepositoryReader:
        def read_dependency_evidence(self, repository, issue_number):
            return DependencyEvidence(status=EvidenceStatus.UNAVAILABLE)

        def read_validation_evidence(self, repository, issue_number):
            return ValidationEvidence(status=EvidenceStatus.UNAVAILABLE)

    composed = sources.ProductionHostStateSources(
        checkpoint_store_root=tmp_path,
        issue_reader=_IssueReader(),
        repository_reader=_RepositoryReader(),
        repository_observation_reader=lambda descriptor: descriptor,
        required_environment_spec_reader=(
            capsule_module.build_required_environment_spec_reader(tmp_path)
        ),
        evaluated_at="2026-08-21T12:00:00Z",
        repository_root=tmp_path,
        workspace_parent=tmp_path,
        lease_directory=tmp_path,
    )

    assert callable(composed.required_environment_spec_reader)
    assert composed.dependency_identity_evidence_reader is None


def test_1303_still_rechecks_the_descriptor_environment_identity():
    """The consumer keeps its own identity gate; the reader adds no second one."""
    source = inspect.getsource(sources.ProductionHostStateSources._rebuild_current_state)
    assert "required_environment_spec_reader(descriptor)" in source
    assert "required_environment.required_environment_id != descriptor.required_environment_id" in source


def test_capsule_persistence_introduces_no_second_store_or_authority():
    source = inspect.getsource(capsule_module)
    assert source.count('"governed-resume-restart-capsules"') == 1
    for banned in (
        "sqlite3",
        "Scheduler(",
        "acquire_lease",
        "retry",
        "subprocess",
        "execution_authorized=True",
        "merge_authorized=True",
    ):
        assert banned not in source, f"restart capsule module introduces {banned!r}"
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert "scripts.agent_os_execution_checkpoint.store" in imports
    assert not [
        name
        for name in imports
        if name.startswith(("subprocess", "requests", "github", "google.cloud", "paramiko"))
    ]


def test_capsule_reuses_the_canonical_spec_transport_rather_than_a_second_one():
    source = inspect.getsource(capsule_module)
    assert "required_environment_spec_payload(" in source
    assert "reconstruct_required_environment_spec(" in source
    assert "class RequiredEnvironmentSpec" not in source
