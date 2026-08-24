"""Offline tests for the production host bootstrap (#1319 / AOS-GCE2E).

Every test here is offline and injected: no GitHub, network, cloud, IAM, VM,
SSH, IAP, or process effect occurs, and no Scheduler job, lease acquisition, or
real reconstruction runs. Filesystem needs use ``tmp_path``.

Where an object's own contract is owned by another issue's suite (#1303 state
sources, #1287 composition, #1218 reconstruction, #758 dispatch, #1320 capsule
persistence), that seam is stubbed/monkeypatched exactly as
``test_production_host_composition.py`` already does -- these tests prove the
bootstrap's composition, binding, and fail-closed behaviour, not the internals
those suites already cover.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

import agent_os_execution_service.host_github_read_transport as ghread
import agent_os_execution_service.production_host_bootstrap as bootstrap_module
import agent_os_execution_service.production_host_composition as phc
from agent_os_execution_service.execution_authorization_source import (
    ExecutionAuthorizationSourceReason,
    ExecutionAuthorizationSourceStatus,
    reacquire_execution_authorization,
)
from agent_os_execution_service.governed_resume_entrypoint import (
    main as entrypoint_main,
    parse_handoff_argv,
    run_governed_resume,
)
from agent_os_execution_service.production_host_bootstrap import (
    DELEGATED_PARENT_CGROUP_ENV_VAR,
    LEASE_DIRECTORY_ENV_VAR,
    REPOSITORY_ROOT_ENV_VAR,
    REQUIRED_PATH_ENV_VARS,
    WORKSPACE_PARENT_ENV_VAR,
    ProductionHostBootstrapError,
    ProductionHostConfiguration,
    VerifierInvocation,
    build_production_host_bootstrap,
    build_repository_observation_reader,
    build_subprocess_verifier_runner,
    canonical_evaluated_at,
    load_production_host_configuration,
)
from agent_os_execution_service.production_host_composition import (
    CHECKPOINT_STORE_ROOT_ENV_VAR,
)
from agent_os_execution_service.production_host_state_sources import (
    ProductionHostStateSources,
)
from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation
from scripts.agent_os_candidate_packet.stage_models import (
    DependencyEvidence,
    EvidenceStatus,
    IssueReadStatus,
    ValidationEvidence,
)
from scripts.agent_os_candidate_packet_live_input import (
    LiveIssueReader,
    SingleIssueTransportOutcome,
    SingleIssueTransportResult,
    VerifierStdoutError,
)
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    WorktreeState,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
)

HANDOFF_ID = "executor-handoff:" + "a" * 64
BASE_SHA = "1" * 40
HEAD_SHA = "1" * 40
EVALUATED_AT = "2026-08-21T12:00:00Z"
CONTRACT_FINGERPRINT = "c" * 64


# --------------------------------------------------------------------------
# Fixtures and fakes
# --------------------------------------------------------------------------


def _descriptor(**overrides) -> GovernedInvocationDescriptor:
    fields = {
        "schema_name": "agent-os.governed-invocation-descriptor",
        "schema_version": "1.0",
        "repository": "Blummer92/agent-os",
        "issue_number": 1319,
        "issue_or_handoff_identity": "issue:1319",
        "handoff_id": HANDOFF_ID,
        "route_decision_id": "route-decision:" + "2" * 64,
        "execution_service_request_fingerprint": "request:" + "3" * 64,
        "authorization_id": "authorization:" + "4" * 64,
        "source_ref": "refs/heads/agent/1319-host-bootstrap",
        "source_sha": "5" * 40,
        "checkpoint_id": "checkpoint:" + "6" * 64,
        "resume_plan_id": "resume-plan:" + "7" * 64,
        "environment_profile_id": "environment-profile:" + "8" * 64,
        "environment_health_evidence_id": "environment-health:" + "9" * 64,
        "required_environment_id": "required-environment:" + "a" * 64,
        "dependency_readiness_evidence_id": "dependency-readiness:" + "0" * 64,
        "execution_surface_id": "execution-surface:test",
        "workspace_identity": "workspace:test",
        "workflow_runtime_identity": "workflow-runtime:test",
        "candidate_packet_id": "candidate-packet:" + "b" * 64,
        "runtime_configuration_fingerprint": "runtime-configuration:" + "c" * 64,
        "execution_id": "execution:" + "d" * 64,
        "invocation_id": "invocation:" + "e" * 64,
    }
    fields.update(overrides)
    return GovernedInvocationDescriptor(**fields)


def _capsule() -> SimpleNamespace:
    """Stand-in for the #1320 restart capsule this bootstrap only reads."""
    return SimpleNamespace(
        handoff_id=HANDOFF_ID,
        candidate_branch="agent/1319-host-bootstrap",
        candidate_packet=SimpleNamespace(
            base_branch="main",
            base_sha=BASE_SHA,
            freshness_boundary="2026-08-21T18:00:00Z",
            external_build_sha=None,
        ),
        approval_record=SimpleNamespace(
            binding=SimpleNamespace(
                implementation_contract_fingerprint=CONTRACT_FINGERPRINT
            )
        ),
    )


