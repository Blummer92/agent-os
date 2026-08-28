"""Repository-owned production host bootstrap for governed resume (#1319).

This module is the single boundary that turns *trusted host state* into the
already-merged composition below it. It owns nothing else:

```text
/usr/local/libexec/agent-os-governed-resume
-> fixed argv parser (#1238)
-> this bootstrap                                   (composition only)
-> ProductionHostStateSources (#1303)               (current-state semantics)
-> build_production_governed_resume_bindings (#1287)(reconstruct/dispatch)
-> existing #1218/#1253 reconstruction/currentness
-> existing Workflow Scheduler
```

No second Scheduler, reconstruction engine, authorization model, store, lease
system, checkpoint system, router, retry authority, transport control plane, or
execution authority is introduced here. Every semantic decision stays with its
existing canonical owner:

- issue normalization -> ``LiveIssueReader`` (#1155);
- dependency/validation evidence -> the AOS-GCE2F (#1320) reader the host
  supplies (``LiveRepositoryEvidenceReader``), which this module requires and
  never substitutes for;
- ``RequiredEnvironmentSpec`` recovery -> ``build_required_environment_spec_reader``
  (#1320) over the one existing restart-capsule seam;
- authorization -> ``reacquire_execution_authorization(...)`` (unchanged),
  reached through an injected read-only transport;
- Git state -> ``scripts/verify-repo-state.sh`` plus the canonical
  ``build_repository_observation_from_verifier_stdout(...)`` assembler;
- currentness/admission -> #1218/#1253; concurrency -> the Scheduler lease.

**Configuration is host state, never caller input.** ``sys.argv``, issue text,
issue-comment text, and handoff payloads are never consulted for a path, a
store root, a lease directory, or a cgroup: the frozen #1238 argv contract
carries exactly one ``--handoff-id`` and nothing on this path can widen it.
Static host locations come only from the process environment, extending the
existing ``AGENT_OS_CHECKPOINT_STORE_ROOT`` convention already used by
``production_host_composition`` and
``scripts/agent_os_execution_interface/hook_adapter.py`` -- the same
configuration source of truth, not a new one.

Missing, malformed, conflicting, or ambiguous host input fails closed *before*
``GovernedResumeBindings`` are ever constructed, so the preserved invariant
holds: a bad bootstrap performs zero Scheduler dispatches.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from scripts.agent_os_candidate_packet.repository_stage import RepositoryObservation
from scripts.agent_os_candidate_packet_live_input import (
    LiveIssueReader,
    SingleIssueTransport,
    build_repository_observation_from_verifier_stdout,
)
from scripts.agent_os_execution_capabilities import (
    RepositoryEvidenceType,
    RepositoryIdentity,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    GovernedInvocationDescriptor,
)
from workflow_scheduler.execution.concrete_runtime_adapters import (
    ChangedPathsInspector,
    ProcessCancellationCheck,
)
from workflow_scheduler.execution.dependency_preparation import DependencyCommandRunner
from workflow_scheduler.execution.git_worktree_adapter import GitRunner
from workflow_scheduler.execution.single_issue_pilot import CancellationProbe

from .execution_authorization_source import ExecutionAuthorizationSourceTransport
from .governed_resume_entrypoint import GovernedResumeBindings
from .governed_resume_restart_capsule import (
    build_required_environment_spec_reader,
    load_restart_capsule,
)
from .models import parse_canonical_utc
from .production_host_composition import (
    CHECKPOINT_STORE_ROOT_ENV_VAR,
    build_production_governed_resume_bindings,
)
from .production_host_state_sources import (
    DependencyIdentityEvidenceReader,
    ProductionHostStateSources,
    RepositoryObservationReader,
)

#: Static host locations. ``AGENT_OS_CHECKPOINT_STORE_ROOT`` is the existing
#: variable ``production_host_composition`` already binds; the rest follow the
#: same convention rather than opening a second configuration source of truth.
REPOSITORY_ROOT_ENV_VAR = "AGENT_OS_REPOSITORY_ROOT"
WORKSPACE_PARENT_ENV_VAR = "AGENT_OS_WORKSPACE_PARENT"
LEASE_DIRECTORY_ENV_VAR = "AGENT_OS_LEASE_DIRECTORY"
#: Optional: the already-qualified delegated cgroup #1238's wrapper establishes.
DELEGATED_PARENT_CGROUP_ENV_VAR = "AGENT_OS_DELEGATED_PARENT_CGROUP"
#: Optional: the Git host of the governed repository (GHES/forks).
REPOSITORY_HOST_ENV_VAR = "AGENT_OS_REPOSITORY_HOST"
DEFAULT_REPOSITORY_HOST = "github.com"

REQUIRED_PATH_ENV_VARS = (
    CHECKPOINT_STORE_ROOT_ENV_VAR,
    REPOSITORY_ROOT_ENV_VAR,
    WORKSPACE_PARENT_ENV_VAR,
    LEASE_DIRECTORY_ENV_VAR,
)

#: The canonical verifier, resolved under the configured repository root only.
VERIFIER_RELATIVE_PATH = "scripts/verify-repo-state.sh"
VERIFIER_TIMEOUT_SECONDS = 300

PRODUCER_ADAPTER = "agent-os-governed-resume-host-bootstrap"
PRODUCER_ADAPTER_VERSION = "1.0"


class ProductionHostBootstrapError(RuntimeError):
    """Raised when trusted host state cannot compose governed resume safely."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionHostConfiguration:
    """Static host locations, bound from host state only.

    Every path must be absolute: a relative path would make the bound location
    depend on the process working directory, which is not trusted host state.
    """

    checkpoint_store_root: Path
    repository_root: Path
    workspace_parent: Path
    lease_directory: Path
    delegated_parent_cgroup: Path | None
    repository_host: str

    def __post_init__(self) -> None:
        for name in (
            "checkpoint_store_root",
            "repository_root",
            "workspace_parent",
            "lease_directory",
        ):
            _absolute_path(getattr(self, name), name)
        if self.delegated_parent_cgroup is not None:
            _absolute_path(self.delegated_parent_cgroup, "delegated_parent_cgroup")
        host = self.repository_host
        if type(host) is not str or not host.strip() or host != host.strip():
            raise ProductionHostBootstrapError("repository_host must be canonical text")


