from __future__ import annotations

import posixpath
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from scripts.agent_os_execution_capabilities.dependencies import (
    DependencyCacheState,
    DependencyEcosystem,
    DependencyInstallMode,
    DependencyPreparationStatus,
    DependencyReadinessEvidence,
    ReproducibilityLevel,
    RequiredEnvironmentSpec,
)

UNDECLARED_PACKAGE_SOURCE = "dependency.undeclared-package-source"
UNDECLARED_LOCAL_PROJECT = "dependency.undeclared-local-project"
UNSUPPORTED_SOURCE_INDIRECTION = "dependency.unsupported-source-indirection"
POST_PREPARATION_DRIFT = "dependency.post-preparation-drift"

# v1 represents exactly one package source (``approved_source_identity``) plus
# structurally declared local projects. Every requirements-file directive that
# could add, replace, or indirect a package source is therefore unrepresentable
# and must fail closed rather than be delegated to pip.
_SOURCE_OPTION_PREFIXES = (
    "-i",
    "--index-url",
    "--extra-index-url",
    "-f",
    "--find-links",
    "--no-index",
    "--trusted-host",
    "--pre",
    "--use-feature",
    "--use-deprecated",
    "--no-binary",
    "--only-binary",
    "--prefer-binary",
    "--config-settings",
    "--global-option",
    "--install-option",
)
_INDIRECTION_OPTION_PREFIXES = ("-r", "--requirement", "-c", "--constraint")
_VCS_SCHEMES = ("git+", "hg+", "bzr+", "svn+", "git:", "svn:")
_URL_SCHEMES = ("http://", "https://", "ftp://", "file:")
_ARCHIVE_SUFFIXES = (".whl", ".tar.gz", ".tgz", ".zip", ".tar.bz2", ".tar.xz")


def source_location(approved_source_identity: str) -> str:
    """Return the concrete package-source location for one approved identity.

    ``approved_source_identity`` is frozen by ``RequiredEnvironmentSpec``. This
    only makes the identity usable as an explicit package-manager argument; it
    never widens, defaults, or substitutes the approved source.
    """
    if type(approved_source_identity) is not str or not approved_source_identity:
        raise TypeError("approved_source_identity must be non-empty exact text")
    if "://" in approved_source_identity:
        return approved_source_identity
    return f"https://{approved_source_identity}"


def _canonical_project_path(raw: str) -> str:
    """Normalize a manifest-supplied local path to the frozen contract's form."""
    text = raw.strip().rstrip("/")
    if text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or "\\" in text:
        return ""
    normalized = posixpath.normpath(text)
    return "" if normalized in (".", "..") or normalized.startswith("..") else normalized


def _logical_requirement_lines(text: str) -> tuple[str, ...]:
    """Join pip line continuations and drop comments and blank lines."""
    joined: list[str] = []
    buffer = ""
    for raw_line in text.splitlines():
        line = buffer + raw_line
        buffer = ""
        if line.endswith("\\"):
            buffer = line[:-1]
            continue
        joined.append(line)
    if buffer:
        joined.append(buffer)
    lines: list[str] = []
    for line in joined:
        without_comment = line.split(" #", 1)[0]
        if without_comment.lstrip().startswith("#"):
            continue
        stripped = without_comment.strip()
        if stripped:
            lines.append(stripped)
    return tuple(lines)


def _declared_local_projects(
    spec: RequiredEnvironmentSpec,
) -> dict[str, bool]:
    return {
        requirement.relative_path: requirement.editable
        for requirement in spec.local_project_requirements
    }


def _split_option(line: str) -> tuple[str, str]:
    """Split one requirements-file option into its name and its argument."""
    head, separator, tail = line.partition("=")
    if separator and " " not in head:
        return head.strip(), tail.strip()
    parts = line.split(None, 1)
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


def _looks_like_local_path(value: str) -> bool:
    return value.startswith((".", "/")) or "/" in value.split("[", 1)[0]