def _verifier_stdout(*, head_sha: str = HEAD_SHA, base_sha: str = BASE_SHA) -> str:
    return (
        "HEAD_REF=main\n"
        f"HEAD_SHA={head_sha}\n"
        "BASE_REF=origin/main\n"
        f"BASE_SHA={base_sha}\n"
        "CHANGED_FILES_BEGIN\n"
        "CHANGED_FILES_END\n"
    )


class _IssueTransport:
    """Injected read-only single-issue transport. Performs no network read."""

    def __init__(self, outcome=SingleIssueTransportOutcome.NOT_FOUND, item=None) -> None:
        self.outcome = outcome
        self.item = item
        self.calls: list[tuple[str, int]] = []

    def get_issue(self, repository: str, issue_number: int) -> SingleIssueTransportResult:
        self.calls.append((repository, issue_number))
        return SingleIssueTransportResult(outcome=self.outcome, item=self.item)


class _AuthorizationTransport:
    """Injected read-only authorization-source transport."""

    def __init__(self, snapshot: object | None = None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, int]] = []

    def read_authorization_source(self, repository: str, issue_number: int) -> object:
        self.calls.append((repository, issue_number))
        if self.snapshot is None:
            raise RuntimeError("source unavailable")
        return self.snapshot


class _EvidenceReader:
    """Stand-in for the AOS-GCE2F (#1320) ``LiveRepositoryEvidenceReader``."""

    execution_authorized = False

    def read_dependency_evidence(self, repository: str, issue_number: int):
        return DependencyEvidence(status=EvidenceStatus.UNAVAILABLE)

    def read_validation_evidence(self, repository: str, issue_number: int):
        return ValidationEvidence(status=EvidenceStatus.UNAVAILABLE)


def _host_paths(tmp_path) -> dict[str, str]:
    # ``leases`` is deliberately not created: HostLocalLeaseAdapter owns that
    # directory's existence and its owner-private mode.
    for name in ("checkpoints", "repository", "workspaces"):
        (tmp_path / name).mkdir(exist_ok=True)
    return {
        CHECKPOINT_STORE_ROOT_ENV_VAR: str(tmp_path / "checkpoints"),
        REPOSITORY_ROOT_ENV_VAR: str(tmp_path / "repository"),
        WORKSPACE_PARENT_ENV_VAR: str(tmp_path / "workspaces"),
        LEASE_DIRECTORY_ENV_VAR: str(tmp_path / "leases"),
    }


@pytest.fixture
def host_environment(tmp_path, monkeypatch) -> dict[str, str]:
    values = _host_paths(tmp_path)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv(DELEGATED_PARENT_CGROUP_ENV_VAR, raising=False)
    return values