def load_production_host_configuration(
    environ: Mapping[str, str] | None = None,
) -> ProductionHostConfiguration:
    """Bind the static host locations from the process environment only.

    ``environ`` exists so offline tests can supply a controlled mapping; there
    is no argv, issue-text, handoff-payload, or working-directory path into
    this function, and no value is defaulted or invented. A missing or blank
    required variable fails closed and names the variable.
    """
    source = os.environ if environ is None else environ
    values: dict[str, str] = {}
    for name in REQUIRED_PATH_ENV_VARS:
        raw = source.get(name)
        if raw is None or not str(raw).strip():
            raise ProductionHostBootstrapError(
                f"{name} must be set to an absolute host path; production "
                "governed-resume bootstrap refuses to invent or default a location"
            )
        values[name] = str(raw)
    cgroup = source.get(DELEGATED_PARENT_CGROUP_ENV_VAR)
    host = source.get(REPOSITORY_HOST_ENV_VAR)
    return ProductionHostConfiguration(
        checkpoint_store_root=Path(values[CHECKPOINT_STORE_ROOT_ENV_VAR]),
        repository_root=Path(values[REPOSITORY_ROOT_ENV_VAR]),
        workspace_parent=Path(values[WORKSPACE_PARENT_ENV_VAR]),
        lease_directory=Path(values[LEASE_DIRECTORY_ENV_VAR]),
        delegated_parent_cgroup=(
            None if cgroup is None or not str(cgroup).strip() else Path(str(cgroup))
        ),
        repository_host=(
            DEFAULT_REPOSITORY_HOST if host is None or not str(host).strip() else str(host)
        ),
    )


def canonical_evaluated_at(now: Callable[[], datetime] | None = None) -> str:
    """Produce the one bootstrap-time ``evaluated_at`` in canonical UTC seconds.

    Time comes from the host clock at bootstrap, never from argv, issue text,
    a handoff payload, or any other caller-controlled input. ``now`` exists so
    offline tests can pin the clock; a naive datetime fails closed rather than
    being assumed to be UTC.
    """
    clock = (lambda: datetime.now(timezone.utc)) if now is None else now
    moment = clock()
    if type(moment) is not datetime or moment.tzinfo is None:
        raise ProductionHostBootstrapError(
            "the host clock must supply a timezone-aware datetime"
        )
    value = moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parse_canonical_utc(value)
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifierInvocation:
    """The bounded request handed to ``scripts/verify-repo-state.sh``.

    Only a repository root and two branch names -- never a command, never an
    argv fragment, never a caller-controlled root.
    """

    repository_root: Path
    branch: str
    base_branch: str