def validate_python_requirements_source_forms(
    text: str, spec: RequiredEnvironmentSpec
) -> tuple[str, ...]:
    """Prove every requirements-file directive is representable by the v1 contract.

    Raw manifest text may not introduce a package source, a local project, or a
    source indirection that ``RequiredEnvironmentSpec`` does not already declare.
    Returns bounded reason codes; an empty tuple means every directive is
    structurally represented.
    """
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(text) is not str:
        raise TypeError("text must be exact str")
    declared = _declared_local_projects(spec)
    reasons: set[str] = set()
    for line in _logical_requirement_lines(text):
        if "${" in line or "$(" in line or "%(" in line:
            reasons.add(UNDECLARED_PACKAGE_SOURCE)
            continue
        if line.startswith("-"):
            option, target = _split_option(line)
            if option in ("-e", "--editable"):
                reasons.update(_editable_reasons(target, declared))
                continue
            if option in _INDIRECTION_OPTION_PREFIXES:
                reasons.add(UNSUPPORTED_SOURCE_INDIRECTION)
                continue
            if option in _SOURCE_OPTION_PREFIXES:
                reasons.add(UNDECLARED_PACKAGE_SOURCE)
                continue
            reasons.add(UNSUPPORTED_SOURCE_INDIRECTION)
            continue
        reasons.update(_requirement_reasons(line, declared))
    return tuple(sorted(reasons))


def _editable_reasons(target: str, declared: dict[str, bool]) -> tuple[str, ...]:
    if not target:
        return (UNSUPPORTED_SOURCE_INDIRECTION,)
    if target.startswith(_VCS_SCHEMES) or target.startswith(_URL_SCHEMES):
        return (UNDECLARED_PACKAGE_SOURCE,)
    canonical = _canonical_project_path(target)
    if not canonical or declared.get(canonical) is not True:
        return (UNDECLARED_LOCAL_PROJECT,)
    return ()


def _requirement_reasons(line: str, declared: dict[str, bool]) -> tuple[str, ...]:
    candidate = line
    if " @ " in candidate:
        candidate = candidate.split(" @ ", 1)[1].strip()
    if candidate.startswith(_VCS_SCHEMES):
        return (UNDECLARED_PACKAGE_SOURCE,)
    if candidate.startswith(_URL_SCHEMES):
        return (UNDECLARED_PACKAGE_SOURCE,)
    if candidate.split("#", 1)[0].split(";", 1)[0].strip().endswith(_ARCHIVE_SUFFIXES):
        return (UNDECLARED_PACKAGE_SOURCE,)
    if _looks_like_local_path(candidate):
        canonical = _canonical_project_path(candidate.split(";", 1)[0])
        if not canonical or canonical not in declared:
            return (UNDECLARED_LOCAL_PROJECT,)
        if declared[canonical]:
            # Declared editable projects must enter through an ``-e`` directive so
            # editable-mode authorization stays structural rather than inferred.
            return (UNDECLARED_LOCAL_PROJECT,)
    return ()


def _npm_registry_host(spec: RequiredEnvironmentSpec) -> str:
    identity = spec.approved_source_identity
    location = identity if "://" in identity else f"https://{identity}"
    return urlsplit(location).netloc.casefold()


def validate_npm_lock_source_forms(
    payload: object, spec: RequiredEnvironmentSpec
) -> tuple[str, ...]:
    """Prove every npm lockfile entry resolves to the approved source or a declared project.

    Registry tarballs must come from ``approved_source_identity``; git, remote
    tarball, ``file:``, ``link:``, and directory forms are rejected unless the
    entry is one of the structurally declared local projects.
    """
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(payload) is not dict:
        return (UNDECLARED_PACKAGE_SOURCE,)
    declared = set(_declared_local_projects(spec))
    approved_host = _npm_registry_host(spec)
    reasons: set[str] = set()
    packages = payload.get("packages")
    if type(packages) is dict:
        for key, entry in packages.items():
            if type(key) is not str or type(entry) is not dict:
                reasons.add(UNDECLARED_PACKAGE_SOURCE)
                continue
            if key == "":
                continue
            reasons.update(
                _npm_entry_reasons(key, entry, declared, approved_host, spec)
            )
    legacy = payload.get("dependencies")
    if type(legacy) is dict:
        reasons.update(_npm_legacy_reasons(legacy, approved_host))
    if packages is None and legacy is None:
        reasons.add(UNDECLARED_PACKAGE_SOURCE)
    return tuple(sorted(reasons))


def _npm_declared_local(key: str, spec: RequiredEnvironmentSpec, declared: set[str]) -> bool:
    canonical = _canonical_project_path(key)
    if not canonical:
        return False
    if canonical in declared:
        return True
    root = "" if spec.package_root == "." else spec.package_root
    return bool(root) and posixpath.join(root, canonical) in declared