def _build(monkeypatch, host_environment, *, stdout: str | None = None, **overrides):
    """Compose one bootstrap over injected transports and a fake verifier."""
    monkeypatch.setattr(bootstrap_module, "load_restart_capsule", lambda root, handoff: _capsule())
    runs: list[VerifierInvocation] = []

    def run_verifier(invocation: VerifierInvocation) -> str:
        runs.append(invocation)
        return _verifier_stdout() if stdout is None else stdout

    kwargs = dict(
        issue_transport=_IssueTransport(),
        authorization_transport=_AuthorizationTransport(),
        repository_evidence_reader=_EvidenceReader(),
        run_verifier=run_verifier,
        evaluated_at=EVALUATED_AT,
    )
    kwargs.update(overrides)
    return build_production_host_bootstrap(**kwargs), runs


# --------------------------------------------------------------------------
# 1. Canonical host configuration + injected transports construct #1303 sources
# --------------------------------------------------------------------------


def test_configuration_and_injected_transports_construct_1303_sources(
    monkeypatch, host_environment, tmp_path
):
    bootstrap, _ = _build(monkeypatch, host_environment)

    assert type(bootstrap.sources) is ProductionHostStateSources
    assert bootstrap.sources.checkpoint_store_root == tmp_path / "checkpoints"
    assert bootstrap.sources.repository_root == str(tmp_path / "repository")
    assert bootstrap.sources.workspace_parent == str(tmp_path / "workspaces")
    assert bootstrap.sources.lease_directory == str(tmp_path / "leases")
    assert bootstrap.sources.evaluated_at == EVALUATED_AT
    assert bootstrap.sources.delegated_parent_cgroup is None


def test_optional_delegated_cgroup_is_bound_from_host_state_only(
    monkeypatch, host_environment, tmp_path
):
    monkeypatch.setenv(DELEGATED_PARENT_CGROUP_ENV_VAR, str(tmp_path / "cgroup"))
    bootstrap, _ = _build(monkeypatch, host_environment)

    assert bootstrap.sources.delegated_parent_cgroup == str(tmp_path / "cgroup")


def test_required_environment_spec_reader_is_the_1320_capsule_reader(
    monkeypatch, host_environment
):
    """The bootstrap composes AOS-GCE2F's reader; it models no spec of its own."""
    bootstrap, _ = _build(monkeypatch, host_environment)
    reader = bootstrap.sources.required_environment_spec_reader

    assert callable(reader)
    assert list(inspect.signature(reader).parameters) == ["descriptor"]
    source = inspect.getsource(bootstrap_module.build_production_host_bootstrap)
    assert "build_required_environment_spec_reader(" in source


# --------------------------------------------------------------------------
# 2. The seven #1303 source methods reach #1287 composition unreimplemented
# --------------------------------------------------------------------------


def test_seven_source_methods_are_passed_to_1287_composition(
    monkeypatch, host_environment, tmp_path
):
    bootstrap, _ = _build(monkeypatch, host_environment)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        bootstrap_module,
        "build_production_governed_resume_bindings",
        lambda **kwargs: captured.update(kwargs) or "bindings",
    )

    assert bootstrap.governed_resume_bindings(cancelled=lambda: False) == "bindings"

    sources = bootstrap.sources
    direct = {
        "route_decision_reader": ProductionHostStateSources.route_decision,
        "handoff_reader": ProductionHostStateSources.handoff,
        "checkpoint_reader": ProductionHostStateSources.checkpoint,
        "resume_plan_reader": ProductionHostStateSources.resume_plan,
        "candidate_packet_rebuilder": ProductionHostStateSources.candidate_packet,
        "pilot_input_builder": ProductionHostStateSources.pilot_input,
    }
    for name, function in direct.items():
        bound = captured[name]
        assert bound.__self__ is sources
        assert bound.__func__ is function

    # The seventh slot reaches #1287 through the one invocation-scoped binding
    # that hands the *same* object back at dispatch time -- never a rebuild.
    binding = captured["runtime_configuration_builder"].__self__
    assert type(binding) is bootstrap_module._InvocationRuntimeConfigurationBinding
    assert captured["runtime_configuration_provider"].__self__ is binding
    assert binding._build.__func__ is ProductionHostStateSources.runtime_configuration

    configuration = object()
    binding._build = lambda descriptor, packet: configuration
    assert binding.build(_descriptor(), object()) is configuration
    assert binding.provide(object()) is configuration
    assert captured["evaluated_at"] == EVALUATED_AT
    assert captured["lease_directory"] == str(tmp_path / "leases")
    assert captured["authorization_transport"] is bootstrap.authorization_transport


