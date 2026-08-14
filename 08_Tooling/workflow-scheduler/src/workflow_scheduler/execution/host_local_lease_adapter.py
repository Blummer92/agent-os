"""Host-local cross-process lease adapter for bounded validation lifecycles."""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
        generation = 0
        if generation_path.exists():
            generation = self._decode_generation(self._read_bounded(generation_path))
        if not active_path.exists():
            return HostLocalLeaseObservation(
                lease_identity=lease_identity, active=False, ambiguous=False, generation=generation
            )
        try:
            stored_lease, holder, active_generation = self._decode_active(
                self._read_bounded(active_path)
            )
        except (OSError, ValueError) as exc:
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=generation,
                reason=str(exc),
            )
        if stored_lease != lease_identity or active_generation != generation:
            return HostLocalLeaseObservation(
                lease_identity=lease_identity,
                active=True,
                ambiguous=True,
                generation=generation,
                holder_identity=holder,
                reason="active lease metadata does not match durable generation",
            )
        return HostLocalLeaseObservation(
            lease_identity=lease_identity,
            active=True,
            ambiguous=False,
            generation=generation,
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
