"""Host-local cross-process lease adapter for bounded validation lifecycles."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from workflow_scheduler.execution.posix_process_adapter import (
    ContainedTerminationEvidence,
)
from workflow_scheduler.execution.single_issue_pilot import (
    PilotLeaseGrant,
    PilotLeaseReleaseObservation,
    PilotLeaseRequest,
    pilot_holder_identity,
    pilot_lease_identity,
)

HOST_LOCAL_LEASE_SCHEMA_VERSION = "1.0"
_MAX_METADATA_BYTES = 16_384
_MAX_PATH_LENGTH = 1024
_MAX_IDENTITY_LENGTH = 512

# Workspace/repository dispositions that are resolved enough to recover under.
# There is deliberately no "unknown" member: while the workspace disposition is
# open, quarantine remains dominant and no recovery may proceed.
LEASE_RECOVERY_WORKSPACE_DISPOSITIONS: frozenset[str] = frozenset(
    {"workspace-removed-and-verified", "workspace-preserved-under-review"}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class HostLocalLeasePolicy:
    """Closed policy for one private host-local lease directory."""

    lease_directory: str
    schema_version: Literal["1.0"] = HOST_LOCAL_LEASE_SCHEMA_VERSION
    directory_mode: int = 0o700
    file_mode: int = 0o600
    automatic_retry: Literal[False] = False
    takeover_allowed: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.lease_directory) is not str or not self.lease_directory:
            raise TypeError("lease_directory must be a non-empty string")
        if len(self.lease_directory) > _MAX_PATH_LENGTH:
            raise ValueError("lease_directory exceeds the bounded path length")
        path = Path(self.lease_directory)
        if not path.is_absolute() or str(path) != os.path.normpath(str(path)):
            raise ValueError("lease_directory must be an absolute normalized path")
        if path == Path(path.anchor) or path == Path.home():
            raise ValueError("lease_directory must not be a broad system or home directory")
        if self.directory_mode != 0o700 or self.file_mode != 0o600:
            raise ValueError("host-local lease permissions are fixed at 0700/0600")


@dataclass(frozen=True, slots=True, kw_only=True)
class HostLocalLeaseObservation:
    """Bounded diagnostic observation of one host-local lease identity."""

    lease_identity: str
    active: bool
    ambiguous: bool
    generation: int
    holder_identity: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class OrphanedLeaseRecoveryRequest:
    """Every precondition one bounded exact-identity orphan recovery requires.

    Recovery is never inferred. The caller must bind the exact lease being
    recovered, the exact ownership it expects to remove, the invocation that
    ownership came from, independently proven termination, a resolved
    workspace/repository disposition, and the review evidence authorizing the
    recovery. There is no field through which lease age, TTL, wall-clock
    expiry, heartbeat absence, PID absence, ``ESRCH``, host reachability, or a
    belief that execution is probably dead could be supplied, because none of
    those prove anything.
    """

    lease_identity: str
    expected_holder_identity: str
    expected_generation: int
    original_invocation_id: str
    termination_evidence: ContainedTerminationEvidence
    workspace_disposition: str
    review_evidence_identity: str

    def __post_init__(self) -> None:
        for name in (
            "lease_identity",
            "expected_holder_identity",
            "original_invocation_id",
            "workspace_disposition",
            "review_evidence_identity",
        ):
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ValueError(f"{name} must be a non-empty string")
            if len(value) > _MAX_IDENTITY_LENGTH:
                raise ValueError(f"{name} exceeds the bounded identity length")
        if type(self.expected_generation) is not int or isinstance(
            self.expected_generation, bool
        ):
            raise ValueError("expected_generation must be an exact int")
        if self.expected_generation < 1:
            raise ValueError("expected_generation must be a positive generation")
        if type(self.termination_evidence) is not ContainedTerminationEvidence:
            raise TypeError(
                "termination_evidence must be an exact ContainedTerminationEvidence"
            )
        if self.workspace_disposition not in LEASE_RECOVERY_WORKSPACE_DISPOSITIONS:
            raise ValueError("workspace_disposition must be a resolved disposition")


@dataclass(frozen=True, slots=True, kw_only=True)
class OrphanedLeaseRecoveryObservation:
    """Bounded evidence for exactly one attempted orphan recovery."""

    recovered: bool
    mutated: bool
    lease_identity: str
    expected_holder_identity: str
    expected_generation: int
    retained_generation: int
    reason: str = ""


class HostLocalLeaseAdapter:
    """Atomic, fail-closed lease ownership shared by local processes.

    Active ownership is represented by an O_EXCL-created metadata file. Generation
    state persists separately so a successfully released lease receives a larger
    fencing value on its next acquisition. Existing active metadata is never
    expired, stolen, renewed, or force-released.
    """

    def __init__(self, *, policy: HostLocalLeasePolicy) -> None:
        if type(policy) is not HostLocalLeasePolicy:
            raise TypeError("policy must be an exact HostLocalLeasePolicy")
        self._policy = policy
        self._root = Path(policy.lease_directory)
        self._prepare_root()

    def _prepare_root(self) -> None:
        if self._root.exists() and self._root.is_symlink():
            raise ValueError("lease_directory must not be a symlink")
        self._root.mkdir(mode=self._policy.directory_mode, parents=False, exist_ok=True)
        if not self._root.is_dir() or self._root.is_symlink():
            raise ValueError("lease_directory must be a real directory")
        mode = stat.S_IMODE(self._root.stat().st_mode)
        if mode & 0o077:
            raise PermissionError("lease_directory must be private to its owner")
        os.chmod(self._root, self._policy.directory_mode)

    @staticmethod
    def _key(lease_identity: str) -> str:
        if not lease_identity.startswith("pilot-lease:"):
            raise ValueError("unsupported lease identity")
        digest = lease_identity.removeprefix("pilot-lease:")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("malformed lease identity")
        return digest

    def _paths(self, lease_identity: str) -> tuple[Path, Path]:
        key = self._key(lease_identity)
        return self._root / f"{key}.active.json", self._root / f"{key}.generation"

    @staticmethod
    def _read_bounded(path: Path) -> bytes:
        if path.is_symlink():
            raise ValueError("lease metadata must not be a symlink")
        data = path.read_bytes()
        if len(data) > _MAX_METADATA_BYTES:
            raise ValueError("lease metadata exceeds bounded size")
        return data

    @staticmethod
    def _decode_active(data: bytes) -> tuple[str, str, int]:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("malformed active lease metadata") from exc
        if type(payload) is not dict or set(payload) != {
            "lease_identity", "holder_identity", "generation"
        }:
            raise ValueError("malformed active lease metadata")
        lease_identity = payload["lease_identity"]
        holder_identity = payload["holder_identity"]
        generation = payload["generation"]
        if type(lease_identity) is not str or type(holder_identity) is not str:
            raise ValueError("malformed active lease metadata")
        if type(generation) is not int or isinstance(generation, bool) or generation < 1:
            raise ValueError("malformed active lease generation")
        return lease_identity, holder_identity, generation

    @staticmethod
    def _decode_generation(data: bytes) -> int:
        try:
            text = data.decode("ascii")
            value = int(text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("malformed lease generation metadata") from exc
        if str(value) != text or value < 0:
            raise ValueError("malformed lease generation metadata")
        return value

    def _write_generation(self, path: Path, generation: int) -> None:
        if path.exists() and path.is_symlink():
            raise ValueError("generation metadata must not be a symlink")
        temp = path.with_suffix(".tmp")
        if temp.exists():
            raise RuntimeError("ambiguous generation update state")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, self._policy.file_mode)
        try:
            os.write(fd, str(generation).encode("ascii"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, path)

    def inspect(self, request: PilotLeaseRequest) -> HostLocalLeaseObservation:
        if type(request) is not PilotLeaseRequest:
            raise TypeError("request must be an exact PilotLeaseRequest")
        lease_identity = pilot_lease_identity(request)
        active_path, generation_path = self._paths(lease_identity)
        if not active_path.exists():
            generation = 0
            if generation_path.exists():
                generation = self._decode_generation(self._read_bounded(generation_path))
            return HostLocalLeaseObservation(
                lease_identity=lease_identity, active=False, ambiguous=False, generation=generation
            )
        try:
            stored_lease, holder, active_generation = self._decode_active(
                self._read_bounded(active_path)
            )
        except (OSError, ValueError) as exc:
            generation = 0
            try:
                if generation_path.exists():
                    generation = self._decode_generation(self._read_bounded(generation_path))
            except (OSError, ValueError):
                pass
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=generation,
                reason=str(exc),
            )
        if stored_lease != lease_identity:
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=active_generation,
                holder_identity=holder,
                reason="active lease identity does not match requested lease",
            )
        if not generation_path.exists():
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=active_generation,
                holder_identity=holder,
                reason="active lease generation is not durably recorded",
            )
        try:
            durable_generation = self._decode_generation(self._read_bounded(generation_path))
        except (OSError, ValueError) as exc:
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=active_generation,
                holder_identity=holder,
                reason=str(exc),
            )
        if active_generation != durable_generation:
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=active_generation,
                holder_identity=holder,
                reason="active lease metadata does not match durable generation",
            )
        return HostLocalLeaseObservation(
            lease_identity=lease_identity,
            active=True,
            ambiguous=False,
            generation=durable_generation,
            holder_identity=holder,
        )

    def acquire(self, request: PilotLeaseRequest) -> PilotLeaseGrant:
        if type(request) is not PilotLeaseRequest:
            raise TypeError("request must be an exact PilotLeaseRequest")
        lease_identity = pilot_lease_identity(request)
        holder_identity = pilot_holder_identity(request)
        active_path, generation_path = self._paths(lease_identity)

        if active_path.is_symlink() or generation_path.is_symlink():
            return PilotLeaseGrant(
                acquired=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=0,
                reason="ambiguous lease metadata requires manual recovery",
            )
        if active_path.exists():
            observation = self.inspect(request)
            return PilotLeaseGrant(
                acquired=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=observation.generation,
                reason=(
                    "ambiguous lease metadata requires manual recovery"
                    if observation.ambiguous
                    else "lease already acquired"
                ),
            )

        generation = 1
        if generation_path.exists():
            try:
                generation = self._decode_generation(self._read_bounded(generation_path)) + 1
            except (OSError, ValueError):
                return PilotLeaseGrant(
                    acquired=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=0,
                    reason="ambiguous generation metadata requires manual recovery",
                )

        payload = json.dumps(
            {
                "lease_identity": lease_identity,
                "holder_identity": holder_identity,
                "generation": generation,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            fd = os.open(active_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, self._policy.file_mode)
        except FileExistsError:
            return PilotLeaseGrant(
                acquired=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
                reason="lease already acquired",
            )
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

        try:
            self._write_generation(generation_path, generation)
        except BaseException:
            # The active file proves possible ownership. Never remove it here:
            # doing so would turn uncertain acquisition into implicit takeover.
            raise

        return PilotLeaseGrant(
            acquired=True,
            lease_identity=lease_identity,
            holder_identity=holder_identity,
            generation=generation,
        )

    def release(self, grant: PilotLeaseGrant) -> PilotLeaseReleaseObservation:
        if type(grant) is not PilotLeaseGrant:
            raise TypeError("grant must be an exact PilotLeaseGrant")
        lease_identity, holder_identity, generation = (
            grant.lease_identity,
            grant.holder_identity,
            grant.generation,
        )
        if not lease_identity or not holder_identity or type(generation) is not int or generation < 1:
            return PilotLeaseReleaseObservation(
                released=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
                reason="malformed release request",
            )
        try:
            active_path, generation_path = self._paths(lease_identity)
            if not active_path.exists() or active_path.is_symlink():
                return PilotLeaseReleaseObservation(
                    released=False,
                    lease_identity=lease_identity,
                    holder_identity=holder_identity,
                    generation=generation,
                    ambiguous=active_path.is_symlink(),
                    reason="lease already released" if not active_path.exists() else "ambiguous lease metadata",
                )
            stored_lease, stored_holder, stored_generation = self._decode_active(
                self._read_bounded(active_path)
            )
            durable_generation = self._decode_generation(self._read_bounded(generation_path))
        except (OSError, ValueError) as exc:
            return PilotLeaseReleaseObservation(
                released=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
                ambiguous=True,
                reason=str(exc),
            )
        if stored_lease != lease_identity:
            reason = "lease identity does not match active lease"
        elif stored_holder != holder_identity:
            reason = "lease holder does not match active owner"
        elif stored_generation != generation or durable_generation != generation:
            reason = "lease generation does not match active generation"
        else:
            reason = ""
        if reason:
            return PilotLeaseReleaseObservation(
                released=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
                reason=reason,
            )

        active_path.unlink()
        if active_path.exists():
            return PilotLeaseReleaseObservation(
                released=False,
                lease_identity=lease_identity,
                holder_identity=holder_identity,
                generation=generation,
                ambiguous=True,
                reason="lease release could not be observed complete",
            )
        return PilotLeaseReleaseObservation(
            released=True,
            lease_identity=lease_identity,
            holder_identity=holder_identity,
            generation=generation,
        )

    def _before_recovery_mutation(self) -> None:
        """The compare-and-act boundary between the decision and the mutation.

        Overridable so a test can interleave real concurrent activity here and
        prove the authoritative re-read below rejects drift. It is a no-op in
        every production path.
        """

    def _rejected(
        self,
        request: OrphanedLeaseRecoveryRequest,
        reason: str,
        *,
        retained_generation: int = 0,
    ) -> OrphanedLeaseRecoveryObservation:
        return OrphanedLeaseRecoveryObservation(
            recovered=False,
            mutated=False,
            lease_identity=request.lease_identity,
            expected_holder_identity=request.expected_holder_identity,
            expected_generation=request.expected_generation,
            retained_generation=retained_generation,
            reason=reason,
        )

    def recover_orphaned_lease(
        self, request: OrphanedLeaseRecoveryRequest
    ) -> OrphanedLeaseRecoveryObservation:
        """Recover exactly one genuinely orphaned host-local lease, or do nothing.

        This is not a force-release, steal, takeover, expiry, or retry. It
        removes only the exact active ownership state named by the request, and
        only after independently proven termination and an authoritative
        re-read that still matches that exact lease identity, holder identity,
        and generation. Any mismatch, ambiguity, or uncertainty performs zero
        mutation and fails closed.

        Generation history is deliberately preserved: the durable generation
        record is never rewritten or reset, so the next ordinary acquisition
        reads it and receives a strictly newer generation. A stale holder from
        the recovered generation can therefore never release the next owner.
        """
        if type(request) is not OrphanedLeaseRecoveryRequest:
            raise TypeError("request must be an exact OrphanedLeaseRecoveryRequest")

        if not request.termination_evidence.termination_proven:
            return self._rejected(
                request, "recovery requires independently proven prior termination"
            )

        try:
            active_path, generation_path = self._paths(request.lease_identity)
        except ValueError as exc:
            return self._rejected(request, str(exc))

        if active_path.is_symlink() or generation_path.is_symlink():
            return self._rejected(request, "ambiguous lease metadata requires manual recovery")
        if not active_path.exists():
            return self._rejected(request, "no active lease ownership to recover")

        # Decision read: the ownership the caller believes it is recovering.
        try:
            decided = self._decode_active(self._read_bounded(active_path))
            durable_generation = self._decode_generation(self._read_bounded(generation_path))
        except (OSError, ValueError) as exc:
            return self._rejected(request, str(exc))

        expected = (
            request.lease_identity,
            request.expected_holder_identity,
            request.expected_generation,
        )
        if decided != expected or durable_generation != request.expected_generation:
            return self._rejected(
                request,
                "active lease metadata does not match the exact recovery identity",
                retained_generation=durable_generation,
            )

        self._before_recovery_mutation()

        # Authoritative re-read immediately before the only mutation. If the
        # active lease moved on between the decision and here, nothing is
        # touched: the current owner is never disturbed by a stale recovery.
        try:
            if not active_path.exists() or active_path.is_symlink():
                return self._rejected(
                    request,
                    "active lease ownership changed before recovery could act",
                    retained_generation=durable_generation,
                )
            current = self._decode_active(self._read_bounded(active_path))
            current_durable = self._decode_generation(self._read_bounded(generation_path))
        except (OSError, ValueError) as exc:
            return self._rejected(request, str(exc), retained_generation=durable_generation)

        if current != expected or current_durable != request.expected_generation:
            return self._rejected(
                request,
                "active lease ownership changed before recovery could act",
                retained_generation=current_durable,
            )

        # Remove only the exact active ownership. The generation record stays.
        active_path.unlink()
        if active_path.exists():
            return OrphanedLeaseRecoveryObservation(
                recovered=False,
                mutated=True,
                lease_identity=request.lease_identity,
                expected_holder_identity=request.expected_holder_identity,
                expected_generation=request.expected_generation,
                retained_generation=current_durable,
                reason="recovery could not be observed complete",
            )
        return OrphanedLeaseRecoveryObservation(
            recovered=True,
            mutated=True,
            lease_identity=request.lease_identity,
            expected_holder_identity=request.expected_holder_identity,
            expected_generation=request.expected_generation,
            retained_generation=current_durable,
        )