#: Runs the canonical verifier once and returns its stdout capture.
VerifierRunner = Callable[[VerifierInvocation], str]


def build_subprocess_verifier_runner(
    *, timeout_seconds: int = VERIFIER_TIMEOUT_SECONDS
) -> VerifierRunner:
    """Return the production runner for the canonical ``verify-repo-state.sh``.

    Git state is never reimplemented here: the script is the only thing that
    runs Git, and this runner only executes it with a fixed argv (no shell, no
    caller-supplied command, no caller-supplied root) and returns its stdout.
    ``subprocess`` is imported locally so importing this module -- which offline
    tests do -- pulls in no process machinery.
    """
    import subprocess

    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
        raise ProductionHostBootstrapError("timeout_seconds must be an int from 1 to 3600")

    def run(invocation: VerifierInvocation) -> str:
        if type(invocation) is not VerifierInvocation:
            raise ProductionHostBootstrapError("invocation must be a VerifierInvocation")
        script = invocation.repository_root / VERIFIER_RELATIVE_PATH
        if not script.is_file():
            raise ProductionHostBootstrapError(
                f"the canonical repository-state verifier is missing at "
                f"{VERIFIER_RELATIVE_PATH} under the configured repository root"
            )
        completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False
            [str(script), invocation.branch, invocation.base_branch],
            cwd=str(invocation.repository_root),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            # Only the documented exit code is reported. Verifier stderr is
            # host-local logging and never enters governed evidence.
            raise ProductionHostBootstrapError(
                "canonical repository-state verifier exited "
                f"{completed.returncode}; see scripts/verify-repo-state-contract.md"
            )
        return completed.stdout

    return run


def build_repository_observation_reader(
    *,
    configuration: ProductionHostConfiguration,
    evaluated_at: str,
    run_verifier: VerifierRunner,
) -> RepositoryObservationReader:
    """Return the #1303 ``RepositoryObservationReader`` over the canonical verifier.

    The branch pair handed to the verifier comes from the trusted restart
    capsule (#1303/#1320), never from argv or issue text: the observation
    #1303 consumes supplies ``evaluated_repository_sha`` for the base branch
    the governed invocation is pinned to, so the verifier is asked for that
    base branch.

    Every field the canonical assembler leaves to the caller is bound from an
    existing canonical owner and nothing is invented:

    - ``correlation_id`` -> the descriptor's ``invocation_id``;
    - ``repository_identity`` -> the descriptor's repository plus the
      configured Git host;
    - ``contract_fingerprint`` -> the approval record's
      ``implementation_contract_fingerprint`` (the value the repository stage
      already validates against);
    - ``freshness_boundary`` -> the candidate packet's own boundary;
    - ``requested_ref``/``requested_sha`` -> the base branch and base SHA the
      candidate packet is pinned to, so live base drift fails closed;
    - ``tested_sha``/``pushed_sha``/``proposed_pr_sha``/``synthetic_merge_sha``
      -> ``None``: the verifier does not observe them, and absence is stated
      rather than inferred.
    """
    if type(configuration) is not ProductionHostConfiguration:
        raise ProductionHostBootstrapError(
            "configuration must be an exact ProductionHostConfiguration"
        )
    parse_canonical_utc(evaluated_at)
    if not callable(run_verifier):
        raise ProductionHostBootstrapError("run_verifier must be callable")

    def read(descriptor: GovernedInvocationDescriptor) -> RepositoryObservation:
        if type(descriptor) is not GovernedInvocationDescriptor:
            raise ProductionHostBootstrapError(
                "descriptor must be an exact GovernedInvocationDescriptor"
            )
        capsule = load_restart_capsule(
            configuration.checkpoint_store_root, descriptor.handoff_id
        )
        packet = capsule.candidate_packet
        stdout = run_verifier(
            VerifierInvocation(
                repository_root=configuration.repository_root,
                branch=packet.base_branch,
                base_branch=packet.base_branch,
            )
        )
        if type(stdout) is not str:
            raise ProductionHostBootstrapError(
                "the repository-state verifier runner must return stdout text"
            )
        return build_repository_observation_from_verifier_stdout(
            stdout,
            producer_adapter=PRODUCER_ADAPTER,
            producer_adapter_version=PRODUCER_ADAPTER_VERSION,
            correlation_id=descriptor.invocation_id,
            repository_identity=_repository_identity(
                descriptor.repository,
                host=configuration.repository_host,
                default_branch=packet.base_branch,
            ),
            contract_fingerprint=capsule.approval_record.binding.implementation_contract_fingerprint,
            observed_at=evaluated_at,
            freshness_boundary=packet.freshness_boundary,
            evidence_type=RepositoryEvidenceType.BRANCH_HEAD,
            requested_ref=packet.base_branch,
            requested_sha=packet.base_sha,
            tested_sha=None,
            pushed_sha=None,
            proposed_pr_sha=None,
            synthetic_merge_sha=None,
            external_build_sha=packet.external_build_sha,
        )

    return read