def test_dispatch_without_a_reacquired_configuration_fails_closed():
    binding = bootstrap_module._InvocationRuntimeConfigurationBinding(lambda *_: None)

    with pytest.raises(ProductionHostBootstrapError):
        binding.provide(object())


# --------------------------------------------------------------------------
# 3. Issue reads flow through LiveIssueReader's existing status mapping
# --------------------------------------------------------------------------


def test_issue_reads_flow_through_live_issue_reader(monkeypatch, host_environment):
    transport = _IssueTransport(outcome=SingleIssueTransportOutcome.PERMISSION_DENIED)
    bootstrap, _ = _build(monkeypatch, host_environment, issue_transport=transport)

    reader = bootstrap.sources.issue_reader
    assert type(reader) is LiveIssueReader
    assert reader.transport is transport
    assert reader.execution_authorized is False

    result = reader.read_issue("Blummer92/agent-os", 1319)
    assert result.status is IssueReadStatus.PERMISSION_DENIED
    assert result.item is None
    assert transport.calls == [("Blummer92/agent-os", 1319)]


def test_host_github_transport_satisfies_the_single_issue_protocol():
    payloads = {"/repos/Blummer92/agent-os/issues/1319": {"number": 1319, "title": "x"}}
    transport = ghread.HostGitHubReadTransport(
        read_json=lambda path, parameters: payloads[path]
    )

    result = LiveIssueReader(transport=transport).read_issue("Blummer92/agent-os", 1319)
    assert result.status is IssueReadStatus.OK
    assert result.item == {"number": 1319, "title": "x"}


def test_host_github_transport_never_converts_an_error_to_ok():
    def read_json(path, parameters):
        raise ghread.HostGitHubReadError(SingleIssueTransportOutcome.NOT_FOUND)

    transport = ghread.HostGitHubReadTransport(read_json=read_json)
    result = LiveIssueReader(transport=transport).read_issue("Blummer92/agent-os", 1319)

    assert result.status is IssueReadStatus.NOT_FOUND


# --------------------------------------------------------------------------
# 4. Authorization reads keep the existing reacquire_execution_authorization
# --------------------------------------------------------------------------


def test_authorization_transport_is_consumed_by_existing_reacquire_semantics(
    monkeypatch, host_environment
):
    transport = _AuthorizationTransport()
    bootstrap, _ = _build(monkeypatch, host_environment, authorization_transport=transport)
    assert bootstrap.authorization_transport is transport

    result = reacquire_execution_authorization(
        transport=transport,
        repository="Blummer92/agent-os",
        issue_number=1319,
        expected_candidate_packet_id="candidate-packet:" + "b" * 64,
        expected_invocation_id="invocation:" + "e" * 64,
        expected_operation="governed-resume",
        expected_request_fingerprint="request:" + "3" * 64,
        expected_command_plan_id="command-plan:" + "4" * 64,
        expected_sha="5" * 40,
        evaluated_at=EVALUATED_AT,
    )

    # The transport raised; the existing owner -- not this bootstrap -- decided.
    assert result.status is ExecutionAuthorizationSourceStatus.NEEDS_DECISION
    assert result.reason_codes == (
        ExecutionAuthorizationSourceReason.SOURCE_UNAVAILABLE,
    )
    assert result.evidence is None
    assert transport.calls == [("Blummer92/agent-os", 1319)]


