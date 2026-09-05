"""Cloud Build provider to Scheduler lease lifecycle composition (#1211).

This module is a pure repository-local composition boundary. It consumes an
already-accepted Cloud Build invocation, the existing provider adapter, and the
existing Scheduler lease contract. It creates no provider, retry system, state
store, Scheduler, credential path, or external authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scripts.agent_os_cloud_build_provider import CloudBuildProviderAdapter
from scripts.agent_os_cloud_build_provider.models import (
    CloudBuildProviderInvocation,
    CloudBuildProviderResult,
    ProviderReason,
    ProviderSideEffectState,
    ProviderStatus,
)
from workflow_scheduler.execution.single_issue_pilot import (
    LeaseAdapter,
    PilotLeaseGrant,
    PilotLeaseReleaseObservation,
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)

LifecycleDisposition = Literal[
    "terminal-released",
    "terminal-release-failed",
    "nonterminal-lease-retained",
    "unknown-lease-retained",
    "lease-unavailable",
    "identity-mismatch",
]

_TERMINAL_REASONS = frozenset(
    {
        ProviderReason.ACCEPTED,
        ProviderReason.PROVIDER_FAILURE,
        ProviderReason.PROVIDER_TIMEOUT,
        ProviderReason.PROVIDER_CANCELLED,
        ProviderReason.PROVIDER_EXPIRED,
        ProviderReason.PROVIDER_INTERNAL_ERROR,
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildLeaseBinding:
    """Exact existing identities that bind one provider invocation to one lease."""

    repository: str
    issue_number: int
    issue_or_handoff_identity: str
    invocation_id: str
    branch: str
    source_head_sha: str
    workspace_request_id: str
    projection_id: str
    approval_id: str

    def lease_request(self) -> PilotLeaseRequest:
        return PilotLeaseRequest(
            repository=self.repository,
            issue_number=self.issue_number,
            invocation_id=self.invocation_id,
            branch=self.branch,
            workspace_request_id=self.workspace_request_id,
            projection_id=self.projection_id,
            approval_id=self.approval_id,
            source_head_sha=self.source_head_sha,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CloudBuildLeaseLifecycleResult:
    """Bounded lifecycle evidence; never an execution or merge authorization."""

    disposition: LifecycleDisposition
    provider_result: CloudBuildProviderResult | None
    lease_grant: PilotLeaseGrant | None
    lease_release: PilotLeaseReleaseObservation | None
    lease_retained: bool
    termination_proven: bool
    reason: str
    execution_authorized: bool = False
    merge_authorized: bool = False
    issue_closure_authorized: bool = False


def _identity_matches(
    binding: CloudBuildLeaseBinding,
    invocation: CloudBuildProviderInvocation,
) -> bool:
    return (
        invocation.repository == binding.repository
        and invocation.issue_or_handoff_identity == binding.issue_or_handoff_identity
        and invocation.invocation_id == binding.invocation_id
        and invocation.requested_ref == binding.branch
        and invocation.expected_sha == binding.source_head_sha
        and invocation.resolved_sha == binding.source_head_sha
    )


def _lease_grant_matches(request: PilotLeaseRequest, grant: PilotLeaseGrant) -> bool:
    return (
        grant.acquired
        and grant.lease_identity == pilot_lease_identity(request)
        and grant.holder_identity == pilot_holder_identity(request)
        and type(grant.generation) is int
        and grant.generation > 0
    )


def _termination_proven(result: CloudBuildProviderResult) -> bool:
    return (
        result.status is ProviderStatus.TERMINAL
        and result.side_effect_state is ProviderSideEffectState.CONFIRMED
        and bool(set(result.reason_codes) & _TERMINAL_REASONS)
    )


def run_cloud_build_lease_lifecycle(
    *,
    binding: CloudBuildLeaseBinding,
    invocation: CloudBuildProviderInvocation,
    provider: CloudBuildProviderAdapter,
    lease: LeaseAdapter,
) -> CloudBuildLeaseLifecycleResult:
    """Run one provider invocation while preserving canonical Scheduler ownership.

    A lease is acquired before the provider is invoked. Once provider submission
    may have occurred, nonterminal or unknown provider evidence retains that exact
    lease. Release is attempted only after canonical provider evidence proves a
    terminal execution. No retry or resubmission is performed here.
    """
    if type(binding) is not CloudBuildLeaseBinding:
        raise TypeError("binding must be an exact CloudBuildLeaseBinding")
    if type(invocation) is not CloudBuildProviderInvocation:
        raise TypeError("invocation must be an exact CloudBuildProviderInvocation")
    if not isinstance(provider, CloudBuildProviderAdapter):
        raise TypeError("provider must be a CloudBuildProviderAdapter")
    if not isinstance(lease, LeaseAdapter):
        raise TypeError("lease must satisfy the canonical LeaseAdapter protocol")

    if not _identity_matches(binding, invocation):
        return CloudBuildLeaseLifecycleResult(
            disposition="identity-mismatch",
            provider_result=None,
            lease_grant=None,
            lease_release=None,
            lease_retained=False,
            termination_proven=False,
            reason="provider invocation does not match the Scheduler lifecycle binding",
        )

    request = binding.lease_request()
    grant = lease.acquire(request)
    if type(grant) is not PilotLeaseGrant or not _lease_grant_matches(request, grant):
        return CloudBuildLeaseLifecycleResult(
            disposition="lease-unavailable",
            provider_result=None,
            lease_grant=grant if type(grant) is PilotLeaseGrant else None,
            lease_release=None,
            lease_retained=False,
            termination_proven=False,
            reason="canonical Scheduler lease was not acquired with exact identity",
        )

    provider_result = provider.run(invocation)
    terminal = _termination_proven(provider_result)
    if not terminal:
        disposition: LifecycleDisposition = (
            "unknown-lease-retained"
            if provider_result.status is ProviderStatus.UNKNOWN
            or provider_result.side_effect_state is ProviderSideEffectState.UNKNOWN
            else "nonterminal-lease-retained"
        )
        return CloudBuildLeaseLifecycleResult(
            disposition=disposition,
            provider_result=provider_result,
            lease_grant=grant,
            lease_release=None,
            lease_retained=True,
            termination_proven=False,
            reason="provider termination is unproven; exact Scheduler lease remains owned",
        )

    release = lease.release(grant)
    released = (
        type(release) is PilotLeaseReleaseObservation
        and release.released
        and not release.ambiguous
        and not release.forced
        and release.lease_identity == grant.lease_identity
        and release.holder_identity == grant.holder_identity
        and release.generation == grant.generation
    )
    return CloudBuildLeaseLifecycleResult(
        disposition="terminal-released" if released else "terminal-release-failed",
        provider_result=provider_result,
        lease_grant=grant,
        lease_release=release if type(release) is PilotLeaseReleaseObservation else None,
        lease_retained=not released,
        termination_proven=True,
        reason=(
            "provider termination proven and exact Scheduler lease released"
            if released
            else "provider termination proven but exact Scheduler lease release was not proven"
        ),
    )