class _InvocationRuntimeConfigurationBinding:
    """Hand #1287 back the exact configuration #1303 already reacquired.

    ``build_production_governed_resume_bindings`` calls its
    ``runtime_configuration_provider`` with the admitted pilot input only,
    while ``ProductionHostStateSources.runtime_configuration`` is called
    earlier with the descriptor and the candidate packet. This records the
    object the canonical builder returned during reconstruction and returns
    that same object at dispatch time.

    It builds nothing, persists nothing, and adds no second runtime
    configuration owner: #1287 still verifies the object against the admitted
    pilot input and against the bound lease directory before any dispatch.
    """

    __slots__ = ("_build", "_configuration")

    def __init__(self, build: Callable[..., object]) -> None:
        if not callable(build):
            raise ProductionHostBootstrapError("runtime configuration builder must be callable")
        self._build = build
        self._configuration: object | None = None

    def build(self, descriptor: object, candidate_packet: object) -> object:
        configuration = self._build(descriptor, candidate_packet)
        self._configuration = configuration
        return configuration

    def provide(self, pilot_input: object) -> object:
        del pilot_input
        if self._configuration is None:
            raise ProductionHostBootstrapError(
                "no runtime configuration was reacquired during reconstruction; "
                "refusing to dispatch"
            )
        return self._configuration


from .runtime_execution_request import RuntimeExecutionRequest

@dataclass(frozen=True, slots=True, kw_only=True)
class ProductionHostBootstrap:
    """One composed production host binding for exactly one host process."""

    configuration: ProductionHostConfiguration
    evaluated_at: str
    sources: ProductionHostStateSources
    authorization_transport: ExecutionAuthorizationSourceTransport
    runtime_request: RuntimeExecutionRequest | None = None

    def governed_resume_bindings(
        self,
        *,
        cancelled: CancellationProbe,
        git_runner: GitRunner | None = None,
        process_cancelled: ProcessCancellationCheck | None = None,
        changed_paths_inspector: ChangedPathsInspector | None = None,
        dependency_command_runner: DependencyCommandRunner | None = None,
    ) -> GovernedResumeBindings:
        """Compose the existing #1287 production bindings from this bootstrap.

        The seven #1303 source methods are passed through unchanged -- none is
        reimplemented here -- and the one host-local lease directory is the
        same value the sources were bound to, so the reconstruction-time lease
        observation and the dispatch-time lease adapter cannot diverge.
        """
        environment_root = os.environ.get(CHECKPOINT_STORE_ROOT_ENV_VAR)
        if environment_root is None or Path(environment_root) != self.configuration.checkpoint_store_root:
            raise ProductionHostBootstrapError(
                f"{CHECKPOINT_STORE_ROOT_ENV_VAR} does not match the bound host "
                "checkpoint store root; refusing to compose two store locations"
            )
        binding = _InvocationRuntimeConfigurationBinding(self.sources.runtime_configuration)
        return build_production_governed_resume_bindings(
            lease_directory=str(self.configuration.lease_directory),
            route_decision_reader=self.sources.route_decision,
            handoff_reader=self.sources.handoff,
            checkpoint_reader=self.sources.checkpoint,
            resume_plan_reader=self.sources.resume_plan,
            candidate_packet_rebuilder=self.sources.candidate_packet,
            runtime_configuration_builder=binding.build,
            pilot_input_builder=self.sources.pilot_input,
            authorization_transport=self.authorization_transport,
            runtime_configuration_provider=binding.provide,
            evaluated_at=self.evaluated_at,
            cancelled=cancelled,
            git_runner=git_runner,
            process_cancelled=process_cancelled,
            changed_paths_inspector=changed_paths_inspector,
            dependency_command_runner=dependency_command_runner,
            runtime_request=self.runtime_request,
        )