def test_host_github_transport_reports_an_incomplete_comment_source_truthfully():
    """A bounded read that could not see every comment is never called complete."""
    comment = {
        "id": 1,
        "user": {"login": "Blummer92"},
        "created_at": "2026-08-21T12:00:00Z",
        "body": "not an authorization record",
    }

    def read_json(path, parameters):
        if path == "/repos/Blummer92/agent-os":
            return {"owner": {"login": "Blummer92", "type": "User"}}
        return [dict(comment, id=index + 1) for index in range(ghread.COMMENTS_PAGE_SIZE)]

    transport = ghread.HostGitHubReadTransport(read_json=read_json, max_comment_pages=1)
    snapshot = transport.read_authorization_source("Blummer92/agent-os", 1319)

    assert snapshot.comments_complete is False
    result = reacquire_execution_authorization(
        transport=transport,
        repository="Blummer92/agent-os",
        issue_number=1319,
        expected_candidate_packet_id="candidate-packet:" + "b" * 64,
        expected_invocation_id="invocation:" + "e" * 64,
        expected_operation="governed-resume",
        expected_request_fingerprint="request:" + "3" * 64,
        expected_command_plan_id="command-plan:" + "4" * 64,
        expected_sha="5" * 40,
        evaluated_at=EVALUATED_AT,
    )
    assert result.status is ExecutionAuthorizationSourceStatus.NEEDS_DECISION
    assert ExecutionAuthorizationSourceReason.SOURCE_INCOMPLETE in result.reason_codes


def test_bootstrap_rejects_an_authorization_transport_of_the_wrong_shape(
    monkeypatch, host_environment
):
    with pytest.raises(ProductionHostBootstrapError):
        _build(
            monkeypatch,
            host_environment,
            authorization_transport=SimpleNamespace(read_issue=lambda *a: None),
        )


# --------------------------------------------------------------------------
# 5. Repository observation comes from canonical verifier stdout
# --------------------------------------------------------------------------


def test_repository_observation_is_derived_from_canonical_verifier_stdout(
    monkeypatch, host_environment, tmp_path
):
    bootstrap, runs = _build(monkeypatch, host_environment)
    observation = bootstrap.sources.repository_observation_reader(_descriptor())

    assert type(observation) is RepositoryObservation
    # Every Git fact comes from the verifier, none from ad hoc inspection.
    assert observation.head_ref == "main"
    assert observation.head_sha == HEAD_SHA
    # The verifier emits origin/main, but the observation adapter owns the one
    # transport-to-canonical conversion before host state consumes it.
    assert observation.base_ref == "main"
    assert observation.base_sha == BASE_SHA
    assert observation.observed_sha == HEAD_SHA
    assert observation.worktree_state is WorktreeState.CLEAN
    assert observation.evidence_type is RepositoryEvidenceType.BRANCH_HEAD

    # Caller-supplied fields are bound from canonical owners, never invented.
    assert observation.correlation_id == "invocation:" + "e" * 64
    assert observation.contract_fingerprint == CONTRACT_FINGERPRINT
    assert observation.freshness_boundary == "2026-08-21T18:00:00Z"
    assert observation.observed_at == EVALUATED_AT
    assert observation.requested_ref == "main"
    assert observation.requested_sha == BASE_SHA
    assert observation.repository_identity.owner == "blummer92"
    assert observation.repository_identity.repository == "agent-os"
    assert observation.repository_identity.host == "github.com"
    # Facts the verifier does not observe are stated absent, never inferred.
    assert observation.tested_sha is None
    assert observation.pushed_sha is None
    assert observation.proposed_pr_sha is None
    assert observation.synthetic_merge_sha is None

    # The verifier was asked for the base branch the invocation is pinned to,
    # under the configured repository root -- never a caller-supplied root.
    assert len(runs) == 1
    assert runs[0] == VerifierInvocation(
        repository_root=tmp_path / "repository",
        branch="main",
        base_branch="main",
    )