def _npm_entry_reasons(
    key: str,
    entry: dict,
    declared: set[str],
    approved_host: str,
    spec: RequiredEnvironmentSpec,
) -> tuple[str, ...]:
    if entry.get("link") is True or key.startswith("../"):
        return (
            ()
            if _npm_declared_local(str(entry.get("resolved") or key), spec, declared)
            else (UNDECLARED_LOCAL_PROJECT,)
        )
    resolved = entry.get("resolved")
    if resolved is None:
        # A registry dependency always records ``resolved``; an entry without one
        # is a directory/workspace form that must be structurally declared.
        return () if _npm_declared_local(key, spec, declared) else (UNDECLARED_LOCAL_PROJECT,)
    if type(resolved) is not str or not resolved:
        return (UNDECLARED_PACKAGE_SOURCE,)
    if resolved.startswith(("file:", "link:")):
        return (
            ()
            if _npm_declared_local(resolved.split(":", 1)[1], spec, declared)
            else (UNDECLARED_LOCAL_PROJECT,)
        )
    if resolved.startswith(_VCS_SCHEMES) or resolved.startswith("git+ssh://"):
        return (UNDECLARED_PACKAGE_SOURCE,)
    return _npm_remote_reasons(resolved, approved_host)


def _npm_remote_reasons(resolved: str, approved_host: str) -> tuple[str, ...]:
    parts = urlsplit(resolved)
    if parts.scheme != "https" or parts.netloc.casefold() != approved_host:
        return (UNDECLARED_PACKAGE_SOURCE,)
    return ()