def build_production_host_bootstrap(
    *,
    issue_transport: SingleIssueTransport,
    authorization_transport: ExecutionAuthorizationSourceTransport,
    repository_evidence_reader: object,
    run_verifier: VerifierRunner,
    configuration: ProductionHostConfiguration | None = None,
    evaluated_at: str | None = None,
    dependency_identity_evidence_reader: DependencyIdentityEvidenceReader | None = None,
    runtime_request: RuntimeExecutionRequest | None = None,
) -> ProductionHostBootstrap:
    """Compose #1303's ``ProductionHostStateSources`` from trusted host state.

    ``repository_evidence_reader`` is required and is the AOS-GCE2F (#1320)
    ``LiveRepositoryEvidenceReader`` (or another canonical
    ``RepositoryEvidenceReader``). This module deliberately supplies no default
    and no substitute: what structured dependency/validation evidence *means*
    is AOS-GCE2F's source-of-truth problem, and a bootstrap that quietly
    invented an evidence source would be exactly the second source of truth
    #1319 forbids. An absent binding fails closed here, before any Scheduler
    dispatch is reachable.
    """
    bound = load_production_host_configuration() if configuration is None else configuration
    if type(bound) is not ProductionHostConfiguration:
        raise ProductionHostBootstrapError(
            "configuration must be an exact ProductionHostConfiguration"
        )
    moment = canonical_evaluated_at() if evaluated_at is None else evaluated_at
    parse_canonical_utc(moment)

    if issue_transport is None or not callable(getattr(issue_transport, "get_issue", None)):
        raise ProductionHostBootstrapError(
            "issue_transport must satisfy the read-only SingleIssueTransport protocol"
        )
    if not isinstance(authorization_transport, ExecutionAuthorizationSourceTransport):
        raise ProductionHostBootstrapError(
            "authorization_transport must satisfy ExecutionAuthorizationSourceTransport"
        )
    if repository_evidence_reader is None or not all(
        callable(getattr(repository_evidence_reader, name, None))
        for name in ("read_dependency_evidence", "read_validation_evidence")
    ):
        raise ProductionHostBootstrapError(
            "repository_evidence_reader must satisfy the canonical "
            "RepositoryEvidenceReader protocol delivered by AOS-GCE2F (#1320); "
            "governed-resume bootstrap refuses to invent a second evidence source"
        )

    sources = ProductionHostStateSources(
        checkpoint_store_root=bound.checkpoint_store_root,
        issue_reader=LiveIssueReader(transport=issue_transport),
        repository_reader=repository_evidence_reader,
        repository_observation_reader=build_repository_observation_reader(
            configuration=bound,
            evaluated_at=moment,
            run_verifier=run_verifier,
        ),
        required_environment_spec_reader=build_required_environment_spec_reader(
            bound.checkpoint_store_root
        ),
        evaluated_at=moment,
        repository_root=bound.repository_root,
        workspace_parent=bound.workspace_parent,
        lease_directory=bound.lease_directory,
        delegated_parent_cgroup=bound.delegated_parent_cgroup,
        dependency_identity_evidence_reader=dependency_identity_evidence_reader,
        runtime_request=runtime_request,
    )
    return ProductionHostBootstrap(
        configuration=bound,
        evaluated_at=moment,
        sources=sources,
        authorization_transport=authorization_transport,
        runtime_request=runtime_request,
    )


def _absolute_path(value: object, name: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ProductionHostBootstrapError(f"{name} must be an absolute Path")
    return value


def _repository_identity(
    repository: str, *, host: str, default_branch: str
) -> RepositoryIdentity:
    """Build the identity from the descriptor's repository and host state only."""
    if type(repository) is not str or repository.count("/") != 1:
        raise ProductionHostBootstrapError("descriptor repository must be owner/name text")
    owner, _, name = repository.partition("/")
    if not owner or not name:
        raise ProductionHostBootstrapError("descriptor repository must be owner/name text")
    return RepositoryIdentity(
        host=host,
        owner=owner,
        repository=name,
        default_branch=default_branch,
    )