def test_verifier_runner_argv_is_fixed_and_never_a_shell_command(tmp_path):
    source = inspect.getsource(build_subprocess_verifier_runner)
    assert "shell=False" in source
    assert "shell=True" not in source
    assert "invocation.branch, invocation.base_branch" in source

    runner = build_subprocess_verifier_runner()
    with pytest.raises(ProductionHostBootstrapError) as error:
        runner(
            VerifierInvocation(
                repository_root=tmp_path, branch="main", base_branch="main"
            )
        )
    assert "verify-repo-state.sh" in str(error.value)


# --------------------------------------------------------------------------
# 6. Malformed/incomplete verifier evidence -> zero Scheduler dispatch
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "HEAD_REF=main\nHEAD_SHA=short\nBASE_REF=origin/main\nBASE_SHA="
        + BASE_SHA
        + "\nCHANGED_FILES_BEGIN\nCHANGED_FILES_END\n",
        "HEAD_REF=main\nBASE_REF=origin/main\nBASE_SHA="
        + BASE_SHA
        + "\nCHANGED_FILES_BEGIN\nCHANGED_FILES_END\n",
    ],
)
def test_malformed_verifier_evidence_fails_closed(
    monkeypatch, host_environment, stdout
):
    bootstrap, _ = _build(monkeypatch, host_environment, stdout=stdout)

    with pytest.raises(VerifierStdoutError):
        bootstrap.sources.repository_observation_reader(_descriptor())


def test_malformed_verifier_evidence_produces_zero_scheduler_dispatch(
    monkeypatch, host_environment
):
    bootstrap, _ = _build(monkeypatch, host_environment, stdout="")
    dispatched: list[object] = []
    monkeypatch.setattr(
        phc,
        "build_concrete_runtime_adapters",
        lambda *args, **kwargs: dispatched.append("adapters"),
    )
    monkeypatch.setattr(
        phc,
        "run_single_issue_pilot",
        lambda *args, **kwargs: dispatched.append("dispatch"),
    )

    def reconstruct_stub(handoff_id, **kwargs):
        return bootstrap.sources.repository_observation_reader(_descriptor())

    monkeypatch.setattr(phc, "reconstruct_governed_invocation", reconstruct_stub)
    bindings = bootstrap.governed_resume_bindings(cancelled=lambda: False)

    with pytest.raises(VerifierStdoutError):
        run_governed_resume(["--handoff-id", HANDOFF_ID], bindings=bindings)

    assert dispatched == []


def test_a_blocked_reconstruction_still_performs_zero_dispatch(
    monkeypatch, host_environment
):
    bootstrap, _ = _build(monkeypatch, host_environment)
    dispatched: list[object] = []
    monkeypatch.setattr(
        phc,
        "run_single_issue_pilot",
        lambda *args, **kwargs: dispatched.append("dispatch"),
    )
    monkeypatch.setattr(
        phc,
        "reconstruct_governed_invocation",
        lambda handoff_id, **kwargs: SimpleNamespace(
            status="blocked", reason_codes=("lease-held",), pilot_input=None
        ),
    )
    bindings = bootstrap.governed_resume_bindings(cancelled=lambda: False)

    evidence = run_governed_resume(["--handoff-id", HANDOFF_ID], bindings=bindings)

    assert '"scheduler_dispatch_count":0' in evidence
    assert '"status":"blocked"' in evidence
    assert dispatched == []


# --------------------------------------------------------------------------
# 7. Missing host configuration / evidence bindings fail closed
# --------------------------------------------------------------------------