def _npm_legacy_reasons(node: dict, approved_host: str) -> tuple[str, ...]:
    reasons: set[str] = set()
    for entry in node.values():
        if type(entry) is not dict:
            reasons.add(UNDECLARED_PACKAGE_SOURCE)
            continue
        resolved = entry.get("resolved")
        if type(resolved) is str and resolved:
            if resolved.startswith(_VCS_SCHEMES) or resolved.startswith(
                ("file:", "link:", "git+ssh://")
            ):
                reasons.add(UNDECLARED_PACKAGE_SOURCE)
            else:
                reasons.update(_npm_remote_reasons(resolved, approved_host))
        nested = entry.get("dependencies")
        if type(nested) is dict:
            reasons.update(_npm_legacy_reasons(nested, approved_host))
    return tuple(sorted(reasons))


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyPreparationObservation:
    execution_surface_id: str
    workspace_identity: str
    source_sha: str
    environment_health_evidence_id: str
    environment_health_current: bool
    runtime_version: str | None
    runtime_compatible: bool
    package_manager_version: str | None
    manifest_matches: bool
    lock_matches: bool | None
    source_identity_matches: bool
    source_reachable: bool
    package_available: bool
    cache_state: DependencyCacheState
    local_projects_match: bool = False
    source_form_reason_codes: tuple[str, ...] = ()
    offline_source_identity: str | None = None
    offline_source_location: str | None = None
    existing_ready_evidence: DependencyReadinessEvidence | None = None

    def __post_init__(self) -> None:
        if type(self.environment_health_current) is not bool:
            raise TypeError("environment_health_current must be exact bool")
        if type(self.local_projects_match) is not bool:
            raise TypeError("local_projects_match must be exact bool")
        if type(self.source_form_reason_codes) is not tuple or any(
            type(code) is not str or not code
            for code in self.source_form_reason_codes
        ):
            raise TypeError(
                "source_form_reason_codes must be an exact tuple of non-empty strings"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyPreparationPlan:
    status: DependencyPreparationStatus
    argv: tuple[str, ...] | None
    source_identity: str
    cache_state: DependencyCacheState
    reason_codes: tuple[str, ...] = ()
    post_success_status: DependencyPreparationStatus = DependencyPreparationStatus.READY


@dataclass(frozen=True, slots=True, kw_only=True)
class DependencyCommandObservation:
    attempted: bool
    succeeded: bool
    resolved_dependency_identity: str | None = None
    failure_reason_code: str | None = None


class DependencyCommandRunner(Protocol):
    def run(
        self, argv: tuple[str, ...], *, workspace_identity: str
    ) -> DependencyCommandObservation: ...


class DependencyPreparationObservationProvider(Protocol):
    def observe(
        self,
        *,
        workspace_identity: str,
        existing_ready_evidence: DependencyReadinessEvidence | None,
    ) -> DependencyPreparationObservation: ...


@runtime_checkable
class DependencyPreparationAdapter(Protocol):
    """One task-scoped readiness/preparation seam owned by the Scheduler runtime."""

    def prepare(self, *, workspace_identity: str) -> DependencyReadinessEvidence: ...

    def requires_recheck(self, changed_paths: tuple[str, ...]) -> bool: ...


class BoundDependencyPreparationAdapter:
    """Bind one frozen environment spec to observation and command adapters.

    This adapter performs no retry. A second ``prepare`` call is permitted only
    after dependency inputs changed and therefore represents a new readiness
    state, not a retry of the prior attempt.
    """

    def __init__(
        self,
        *,
        spec: RequiredEnvironmentSpec,
        observations: DependencyPreparationObservationProvider,
        runner: DependencyCommandRunner,
        evaluated_at: str,
        expires_at: str,
    ) -> None:
        if type(spec) is not RequiredEnvironmentSpec:
            raise TypeError("spec must be exact RequiredEnvironmentSpec")
        self._spec = spec
        self._observations = observations
        self._runner = runner
        self._evaluated_at = evaluated_at
        self._expires_at = expires_at
        self._last_ready: DependencyReadinessEvidence | None = None
        self._attempts = 0

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def last_ready_evidence(self) -> DependencyReadinessEvidence | None:
        return self._last_ready

    def prepare(self, *, workspace_identity: str) -> DependencyReadinessEvidence:
        if self._attempts >= 2:
            raise RuntimeError(
                "dependency preparation may run only for initial readiness and one changed-input recheck"
            )
        self._attempts += 1
        observation = self._observations.observe(
            workspace_identity=workspace_identity,
            existing_ready_evidence=self._last_ready,
        )
        if type(observation) is not DependencyPreparationObservation:
            raise TypeError(
                "dependency observation provider must return DependencyPreparationObservation"
            )
        if observation.workspace_identity != workspace_identity:
            raise ValueError("dependency observation workspace identity drifted")
        evidence = execute_dependency_preparation(
            self._spec,
            observation,
            self._runner,
            evaluated_at=self._evaluated_at,
            expires_at=self._expires_at,
        )
        if evidence.preparation_status is DependencyPreparationStatus.READY:
            self._last_ready = evidence
        else:
            self._last_ready = None
        return evidence

    def requires_recheck(self, changed_paths: tuple[str, ...]) -> bool:
        return dependency_inputs_changed(self._spec, changed_paths)


def dependency_inputs_changed(
    spec: RequiredEnvironmentSpec, changed_paths: tuple[str, ...]
) -> bool:
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(changed_paths) is not tuple or not all(
        type(path) is str and path for path in changed_paths
    ):
        raise TypeError("changed_paths must be an exact tuple of non-empty strings")
    watched = {spec.dependency_manifest_identity.relative_path}
    if spec.lock_or_constraints_identity is not None:
        watched.add(spec.lock_or_constraints_identity.relative_path)
    project_roots = tuple(
        requirement.relative_path.rstrip("/") + "/"
        for requirement in spec.local_project_requirements
    )
    return any(
        path in watched or any(path.startswith(root) for root in project_roots)
        for path in changed_paths
    )


def plan_dependency_preparation(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    *,
    evaluated_at: str,
) -> DependencyPreparationPlan:
    if type(spec) is not RequiredEnvironmentSpec:
        raise TypeError("spec must be exact RequiredEnvironmentSpec")
    if type(observation) is not DependencyPreparationObservation:
        raise TypeError("observation must be exact DependencyPreparationObservation")
    if not observation.environment_health_current:
        return _blocked(spec, observation, "dependency.environment-stale")
    if observation.runtime_version is None or not observation.runtime_compatible:
        return _blocked(spec, observation, "runtime.incompatible")
    if observation.package_manager_version is None:
        return _blocked(
            spec, observation, "dependency.package-manager-unavailable"
        )

    existing = observation.existing_ready_evidence
    if (
        existing is not None
        and existing.preparation_status is DependencyPreparationStatus.READY
        and existing.execution_surface_id != observation.execution_surface_id
    ):
        return _blocked(
            spec, observation, "dependency.environment-surface-mismatch"
        )

    if not observation.manifest_matches:
        return _blocked(spec, observation, "dependency.manifest-drift")
    if not observation.source_identity_matches:
        return _blocked(spec, observation, "dependency.package-source-drift")
    if (
        spec.lock_or_constraints_identity is not None
        and observation.lock_matches is not True
    ):
        return _blocked(spec, observation, "dependency.lock-mismatch")
    if spec.local_project_requirements and not observation.local_projects_match:
        return _blocked(spec, observation, "dependency.editable-source-drift")
    if observation.source_form_reason_codes:
        return _blocked(spec, observation, *observation.source_form_reason_codes)

    if existing is not None:
        matches = (
            existing.preparation_status is DependencyPreparationStatus.READY
            and existing.required_environment_id == spec.required_environment_id
            and existing.execution_surface_id == observation.execution_surface_id
            and existing.workspace_identity == observation.workspace_identity
            and existing.source_sha == observation.source_sha
            and existing.source_or_registry_identity == spec.approved_source_identity
            and existing.runtime_version == observation.runtime_version
            and existing.package_manager_version == observation.package_manager_version
            and existing.declared_dependency_identity
            == spec.dependency_manifest_identity.sha256
            and existing.lock_or_constraints_identity
            == (
                None
                if spec.lock_or_constraints_identity is None
                else spec.lock_or_constraints_identity.sha256
            )
            and existing.environment_health_evidence_id
            == observation.environment_health_evidence_id
            and existing.cache_state == observation.cache_state
            and existing.is_current(evaluated_at)
        )
        if matches:
            return DependencyPreparationPlan(
                status=DependencyPreparationStatus.READY,
                argv=None,
                source_identity=spec.approved_source_identity,
                cache_state=observation.cache_state,
            )

    source_identity = spec.approved_source_identity
    offline = False
    if not observation.source_reachable:
        complete_offline = (
            observation.cache_state is DependencyCacheState.CURRENT_COMPLETE
            and observation.offline_source_identity is not None
            and (
                spec.ecosystem is DependencyEcosystem.NODE_NPM
                or observation.offline_source_location is not None
            )
        )
        if not complete_offline:
            reason = (
                "dependency.cache-incomplete"
                if observation.cache_state
                in {DependencyCacheState.INCOMPLETE, DependencyCacheState.UNKNOWN}
                else "dependency.source-unavailable"
            )
            return _blocked(spec, observation, reason)
        source_identity = observation.offline_source_identity or source_identity
        offline = True
    if not observation.package_available:
        return _blocked(spec, observation, "dependency.package-unavailable")

    if spec.ecosystem is DependencyEcosystem.PYTHON_PIP:
        # ``--only-binary=:all:`` is the bounded v1 source-build policy: third-party
        # distributions must arrive as wheels, so no third-party build backend runs
        # at install time. Structurally declared editable local projects still build
        # -- pip applies the restriction to resolved distributions, not to the
        # explicit editable targets below.
        argv = ["python", "-m", "pip", "install", "--only-binary=:all:"]
        if offline:
            assert observation.offline_source_location is not None
            argv.extend(
                ("--no-index", "--find-links", observation.offline_source_location)
            )
        else:
            argv.append(f"--index-url={source_location(spec.approved_source_identity)}")
        argv.extend(("-r", spec.dependency_manifest_identity.relative_path))
        for project in spec.local_project_requirements:
            if project.editable:
                argv.extend(("-e", project.relative_path))
            else:
                argv.append(project.relative_path)
        argv.extend(pin.requirement for pin in spec.qualification_only_pins)
        return DependencyPreparationPlan(
            status=DependencyPreparationStatus.PREPARATION_REQUIRED,
            argv=tuple(argv),
            source_identity=source_identity,
            cache_state=observation.cache_state,
        )

    registry = f"--registry={source_location(spec.approved_source_identity)}"
    if spec.install_mode is DependencyInstallMode.ABSENT_AUTHORIZED_LOCK_GENERATION:
        if observation.source_reachable is False:
            return _blocked(spec, observation, "dependency.source-unavailable")
        return DependencyPreparationPlan(
            status=DependencyPreparationStatus.PREPARATION_REQUIRED,
            argv=(
                "npm",
                "install",
                "--package-lock-only",
                "--ignore-scripts",
                "--no-audit",
                registry,
            ),
            source_identity=source_identity,
            cache_state=observation.cache_state,
            post_success_status=DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED,
        )
    if spec.lock_or_constraints_identity is None:
        return _blocked(spec, observation, "dependency.lock-required")
    # v1 authorizes no install-time script execution and no audit traffic; both are
    # package-manager-native flags rather than a new sandbox or policy subsystem.
    argv = ["npm", "ci", "--ignore-scripts", "--no-audit", registry]
    if offline:
        argv.append("--offline")
    return DependencyPreparationPlan(
        status=DependencyPreparationStatus.PREPARATION_REQUIRED,
        argv=tuple(argv),
        source_identity=source_identity,
        cache_state=observation.cache_state,
    )


def execute_dependency_preparation(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    runner: DependencyCommandRunner,
    *,
    evaluated_at: str,
    expires_at: str,
) -> DependencyReadinessEvidence:
    plan = plan_dependency_preparation(spec, observation, evaluated_at=evaluated_at)
    if plan.status is DependencyPreparationStatus.READY:
        assert observation.existing_ready_evidence is not None
        return observation.existing_ready_evidence
    if plan.status is DependencyPreparationStatus.BLOCKED:
        return _evidence(spec, observation, plan, evaluated_at, expires_at, None)
    assert plan.argv is not None
    result = runner.run(plan.argv, workspace_identity=observation.workspace_identity)
    if type(result) is not DependencyCommandObservation or not result.attempted:
        failed = DependencyPreparationPlan(
            status=DependencyPreparationStatus.FAILED,
            argv=plan.argv,
            source_identity=plan.source_identity,
            cache_state=plan.cache_state,
            reason_codes=("dependency.preparation-failed",),
        )
        return _evidence(spec, observation, failed, evaluated_at, expires_at, None)
    if not result.succeeded:
        reason = result.failure_reason_code or "dependency.preparation-failed"
        failed = DependencyPreparationPlan(
            status=DependencyPreparationStatus.FAILED,
            argv=plan.argv,
            source_identity=plan.source_identity,
            cache_state=plan.cache_state,
            reason_codes=(reason,),
        )
        return _evidence(spec, observation, failed, evaluated_at, expires_at, None)
    final = DependencyPreparationPlan(
        status=plan.post_success_status,
        argv=plan.argv,
        source_identity=plan.source_identity,
        cache_state=plan.cache_state,
        reason_codes=("dependency.source-update-required",)
        if plan.post_success_status is DependencyPreparationStatus.SOURCE_UPDATE_REQUIRED
        else (),
    )
    resolved = result.resolved_dependency_identity
    if final.status is DependencyPreparationStatus.READY and not resolved:
        failed = DependencyPreparationPlan(
            status=DependencyPreparationStatus.FAILED,
            argv=plan.argv,
            source_identity=plan.source_identity,
            cache_state=plan.cache_state,
            reason_codes=("dependency.resolved-evidence-missing",),
        )
        return _evidence(spec, observation, failed, evaluated_at, expires_at, None)
    return _evidence(
        spec,
        observation,
        final,
        evaluated_at,
        expires_at,
        resolved,
    )


def _blocked(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    *reasons: str,
) -> DependencyPreparationPlan:
    return DependencyPreparationPlan(
        status=DependencyPreparationStatus.BLOCKED,
        argv=None,
        source_identity=spec.approved_source_identity,
        cache_state=observation.cache_state,
        reason_codes=tuple(sorted(set(reasons))),
    )


def _evidence(
    spec: RequiredEnvironmentSpec,
    observation: DependencyPreparationObservation,
    plan: DependencyPreparationPlan,
    observed_at: str,
    expires_at: str,
    resolved: str | None,
) -> DependencyReadinessEvidence:
    if plan.status is DependencyPreparationStatus.READY:
        level = (
            ReproducibilityLevel.LOCKED
            if spec.lock_or_constraints_identity
            else ReproducibilityLevel.RESOLVED
        )
    else:
        level = ReproducibilityLevel.DECLARED
    declared = spec.dependency_manifest_identity.sha256
    lock = (
        None
        if spec.lock_or_constraints_identity is None
        else spec.lock_or_constraints_identity.sha256
    )
    return DependencyReadinessEvidence(
        execution_surface_id=observation.execution_surface_id,
        workspace_identity=observation.workspace_identity,
        source_sha=observation.source_sha,
        required_environment_id=spec.required_environment_id,
        package_root=spec.package_root,
        ecosystem=spec.ecosystem,
        runtime_version=observation.runtime_version or "unavailable",
        package_manager_version=observation.package_manager_version or "unavailable",
        declared_dependency_identity=declared,
        lock_or_constraints_identity=lock,
        install_mode=spec.install_mode,
        source_or_registry_identity=plan.source_identity,
        cache_state=plan.cache_state,
        preparation_status=plan.status,
        resolved_dependency_identity=(
            resolved
            if plan.status is DependencyPreparationStatus.READY
            else None
        ),
        environment_health_evidence_id=observation.environment_health_evidence_id,
        observed_at=observed_at,
        expires_at=expires_at,
        reproducibility_level=level,
        reason_codes=tuple(sorted(plan.reason_codes)),
    )
