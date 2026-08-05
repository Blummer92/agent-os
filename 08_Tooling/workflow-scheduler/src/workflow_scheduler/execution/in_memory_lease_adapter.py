"""Process-local, fail-closed lease adapter for the WSC5 pilot contract.

The adapter provides only in-memory mutual exclusion inside one Python process.
It does not provide expiry, renewal, takeover, persistence, crash safety, or
distributed coordination.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseGrant,
    PilotLeaseReleaseObservation,
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)

DEFAULT_MAX_LEASE_IDENTITIES = 1024
MAX_REASON_LENGTH = 256


@dataclass(frozen=True, slots=True)
class _ActiveLease:
    holder_identity: str
    generation: int


class InMemoryLeaseAdapter:
    """Atomic process-local implementation of the canonical lease protocol."""

    def __init__(self, *, max_lease_identities: int = DEFAULT_MAX_LEASE_IDENTITIES) -> None:
        if not isinstance(max_lease_identities, int) or isinstance(
            max_lease_identities, bool
        ):
            raise TypeError("max_lease_identities must be an integer")
        if max_lease_identities < 1:
            raise ValueError("max_lease_identities must be positive")
        self._max_lease_identities = max_lease_identities
        self._lock = Lock()
        self._active: dict[str, _ActiveLease] = {}
        self._generations: dict[str, int] = {}

    def acquire(self, request: PilotLeaseRequest) -> PilotLeaseGrant:
        """Acquire one canonical lease or return a bounded fail-closed result."""
        if not isinstance(request, PilotLeaseRequest):
            raise TypeError("request must be PilotLeaseRequest")

        lease_identity = pilot_lease_identity(request)
        holder_identity = pilot_holder_identity(request)

        with self._lock:
            active = self._active.get(lease_identity)
            if active is not None:
                return PilotLeaseGrant(
                    acquired=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=active.generation,
                    reason="lease already acquired",
                )

            if (
                lease_identity not in self._generations
                and len(self._generations) >= self._max_lease_identities
            ):
                return PilotLeaseGrant(
                    acquired=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=0,
                    reason="lease identity capacity reached",
                )

            generation = self._generations.get(lease_identity, 0) + 1
            self._generations[lease_identity] = generation
            self._active[lease_identity] = _ActiveLease(
                holder_identity=holder_identity,
                generation=generation,
            )
            return PilotLeaseGrant(
                acquired=True,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
            )

    def release(self, grant: PilotLeaseGrant) -> PilotLeaseReleaseObservation:
        """Release only the exact active lease identity, holder, and generation."""
        if not isinstance(grant, PilotLeaseGrant):
            raise TypeError("grant must be PilotLeaseGrant")

        lease_identity = grant.lease_identity
        holder_identity = grant.holder_identity
        generation = grant.generation

        if not lease_identity or not holder_identity or generation < 1:
            return PilotLeaseReleaseObservation(
                released=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
                reason="malformed release request",
            )

        with self._lock:
            active = self._active.get(lease_identity)
            if active is None:
                known_generation = self._generations.get(lease_identity)
                reason = (
                    "lease already released"
                    if known_generation is not None and generation <= known_generation
                    else "lease is not owned"
                )
                return PilotLeaseReleaseObservation(
                    released=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=generation,
                    reason=reason,
                )

            if active.holder_identity != holder_identity:
                return PilotLeaseReleaseObservation(
                    released=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=generation,
                    reason="lease holder does not match active owner",
                )

            if active.generation != generation:
                return PilotLeaseReleaseObservation(
                    released=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=generation,
                    reason="lease generation does not match active generation",
                )

            del self._active[lease_identity]
            return PilotLeaseReleaseObservation(
                released=True,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
            )

    def _reset_for_tests(self) -> None:
        """Clear process-local state; this is test isolation, not recovery authority."""
        with self._lock:
            self._active.clear()
            self._generations.clear()