@pytest.mark.parametrize("missing", REQUIRED_PATH_ENV_VARS)
def test_missing_required_host_path_fails_closed(tmp_path, monkeypatch, missing):
    values = _host_paths(tmp_path)
    values.pop(missing)
    with pytest.raises(ProductionHostBootstrapError) as error:
        load_production_host_configuration(values)
    assert missing in str(error.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_required_host_path_fails_closed(tmp_path, blank):
    values = _host_paths(tmp_path)
    values[LEASE_DIRECTORY_ENV_VAR] = blank
    with pytest.raises(ProductionHostBootstrapError):
        load_production_host_configuration(values)


def test_relative_host_paths_fail_closed(tmp_path):
    values = _host_paths(tmp_path)
    values[REPOSITORY_ROOT_ENV_VAR] = "relative/repository"
    with pytest.raises(ProductionHostBootstrapError):
        load_production_host_configuration(values)


def test_missing_evidence_source_binding_fails_closed(monkeypatch, host_environment):
    with pytest.raises(ProductionHostBootstrapError) as error:
        _build(monkeypatch, host_environment, repository_evidence_reader=None)
    assert "AOS-GCE2F" in str(error.value)


def test_partial_evidence_source_binding_fails_closed(monkeypatch, host_environment):
    partial = SimpleNamespace(read_dependency_evidence=lambda *a: None)
    with pytest.raises(ProductionHostBootstrapError):
        _build(monkeypatch, host_environment, repository_evidence_reader=partial)


def test_missing_issue_transport_fails_closed(monkeypatch, host_environment):
    with pytest.raises(ProductionHostBootstrapError):
        _build(monkeypatch, host_environment, issue_transport=None)


def test_a_diverging_checkpoint_store_root_fails_closed_before_binding(
    monkeypatch, host_environment, tmp_path
):
    bootstrap, _ = _build(monkeypatch, host_environment)
    monkeypatch.setenv(CHECKPOINT_STORE_ROOT_ENV_VAR, str(tmp_path / "other-store"))

    with pytest.raises(ProductionHostBootstrapError) as error:
        bootstrap.governed_resume_bindings(cancelled=lambda: False)
    assert CHECKPOINT_STORE_ROOT_ENV_VAR in str(error.value)


def test_a_naive_host_clock_fails_closed():
    import datetime as datetime_module

    with pytest.raises(ProductionHostBootstrapError):
        canonical_evaluated_at(lambda: datetime_module.datetime(2026, 8, 21, 12, 0, 0))


def test_canonical_evaluated_at_is_canonical_utc_seconds():
    import datetime as datetime_module

    value = canonical_evaluated_at(
        lambda: datetime_module.datetime(
            2026, 8, 21, 12, 0, 0, 123456, tzinfo=datetime_module.timezone.utc
        )
    )
    assert value == "2026-08-21T12:00:00Z"


# --------------------------------------------------------------------------
# 8. Remote argv cannot select any host location
# --------------------------------------------------------------------------


def test_remote_argv_cannot_override_host_configuration():
    """The bootstrap has no argv path at all, and #1238's contract stays frozen."""
    for module in (bootstrap_module, ghread):
        tree = ast.parse(inspect.getsource(module))
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert "argv" not in names
        assert "argparse" not in names

    assert list(inspect.signature(load_production_host_configuration).parameters) == [
        "environ"
    ]

    with pytest.raises(ValueError):
        parse_handoff_argv(
            ["--handoff-id", HANDOFF_ID, "--checkpoint-store-root", "/tmp/evil"]
        )


def test_host_configuration_reads_only_the_supplied_mapping(tmp_path, monkeypatch):
    values = _host_paths(tmp_path)
    monkeypatch.setenv(REPOSITORY_ROOT_ENV_VAR, "/proc/self/root")

    configuration = load_production_host_configuration(values)

    assert configuration.repository_root == tmp_path / "repository"
    assert type(configuration) is ProductionHostConfiguration


# --------------------------------------------------------------------------
# 9. Reconstruction-time and dispatch-time lease directories cannot diverge
# --------------------------------------------------------------------------


def test_reconstruction_and_dispatch_lease_directories_cannot_diverge(
    monkeypatch, host_environment, tmp_path
):
    bootstrap, _ = _build(monkeypatch, host_environment)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        bootstrap_module,
        "build_production_governed_resume_bindings",
        lambda **kwargs: captured.update(kwargs),
    )
    bootstrap.governed_resume_bindings(cancelled=lambda: False)

    # One configured value reaches both the #1303 sources (which bind it into
    # the runtime configuration) and the #1287 composition (which observes and
    # dispatches against it). There is no second lease directory to diverge to.
    assert bootstrap.sources.lease_directory == str(tmp_path / "leases")
    assert captured["lease_directory"] == bootstrap.sources.lease_directory
    assert captured["lease_directory"] == str(bootstrap.configuration.lease_directory)


