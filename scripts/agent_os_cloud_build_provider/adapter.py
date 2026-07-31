"""Injected Cloud Build provider adapter (#805).

Consumes one exact accepted ``CloudBuildProviderInvocation`` (#804) and an
injected ``CloudBuildProviderClient`` to submit, observe, and reconcile one
Cloud Build validation build. All Cloud Build transport is delegated to the
injected client Protocol supplied by the caller; this module never imports a
Google SDK, never opens a network connection itself, and never reads the
host clock. It performs no GitHub write, command planning, Workflow
Scheduler lifecycle management, deployment, IAM mutation, credential
installation, or other workflow operation.

An adapter instance performs at most one submit-observe-reconcile
operation. An ambiguous or broken response after a possible submission is
reported as ``status=unknown``/``side_effect_state=unknown`` and is never
automatically retried; recovering it requires external reconciliation and,
if a retry is warranted, a fresh accepted invocation from #804.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, runtime_checkable

from .core import project_cloud_build_provider_result
from .models import (
    PROVIDER_SCHEMA_VERSION,
    CloudBuildProviderConfiguration,
    CloudBuildProviderInvocation,
    CloudBuildProviderObservation,
    CloudBuildProviderResult,
    ProviderCommandEntry,
    ProviderObservationStatus,
    ProviderReason,
    ProviderSideEffectState,
    ProviderStatus,
    cloud_build_provider_invocation_id,
)

DEFAULT_MAX_POLL_ATTEMPTS = 8
MAX_POLL_ATTEMPTS_CEILING = 30
MAX_DIAGNOSTIC_LENGTH = 512
MAX_RECONCILIATION_MATCHES_INSPECTED = 8

_FALLBACK_OBSERVED_AT = "1970-01-01T00:00:00Z"

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_RE = re.compile(
    r"(?i)(authorization\s*:\s*[A-Za-z][A-Za-z0-9._-]*\s+"
    r"[A-Za-z0-9._~+/-]{4,}=*|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?:token|password|secret|api[_-]?key|private[_-]?key)\s*[:=])"
)

SubmissionOutcomeKind = Literal["confirmed", "denied", "unavailable", "internal-error", "ambiguous"]
_SUBMISSION_OUTCOME_KINDS = frozenset({"confirmed", "denied", "unavailable", "internal-error", "ambiguous"})

ObservationOutcomeKind = Literal[
    "working", "success", "failure", "timeout", "cancelled", "internal-error", "unavailable", "unknown"
]
_OBSERVATION_OUTCOME_KINDS = frozenset(status.value for status in ProviderObservationStatus)


def _sanitize_diagnostic(text: object) -> str:
    """Return one bounded, control-stripped, secret-redacted diagnostic string.

    This is a last-resort backstop for whatever a caller-supplied client
    passes back, not the only guard: the injected client is itself
    responsible for never handing this adapter raw headers, credentials,
    provider payloads, or filesystem paths in the first place.
    """
    if type(text) is not str:
        return "diagnostic unavailable"
    stripped = _CONTROL_RE.sub("", text)
    redacted = _SECRET_RE.sub("[redacted]", stripped)
    return redacted[:MAX_DIAGNOSTIC_LENGTH]


def _bounded_optional_text(name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is not str or len(value) > MAX_DIAGNOSTIC_LENGTH:
        raise ValueError(f"{name} must be None or a bounded string")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildSubmissionRequest:
    """Exact identities transported to the injected client for one submission.

    Every field is copied verbatim from an already-validated
    ``CloudBuildProviderInvocation`` or its bound
    ``CloudBuildProviderConfiguration`` -- this type never accepts a
    caller-invented identity of its own.
    """

    repository: str
    resolved_sha: str
    profile: str
    selector_version: str
    command_set_digest: str
    fixed_command_entries: tuple[ProviderCommandEntry, ...]
    fixed_argv_identities: tuple[str, ...]
    provider_configuration_fingerprint: str
    project_id: str
    location: str
    build_service_account_identity: str
    build_definition_identity: str
    builder_image_identity: str
    validator_dependency_identity: str
    evidence_destination_identity: str
    max_build_timeout_seconds: int
    max_output_bytes: int
    provider_metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if type(self.fixed_command_entries) is not tuple or type(self.fixed_argv_identities) is not tuple:
            raise TypeError("fixed_command_entries and fixed_argv_identities must be exact tuples")
        if not isinstance(self.provider_metadata, Mapping):
            raise TypeError("provider_metadata must be a mapping")
        if dict(self.provider_metadata) != {"invocation_id": self.provider_metadata.get("invocation_id")} or not isinstance(
            self.provider_metadata.get("invocation_id"), str
        ):
            raise ValueError("provider_metadata must carry exactly one string invocation_id entry")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildSubmissionOutcome:
    """One caller-supplied outcome of exactly one submission attempt."""

    kind: SubmissionOutcomeKind
    build_id: str | None = None
    observed_at: str | None = None
    diagnostic: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.kind not in _SUBMISSION_OUTCOME_KINDS:
            raise ValueError("kind must be one of the supported submission outcome kinds")
        if self.kind == "confirmed":
            if type(self.build_id) is not str or not self.build_id:
                raise ValueError("a confirmed submission requires a non-empty build_id")
        elif self.build_id is not None:
            raise ValueError("only a confirmed submission may carry a build_id")
        _bounded_optional_text("observed_at", self.observed_at)
        if type(self.diagnostic) is not str:
            raise TypeError("diagnostic must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildObservationRequest:
    """One bounded request to observe the current state of one confirmed build."""

    build_id: str
    invocation_id: str
    attempt: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildObservationOutcome:
    """One caller-supplied observation of one confirmed build at one poll attempt."""

    kind: ObservationOutcomeKind
    tested_sha: str | None = None
    failed_step: str | None = None
    exit_code: int | None = None
    observed_at: str | None = None
    source_complete: bool = False
    diagnostic: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if self.kind not in _OBSERVATION_OUTCOME_KINDS:
            raise ValueError("kind must be one of the supported observation outcome kinds")
        _bounded_optional_text("tested_sha", self.tested_sha)
        _bounded_optional_text("failed_step", self.failed_step)
        _bounded_optional_text("observed_at", self.observed_at)
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise TypeError("exit_code must be an exact integer or None")
        if type(self.source_complete) is not bool:
            raise TypeError("source_complete must be an exact boolean")
        if type(self.diagnostic) is not str:
            raise TypeError("diagnostic must be a string")


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildReconciliationRequest:
    """One bounded request to reconcile builds tagged with one invocation ID."""

    invocation_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildReconciliationOutcome:
    """Caller-supplied reconciliation evidence for one invocation ID.

    ``matches`` holds every build ID the provider reports as tagged with the
    requested invocation ID's metadata. Exactly one match is required before
    the adapter will treat a prior ambiguous submission as confirmed; zero
    or multiple matches remain an unresolved unknown outcome.
    """

    matches: tuple[str, ...] = ()
    observed_at: str | None = None
    diagnostic: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if type(self.matches) is not tuple or len(self.matches) > MAX_RECONCILIATION_MATCHES_INSPECTED:
            raise ValueError("matches must be a bounded tuple of build IDs")
        for item in self.matches:
            if type(item) is not str or not item:
                raise ValueError("every reconciliation match must be a non-empty string build ID")
        _bounded_optional_text("observed_at", self.observed_at)
        if type(self.diagnostic) is not str:
            raise TypeError("diagnostic must be a string")


@runtime_checkable
class CloudBuildProviderClient(Protocol):
    """Injected boundary for exactly one submit/observe/reconcile cycle.

    No implementation lives in this package. Tests supply a fake; a real
    Cloud Build-backed implementation is wired up outside this package and
    is never imported here.
    """

    def submit(self, request: CloudBuildSubmissionRequest) -> CloudBuildSubmissionOutcome: ...

    def observe(self, request: CloudBuildObservationRequest) -> CloudBuildObservationOutcome: ...

    def reconcile(self, request: CloudBuildReconciliationRequest) -> CloudBuildReconciliationOutcome: ...


def _submission_request(
    invocation: CloudBuildProviderInvocation,
    configuration: CloudBuildProviderConfiguration,
) -> CloudBuildSubmissionRequest:
    return CloudBuildSubmissionRequest(
        repository=invocation.repository,
        resolved_sha=invocation.resolved_sha,
        profile=invocation.profile,
        selector_version=invocation.selector_version,
        command_set_digest=invocation.command_set_digest,
        fixed_command_entries=invocation.fixed_command_entries,
        fixed_argv_identities=invocation.fixed_argv_identities,
        provider_configuration_fingerprint=invocation.provider_configuration_fingerprint,
        project_id=configuration.project_id,
        location=configuration.location,
        build_service_account_identity=configuration.build_service_account_identity,
        build_definition_identity=configuration.build_definition_identity,
        builder_image_identity=configuration.builder_image_identity,
        validator_dependency_identity=configuration.validator_dependency_identity,
        evidence_destination_identity=configuration.evidence_destination_identity,
        max_build_timeout_seconds=configuration.max_build_timeout_seconds,
        max_output_bytes=configuration.max_output_bytes,
        provider_metadata={"invocation_id": invocation.invocation_id},
    )


def _safe_observation(
    invocation: CloudBuildProviderInvocation,
    *,
    build_id: str | None,
    tested_sha: str | None,
    terminal_status: ProviderObservationStatus,
    failed_step: str | None,
    exit_code: int | None,
    observed_at: str | None,
    source_complete: bool,
    side_effect_state: ProviderSideEffectState,
) -> CloudBuildProviderObservation:
    """Build a canonical observation, never raising and never fabricating.

    A malformed or hostile client response cannot crash this adapter or
    smuggle an invented build ID, SHA, step, exit code, or terminal state
    into the canonical result: it fails closed to an unknown observation
    carrying no build evidence.
    """
    candidate_observed_at = observed_at if type(observed_at) is str else _FALLBACK_OBSERVED_AT
    try:
        return CloudBuildProviderObservation(
            invocation_id=invocation.invocation_id,
            build_id=build_id,
            repository=invocation.repository,
            tested_sha=tested_sha,
            terminal_status=terminal_status,
            failed_step=failed_step,
            exit_code=exit_code,
            observed_at=candidate_observed_at,
            source_complete=source_complete,
            side_effect_state=side_effect_state,
        )
    except (TypeError, ValueError):
        return CloudBuildProviderObservation(
            invocation_id=invocation.invocation_id,
            build_id=None,
            repository=invocation.repository,
            tested_sha=None,
            terminal_status=ProviderObservationStatus.UNKNOWN,
            failed_step=None,
            exit_code=None,
            observed_at=_FALLBACK_OBSERVED_AT,
            source_complete=False,
            side_effect_state=ProviderSideEffectState.UNKNOWN,
        )


def _denied_result(invocation: CloudBuildProviderInvocation) -> CloudBuildProviderResult:
    """Build the one canonical result shape ``project_cloud_build_provider_result``
    cannot produce: a clean, proven-before-any-build permission denial.
    """
    return CloudBuildProviderResult(
        schema_version=PROVIDER_SCHEMA_VERSION,
        status=ProviderStatus.MANUAL_REVIEW,
        invocation=invocation,
        invocation_id=invocation.invocation_id,
        build_id=None,
        tested_sha=None,
        reason_codes=(ProviderReason.PROVIDER_PERMISSION_DENIED,),
        normalized_cloud_build_evidence=None,
        execution_authorized=True,
        side_effect_state=ProviderSideEffectState.NONE,
    )


class CloudBuildProviderAdapter:
    """A one-shot injected Cloud Build submit/observe/reconcile operation.

    Consumes one exact accepted ``CloudBuildProviderInvocation`` and returns
    one canonical ``CloudBuildProviderResult``. Submits at most once per
    adapter instance; every subsequent ``run`` call on the same instance
    raises rather than resubmitting.
    """

    def __init__(
        self,
        *,
        client: CloudBuildProviderClient,
        configuration: CloudBuildProviderConfiguration,
        max_poll_attempts: int = DEFAULT_MAX_POLL_ATTEMPTS,
    ) -> None:
        if not isinstance(client, CloudBuildProviderClient):
            raise TypeError("client does not satisfy the CloudBuildProviderClient protocol")
        if type(configuration) is not CloudBuildProviderConfiguration:
            raise TypeError("configuration must be an exact CloudBuildProviderConfiguration")
        if (
            type(max_poll_attempts) is not int
            or isinstance(max_poll_attempts, bool)
            or not (1 <= max_poll_attempts <= MAX_POLL_ATTEMPTS_CEILING)
        ):
            raise ValueError(
                f"max_poll_attempts must be a positive integer no greater than {MAX_POLL_ATTEMPTS_CEILING}"
            )
        self._client = client
        self._configuration = configuration
        self._max_poll_attempts = max_poll_attempts
        self._operated = False
        self._poll_attempts = 0
        self._last_diagnostic = ""

    @property
    def poll_attempts(self) -> int:
        """Return how many bounded observation polls were actually issued."""
        return self._poll_attempts

    @property
    def last_diagnostic(self) -> str:
        """Return the bounded, sanitized private diagnostic of the last attempt, if any.

        Never contains credentials, headers, raw provider payloads, or
        filesystem paths; this is local operator evidence only and is never
        part of the canonical ``CloudBuildProviderResult``.
        """
        return self._last_diagnostic

    def run(self, invocation: object) -> CloudBuildProviderResult:
        """Submit, observe, and reconcile exactly once for ``invocation``."""

        if self._operated:
            raise RuntimeError("the cloud build provider adapter may submit at most once")
        self._operated = True

        if type(invocation) is not CloudBuildProviderInvocation:
            self._last_diagnostic = "invocation was not an exact CloudBuildProviderInvocation"
            return project_cloud_build_provider_result(invocation, None)
        if invocation.invocation_id != cloud_build_provider_invocation_id(invocation):
            self._last_diagnostic = "invocation semantic ID did not match its own recomputed identity"
            return project_cloud_build_provider_result(invocation, None)
        if invocation.provider_configuration_fingerprint != self._configuration.configuration_fingerprint:
            self._last_diagnostic = "invocation was bound to a different provider configuration"
            return project_cloud_build_provider_result(invocation, None)

        request = _submission_request(invocation, self._configuration)
        try:
            outcome = self._client.submit(request)
        except Exception as exc:  # noqa: BLE001 - injected boundary; never propagated raw
            self._last_diagnostic = _sanitize_diagnostic(f"submission raised {type(exc).__name__}")
            return self._reconcile(invocation)

        if type(outcome) is not CloudBuildSubmissionOutcome:
            self._last_diagnostic = "submission returned a malformed outcome"
            return self._reconcile(invocation)

        self._last_diagnostic = _sanitize_diagnostic(outcome.diagnostic)

        if outcome.kind == "ambiguous":
            return self._reconcile(invocation)
        if outcome.kind == "denied":
            return _denied_result(invocation)
        if outcome.kind in ("unavailable", "internal-error"):
            return self._proven_unsuccessful_result(invocation, outcome.kind, outcome.observed_at)

        assert outcome.kind == "confirmed" and outcome.build_id is not None
        observation = self._observe_to_terminal(invocation, outcome.build_id)
        return project_cloud_build_provider_result(invocation, observation)

    def _proven_unsuccessful_result(
        self,
        invocation: CloudBuildProviderInvocation,
        kind: str,
        observed_at: str | None,
    ) -> CloudBuildProviderResult:
        terminal_status = (
            ProviderObservationStatus.UNAVAILABLE if kind == "unavailable" else ProviderObservationStatus.INTERNAL_ERROR
        )
        observation = _safe_observation(
            invocation,
            build_id=None,
            tested_sha=None,
            terminal_status=terminal_status,
            failed_step=None,
            exit_code=None,
            observed_at=observed_at,
            source_complete=False,
            side_effect_state=ProviderSideEffectState.NONE,
        )
        return project_cloud_build_provider_result(invocation, observation)

    def _reconcile(self, invocation: CloudBuildProviderInvocation) -> CloudBuildProviderResult:
        """Perform exact, bounded reconciliation for an ambiguous or broken submission.

        Never resubmits. Exactly one matching build tagged with this
        invocation's ID is required to trust the recovered build ID; zero or
        multiple matches remain an unresolved unknown outcome.
        """
        request = CloudBuildReconciliationRequest(invocation_id=invocation.invocation_id)
        try:
            outcome = self._client.reconcile(request)
        except Exception as exc:  # noqa: BLE001 - injected boundary; never propagated raw
            self._last_diagnostic = _sanitize_diagnostic(f"reconciliation raised {type(exc).__name__}")
            return self._unknown_result(invocation, observed_at=None)

        if type(outcome) is not CloudBuildReconciliationOutcome:
            self._last_diagnostic = "reconciliation returned a malformed outcome"
            return self._unknown_result(invocation, observed_at=None)

        self._last_diagnostic = _sanitize_diagnostic(outcome.diagnostic)

        if len(outcome.matches) != 1:
            return self._unknown_result(invocation, observed_at=outcome.observed_at)

        build_id = outcome.matches[0]
        observation = self._observe_to_terminal(invocation, build_id)
        return project_cloud_build_provider_result(invocation, observation)

    def _unknown_result(self, invocation: CloudBuildProviderInvocation, *, observed_at: str | None) -> CloudBuildProviderResult:
        observation = _safe_observation(
            invocation,
            build_id=None,
            tested_sha=None,
            terminal_status=ProviderObservationStatus.UNKNOWN,
            failed_step=None,
            exit_code=None,
            observed_at=observed_at,
            source_complete=False,
            side_effect_state=ProviderSideEffectState.UNKNOWN,
        )
        return project_cloud_build_provider_result(invocation, observation)

    def _observe_to_terminal(self, invocation: CloudBuildProviderInvocation, build_id: str) -> CloudBuildProviderObservation:
        """Poll the confirmed build a bounded number of times for a terminal state.

        A broken or malformed poll response is truthfully reported as an
        unknown terminal state; a well-formed ``unavailable`` reading from
        the client is preserved as-is rather than escalated to unknown,
        since it is a clean signal, not a broken one.
        """
        last_kind: str = "working"
        last_observed_at: str | None = None
        last_tested_sha: str | None = None
        last_failed_step: str | None = None
        last_exit_code: int | None = None
        last_source_complete = False

        for _ in range(self._max_poll_attempts):
            self._poll_attempts += 1
            request = CloudBuildObservationRequest(
                build_id=build_id, invocation_id=invocation.invocation_id, attempt=self._poll_attempts
            )
            try:
                outcome = self._client.observe(request)
            except Exception as exc:  # noqa: BLE001 - injected boundary; never propagated raw
                self._last_diagnostic = _sanitize_diagnostic(f"observation raised {type(exc).__name__}")
                return _safe_observation(
                    invocation,
                    build_id=build_id,
                    tested_sha=None,
                    terminal_status=ProviderObservationStatus.UNKNOWN,
                    failed_step=None,
                    exit_code=None,
                    observed_at=None,
                    source_complete=False,
                    side_effect_state=ProviderSideEffectState.CONFIRMED,
                )

            if type(outcome) is not CloudBuildObservationOutcome:
                self._last_diagnostic = "observation returned a malformed outcome"
                return _safe_observation(
                    invocation,
                    build_id=build_id,
                    tested_sha=None,
                    terminal_status=ProviderObservationStatus.UNKNOWN,
                    failed_step=None,
                    exit_code=None,
                    observed_at=None,
                    source_complete=False,
                    side_effect_state=ProviderSideEffectState.CONFIRMED,
                )

            self._last_diagnostic = _sanitize_diagnostic(outcome.diagnostic)
            last_kind = outcome.kind
            last_observed_at = outcome.observed_at
            last_tested_sha = outcome.tested_sha
            last_failed_step = outcome.failed_step
            last_exit_code = outcome.exit_code
            last_source_complete = outcome.source_complete
            if outcome.kind != "working":
                break

        terminal_status = (
            ProviderObservationStatus(last_kind) if last_kind in _OBSERVATION_OUTCOME_KINDS else ProviderObservationStatus.UNKNOWN
        )
        return _safe_observation(
            invocation,
            build_id=build_id,
            tested_sha=last_tested_sha,
            terminal_status=terminal_status,
            failed_step=last_failed_step,
            exit_code=last_exit_code,
            observed_at=last_observed_at,
            source_complete=last_source_complete,
            side_effect_state=ProviderSideEffectState.CONFIRMED,
        )