# --------------------------------------------------------------------------
# 10. Credentials/tokens never reach evidence or diagnostics
# --------------------------------------------------------------------------


def test_credentials_are_not_embedded_in_transport_state_or_diagnostics():
    token = "ghp_notarealtoken0000000000000000000000"

    def read_json(path, parameters):
        raise ghread.HostGitHubReadError(SingleIssueTransportOutcome.PERMISSION_DENIED)

    transport = ghread.HostGitHubReadTransport(read_json=read_json)
    assert token not in repr(transport)
    assert not any("token" in name.lower() for name in ghread.HostGitHubReadTransport.__slots__)

    result = transport.get_issue("Blummer92/agent-os", 1319)
    assert result.item is None
    assert token not in str(result)


def test_missing_token_fails_closed_without_echoing_any_secret():
    with pytest.raises(ghread.HostGitHubTransportUnavailable) as error:
        ghread.build_host_github_read_transport_from_environment({"GITHUB_TOKEN": "  "})
    message = str(error.value)
    assert "GITHUB_TOKEN" in message and "GH_TOKEN" in message
    assert "ghp_" not in message


def test_verifier_failure_diagnostics_carry_only_the_documented_exit_code():
    source = inspect.getsource(build_subprocess_verifier_runner)
    assert "completed.stderr" not in source
    assert "returncode" in source


def test_observation_and_configuration_carry_no_credential_fields():
    observation_fields = set(RepositoryObservation.__dataclass_fields__)
    configuration_fields = set(ProductionHostConfiguration.__dataclass_fields__)
    for name in observation_fields | configuration_fields:
        assert not any(
            marker in name.lower()
            for marker in ("token", "secret", "password", "credential", "api_key")
        )


# --------------------------------------------------------------------------
# 11. A missing bootstrap preserves the existing fail-closed #1238 behaviour
# --------------------------------------------------------------------------


def test_missing_production_bootstrap_preserves_1238_fail_closed_behaviour(capsys):
    with pytest.raises(RuntimeError) as error:
        entrypoint_main(["--handoff-id", HANDOFF_ID])
    assert "host-supplied" in str(error.value)
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------
# 12./13. No second architecture, and no live effects from normal tests
# --------------------------------------------------------------------------


def _module_imports(module) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append("." * node.level + node.module)
    return names


def _top_level_imports(module) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("module", [bootstrap_module, ghread])
def test_no_live_network_process_or_cloud_import_at_module_scope(module):
    forbidden = (
        "subprocess",
        "socket",
        "http",
        "requests",
        "httpx",
        "github",
        "google.cloud",
        "paramiko",
    )
    assert not [
        name for name in _top_level_imports(module) if name.startswith(forbidden)
    ]


def test_no_second_scheduler_store_lease_or_authority_is_introduced():
    """Every governing owner is imported, never redefined."""
    tree = ast.parse(inspect.getsource(bootstrap_module))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
    }
    forbidden_markers = (
        "scheduler",
        "lease",
        "checkpoint_store",
        "descriptor_store",
        "queue",
        "router",
        "retry",
        "authoriz",
        "reconstruct",
        "dispatch",
    )
    assert not [
        name
        for name in defined
        if any(marker in name.lower() for marker in forbidden_markers)
    ]

    imported = _module_imports(bootstrap_module)
    assert "agent_os_execution_service.production_host_composition" not in defined
    for owner in (
        ".production_host_composition",
        ".production_host_state_sources",
        ".governed_resume_restart_capsule",
        ".execution_authorization_source",
        ".governed_resume_entrypoint",
        "scripts.agent_os_candidate_packet_live_input",
    ):
        assert owner in imported


def test_bootstrap_owns_no_write_surface():
    for module in (bootstrap_module, ghread):
        source = inspect.getsource(module)
        for marker in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"', "write_text", "mkdir"):
            assert marker not in source
