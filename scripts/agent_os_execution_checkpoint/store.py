"""Append-only, content-addressed local checkpoint store.

The intended production root is ``$(git rev-parse --git-common-dir)/agent-os-checkpoints/``
(see ``README.md``), but resolving that path requires a ``git`` subprocess
call, which this package deliberately never performs -- the caller resolves
``store_root`` and passes it in. This module then owns everything below
that path: atomic content-addressed writes, tamper detection, quarantine,
and bounded retention/size enforcement. Nothing here is ever committed to
the Git-tracked working tree.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .identity import canonical_json_bytes, domain_digest
from .models import (
    CANONICAL_STAGE_ORDER,
    MAX_SERIALIZED_BYTES,
    ExecutionCheckpoint,
    InvalidationState,
    checkpoint_from_dict,
    deserialize_checkpoint,
    serialize_checkpoint,
)

MAX_RECORDS_PER_ISSUE = 512
MAX_BYTES_PER_ISSUE = 32 * 1024 * 1024
QUARANTINE_DOMAIN = "agent-os.execution-checkpoint.quarantine"


class CheckpointStoreUnavailable(RuntimeError):
    """Raised when the store root cannot be used for reads or writes.

    Per the design contract: an unavailable store means read-only stages
    become ``rerun-required`` and mutating stages become ``manual-review``
    -- never that a mutation is assumed not to have occurred.
    """


class CheckpointStoreCapacityExceeded(RuntimeError):
    """Raised when a new write would exceed the per-issue size or count cap.

    New writes are refused; existing records are never auto-pruned.
    """


class CheckpointStoreIntegrityConflict(RuntimeError):
    """A content-addressed filename holds different bytes than expected.

    Effectively unreachable under SHA-256 unless the file was corrupted or
    tampered with after being written; callers should quarantine.
    """


class CheckpointNotFound(LookupError):
    """Raised when no valid checkpoint with the requested exact id exists."""


class CheckpointQuarantined(LookupError):
    """Raised when the requested checkpoint_id is known but quarantined."""


@dataclass(frozen=True, slots=True)
class AppendOutcome:
    checkpoint_id: str
    path: Path
    already_present: bool


@dataclass(frozen=True, slots=True)
class LoadedCheckpoint:
    checkpoint: ExecutionCheckpoint
    path: Path


@dataclass(frozen=True, slots=True)
class QuarantinedEntry:
    checkpoint_id: str | None
    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Result of loading and verifying every record for one issue.

    Never raises for a single bad file: a record that fails id
    recomputation, fails schema validation, or was already quarantined is
    reported in ``quarantined`` rather than raised, so the environment stays
    inspectable after a partial failure.
    """

    valid: tuple[LoadedCheckpoint, ...]
    quarantined: tuple[QuarantinedEntry, ...]
    quarantined_checkpoint_ids: frozenset[str]


def _issue_dirname(issue_number: int) -> str:
    if type(issue_number) is not int or issue_number < 1:
        raise TypeError("issue_number must be a positive built-in integer")
    return f"issue-{issue_number}"


def issue_store_dir(store_root: Path, issue_number: int) -> Path:
    return Path(store_root) / _issue_dirname(issue_number)


def _checkpoints_dir(issue_dir: Path) -> Path:
    return issue_dir / "checkpoints"


def _quarantine_dir(issue_dir: Path) -> Path:
    return issue_dir / "quarantine"


def _head_path(issue_dir: Path) -> Path:
    return issue_dir / "HEAD"


def _filename_for_checkpoint_id(checkpoint_id: str) -> str:
    # checkpoint_id is "<domain>:<64-hex>"; the filename uses the hex suffix
    # only, since ":" is unsafe in filenames on some filesystems.
    return f"{checkpoint_id.rsplit(':', 1)[-1]}.json"


def _reject_symlink(path: Path) -> None:
    try:
        mode = os.lstat(os.fspath(path)).st_mode
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to stat {path}") from exc
    import stat as _stat

    if _stat.S_ISLNK(mode):
        raise CheckpointStoreUnavailable(f"refusing a symlinked store path: {path}")


def _atomic_write(
    directory: Path, filename: str, payload: bytes
) -> tuple[Path, bool]:
    """Publish content atomically without ever overwriting an existing record.

    ``tempfile.mkstemp`` creates the temporary file with exclusive ``O_EXCL``
    semantics. ``os.link`` then publishes that completed file atomically and
    fails if the content-addressed destination already exists.

    Returns ``(path, already_present)``. Identical existing bytes are an
    idempotent success; different existing bytes are an integrity conflict.
    """

    final_path = directory / filename
    _reject_symlink(final_path)

    descriptor = None
    temp_name = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=os.fspath(directory), prefix=".tmp-", suffix=".json"
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = None

        try:
            os.link(temp_name, os.fspath(final_path))
        except FileExistsError:
            _reject_symlink(final_path)
            try:
                existing = final_path.read_bytes()
            except OSError as exc:
                raise CheckpointStoreUnavailable(
                    f"unable to verify existing content at {final_path}"
                ) from exc
            if existing == payload:
                return final_path, True
            raise CheckpointStoreIntegrityConflict(
                f"content-addressed path already holds different content: {final_path}"
            ) from None
        except OSError as exc:
            raise CheckpointStoreUnavailable(
                f"unable to publish {final_path}"
            ) from exc

        return final_path, False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temp_name is not None:
            try:
                os.remove(temp_name)
            except FileNotFoundError:
                pass


def _ensure_dir(path: Path) -> None:
    _reject_symlink(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to create {path}") from exc
    _reject_symlink(path)


def _existing_records_footprint(checkpoints_dir: Path) -> tuple[int, int]:
    if not checkpoints_dir.exists():
        return 0, 0
    count = 0
    total_bytes = 0
    for entry in checkpoints_dir.iterdir():
        if entry.is_file() and entry.suffix == ".json":
            count += 1
            total_bytes += entry.stat().st_size
    return count, total_bytes


def append_checkpoint(store_root: Path | str, checkpoint: ExecutionCheckpoint) -> AppendOutcome:
    """Append one immutable checkpoint record, atomically and idempotently.

    Refuses (raises ``CheckpointStoreCapacityExceeded``) rather than
    auto-pruning when the per-issue record count or byte budget would be
    exceeded by a genuinely new record. An idempotent duplicate write
    (identical content already on disk) is always accepted regardless of
    the current footprint, since it performs no new write.
    """

    if type(checkpoint) is not ExecutionCheckpoint:
        raise TypeError("checkpoint must be an exact ExecutionCheckpoint")

    issue_dir = issue_store_dir(Path(store_root), checkpoint.issue_number)
    _reject_symlink(issue_dir)
    checkpoints_dir = _checkpoints_dir(issue_dir)
    _ensure_dir(checkpoints_dir)

    filename = _filename_for_checkpoint_id(checkpoint.checkpoint_id)
    payload = serialize_checkpoint(checkpoint)
    if len(payload) > MAX_SERIALIZED_BYTES:
        raise CheckpointStoreCapacityExceeded("checkpoint exceeds the per-record size bound")

    destination_existed_before_write = (checkpoints_dir / filename).exists()
    if not destination_existed_before_write:
        count, total_bytes = _existing_records_footprint(checkpoints_dir)
        if count + 1 > MAX_RECORDS_PER_ISSUE or total_bytes + len(payload) > MAX_BYTES_PER_ISSUE:
            raise CheckpointStoreCapacityExceeded(
                f"issue {checkpoint.issue_number} checkpoint store is at capacity"
            )

    path, already_present = _atomic_write(checkpoints_dir, filename, payload)

    try:
        _write_head(issue_dir, checkpoint.checkpoint_id)
    except CheckpointStoreUnavailable:
        # HEAD is a reconstructable fast-path hint only; a failure to update
        # it never invalidates the append itself.
        pass

    return AppendOutcome(
        checkpoint_id=checkpoint.checkpoint_id, path=path, already_present=already_present
    )


def _write_head(issue_dir: Path, checkpoint_id: str) -> None:
    """Best-effort atomic update of the reconstructable mutable HEAD hint."""

    _ensure_dir(issue_dir)
    payload = (checkpoint_id + "\n").encode("utf-8")
    head_path = _head_path(issue_dir)
    _reject_symlink(head_path)

    descriptor = None
    temp_name = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            dir=os.fspath(issue_dir), prefix=".tmp-head-"
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        descriptor = None
        os.replace(temp_name, os.fspath(head_path))
        temp_name = None
    except OSError as exc:
        raise CheckpointStoreUnavailable(
            f"unable to write {head_path}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temp_name is not None:
            try:
                os.remove(temp_name)
            except FileNotFoundError:
                pass


def read_head(store_root: Path | str, issue_number: int) -> str | None:
    """Best-effort HEAD read. Never authoritative -- see ``load_checkpoints``."""

    issue_dir = issue_store_dir(Path(store_root), issue_number)
    head_path = _head_path(issue_dir)
    try:
        text = head_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to read {head_path}") from exc
    return text or None


def write_quarantine_record(
    store_root: Path | str, issue_number: int, checkpoint_id: str | None, reason: str
) -> Path:
    """Record a quarantine decision as a new, separate, content-addressed fact.

    The quarantined checkpoint's own file is never deleted or modified --
    quarantine is additive evidence, not a mutation of history.
    """

    issue_dir = issue_store_dir(Path(store_root), issue_number)
    _reject_symlink(issue_dir)
    quarantine_dir = _quarantine_dir(issue_dir)
    _ensure_dir(quarantine_dir)

    record = {
        "schema": "agent-os.execution-checkpoint.quarantine",
        "schema_version": "1.0",
        "issue_number": issue_number,
        "checkpoint_id": checkpoint_id,
        "reason": reason[:256],
    }
    quarantine_id = domain_digest(QUARANTINE_DOMAIN, record)
    payload = canonical_json_bytes({**record, "quarantine_id": quarantine_id})
    filename = f"{quarantine_id.rsplit(':', 1)[-1]}.json"
    path, _already_present = _atomic_write(quarantine_dir, filename, payload)
    return path


def _checkpoint_id_from_filename(path: Path) -> str | None:
    """Recover the content-addressed id represented by a checkpoint filename."""

    if path.suffix != ".json":
        return None
    digest = path.stem
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return None
    return f"agent-os.execution-checkpoint:{digest}"


def load_checkpoints(store_root: Path | str, issue_number: int) -> LoadResult:
    """Load and verify every checkpoint and its complete parent chain."""

    issue_dir = issue_store_dir(Path(store_root), issue_number)
    _reject_symlink(issue_dir)
    checkpoints_dir = _checkpoints_dir(issue_dir)
    if not checkpoints_dir.exists():
        return LoadResult(valid=(), quarantined=(), quarantined_checkpoint_ids=frozenset())

    already_quarantined = _load_quarantined_ids(issue_dir)
    quarantined_ids: set[str] = set(already_quarantined)
    valid: list[LoadedCheckpoint] = []
    quarantined: list[QuarantinedEntry] = []

    for entry in sorted(checkpoints_dir.iterdir()):
        if not (entry.is_file() and entry.suffix == ".json"):
            continue

        filename_id = _checkpoint_id_from_filename(entry)

        try:
            payload = entry.read_bytes()
        except OSError as exc:
            if filename_id is not None:
                quarantined_ids.add(filename_id)
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=filename_id,
                    path=entry,
                    reason=f"unreadable: {exc}",
                )
            )
            continue

        try:
            checkpoint = deserialize_checkpoint(payload)
        except (TypeError, ValueError) as exc:
            # The filename is content-addressed and preserves the original
            # identifier even when tampering makes the embedded record fail
            # validation. Descendants may therefore still be identified.
            if filename_id is not None:
                quarantined_ids.add(filename_id)
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=filename_id,
                    path=entry,
                    reason=f"invalid: {exc}",
                )
            )
            continue

        expected_filename = _filename_for_checkpoint_id(checkpoint.checkpoint_id)
        if entry.name != expected_filename:
            quarantined_ids.add(checkpoint.checkpoint_id)
            if filename_id is not None:
                quarantined_ids.add(filename_id)
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=checkpoint.checkpoint_id,
                    path=entry,
                    reason="filename does not match recomputed checkpoint_id",
                )
            )
            continue

        if checkpoint.checkpoint_id in already_quarantined:
            quarantined_ids.add(checkpoint.checkpoint_id)
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=checkpoint.checkpoint_id,
                    path=entry,
                    reason="previously quarantined",
                )
            )
            continue

        valid.append(LoadedCheckpoint(checkpoint=checkpoint, path=entry))

    stage_index = {
        stage: index for index, stage in enumerate(CANONICAL_STAGE_ORDER)
    }
    remaining = list(valid)

    while True:
        to_quarantine: dict[str, str] = {}
        by_id = {
            item.checkpoint.checkpoint_id: item
            for item in remaining
        }

        # Validate every direct parent relationship.
        for item in remaining:
            checkpoint = item.checkpoint
            parent_id = checkpoint.parent_checkpoint_id
            if parent_id is None:
                continue

            if parent_id in quarantined_ids:
                to_quarantine[checkpoint.checkpoint_id] = (
                    "descendant of a quarantined checkpoint"
                )
                continue

            parent = by_id.get(parent_id)
            if parent is None:
                to_quarantine[checkpoint.checkpoint_id] = (
                    "missing parent checkpoint"
                )
                continue

            if parent.checkpoint.execution_id != checkpoint.execution_id:
                to_quarantine[checkpoint.checkpoint_id] = (
                    "parent belongs to a different execution_id"
                )
                continue

            parent_stage = stage_index[parent.checkpoint.checkpoint_stage]
            child_stage = stage_index[checkpoint.checkpoint_stage]
            if (
                child_stage < parent_stage
                and checkpoint.invalidation_state
                is not InvalidationState.INVALIDATED
            ):
                to_quarantine[checkpoint.checkpoint_id] = (
                    "checkpoint stage order moves backward without invalidation"
                )

        # Remove direct failures before checking whole-chain shape.
        if not to_quarantine:
            by_execution: dict[str, list[LoadedCheckpoint]] = {}
            for item in remaining:
                by_execution.setdefault(
                    item.checkpoint.execution_id, []
                ).append(item)

            for execution_items in by_execution.values():
                roots = [
                    item
                    for item in execution_items
                    if item.checkpoint.parent_checkpoint_id is None
                ]

                if len(roots) != 1:
                    for item in execution_items:
                        to_quarantine[item.checkpoint.checkpoint_id] = (
                            "execution chain must contain exactly one genesis checkpoint"
                        )
                    continue

                children: dict[str, list[LoadedCheckpoint]] = {}
                for item in execution_items:
                    parent_id = item.checkpoint.parent_checkpoint_id
                    if parent_id is not None:
                        children.setdefault(parent_id, []).append(item)

                fork_found = False
                for siblings in children.values():
                    if len(siblings) > 1:
                        fork_found = True
                        for child in siblings:
                            to_quarantine[child.checkpoint.checkpoint_id] = (
                                "forked execution chain"
                            )

                if fork_found:
                    continue

                # Prove every accepted record is reachable from the one
                # genesis record through one linear predecessor chain.
                visited: set[str] = set()
                current: LoadedCheckpoint | None = roots[0]
                while current is not None:
                    current_id = current.checkpoint.checkpoint_id
                    if current_id in visited:
                        break
                    visited.add(current_id)
                    next_items = children.get(current_id, [])
                    current = next_items[0] if next_items else None

                for item in execution_items:
                    if item.checkpoint.checkpoint_id not in visited:
                        to_quarantine[item.checkpoint.checkpoint_id] = (
                            "execution chain is disconnected or cyclic"
                        )

        if not to_quarantine:
            break

        kept: list[LoadedCheckpoint] = []
        for item in remaining:
            checkpoint_id = item.checkpoint.checkpoint_id
            reason = to_quarantine.get(checkpoint_id)
            if reason is None:
                kept.append(item)
                continue

            quarantined_ids.add(checkpoint_id)
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=checkpoint_id,
                    path=item.path,
                    reason=reason,
                )
            )
        remaining = kept

    # Return each execution in deterministic parent-chain order.
    final_by_id = {
        item.checkpoint.checkpoint_id: item
        for item in remaining
    }
    depth_cache: dict[str, int] = {}

    def chain_depth(item: LoadedCheckpoint) -> int:
        checkpoint_id = item.checkpoint.checkpoint_id
        if checkpoint_id in depth_cache:
            return depth_cache[checkpoint_id]

        parent_id = item.checkpoint.parent_checkpoint_id
        if parent_id is None:
            depth = 0
        else:
            depth = chain_depth(final_by_id[parent_id]) + 1

        depth_cache[checkpoint_id] = depth
        return depth

    remaining.sort(
        key=lambda item: (
            item.checkpoint.execution_id,
            chain_depth(item),
            item.checkpoint.checkpoint_id,
        )
    )

    return LoadResult(
        valid=tuple(remaining),
        quarantined=tuple(quarantined),
        quarantined_checkpoint_ids=frozenset(quarantined_ids),
    )


def _load_quarantined_ids(issue_dir: Path) -> frozenset[str]:
    """Load quarantine facts fail-closed, including content-address validation."""

    quarantine_dir = _quarantine_dir(issue_dir)
    if not quarantine_dir.exists():
        return frozenset()

    try:
        expected_issue_number = int(issue_dir.name.removeprefix("issue-"))
    except ValueError as exc:
        raise CheckpointStoreUnavailable(
            f"invalid issue store directory {issue_dir}"
        ) from exc

    expected_keys = {
        "schema",
        "schema_version",
        "issue_number",
        "checkpoint_id",
        "reason",
        "quarantine_id",
    }
    ids: set[str] = set()

    for entry in quarantine_dir.iterdir():
        if not (entry.is_file() and entry.suffix == ".json"):
            continue
        try:
            import json

            record = json.loads(entry.read_bytes().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise CheckpointStoreUnavailable(
                f"unable to read quarantine record {entry}"
            ) from exc

        if not isinstance(record, dict) or set(record) != expected_keys:
            raise CheckpointStoreUnavailable(
                f"invalid quarantine record structure in {entry}"
            )
        if (
            record["schema"] != "agent-os.execution-checkpoint.quarantine"
            or record["schema_version"] != "1.0"
            or type(record["issue_number"]) is not int
            or record["issue_number"] != expected_issue_number
            or not isinstance(record["reason"], str)
            or len(record["reason"]) > 256
            or not isinstance(record["quarantine_id"], str)
        ):
            raise CheckpointStoreUnavailable(
                f"invalid quarantine record values in {entry}"
            )

        checkpoint_id = record["checkpoint_id"]
        if checkpoint_id is not None:
            prefix = "agent-os.execution-checkpoint:"
            digest = (
                checkpoint_id.removeprefix(prefix)
                if isinstance(checkpoint_id, str)
                else ""
            )
            if (
                not isinstance(checkpoint_id, str)
                or not checkpoint_id.startswith(prefix)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise CheckpointStoreUnavailable(
                    f"invalid quarantined checkpoint id in {entry}"
                )

        identity_payload = {
            key: value
            for key, value in record.items()
            if key != "quarantine_id"
        }
        expected_quarantine_id = domain_digest(
            QUARANTINE_DOMAIN, identity_payload
        )
        if (
            record["quarantine_id"] != expected_quarantine_id
            or entry.stem != expected_quarantine_id.rsplit(":", 1)[-1]
        ):
            raise CheckpointStoreUnavailable(
                f"quarantine record identity mismatch in {entry}"
            )

        if checkpoint_id is not None:
            ids.add(checkpoint_id)

    return frozenset(ids)


def store_is_available(store_root: Path | str) -> bool:
    """Bounded, side-effect-free-on-failure check that the store root is usable."""

    root = Path(store_root)
    try:
        _reject_symlink(root)
        if root.exists() and not root.is_dir():
            return False
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return False
    return True


def retention_cutoff_epoch_seconds(*, terminal: bool, now: float | None = None) -> float:
    """Retention boundary: 30 days after terminal state, 14 days otherwise."""

    reference = time.time() if now is None else now
    days = 30 if terminal else 14
    return reference - (days * 24 * 60 * 60)


def load_checkpoint_by_id(
    store_root: Path | str, issue_number: int, checkpoint_id: str
) -> ExecutionCheckpoint:
    """Bounded exact lookup of one #895 checkpoint by its descriptor-bound id.

    Reuses ``load_checkpoints`` unchanged -- full parent-chain verification,
    quarantine, and content-address reverification -- and selects the single
    matching record from its result. Fails closed rather than fabricating or
    guessing: a checkpoint that is missing, quarantined, or present more than
    once under one identity (structurally unreachable under the existing
    content-addressed atomic writes, guarded here only defensively) never
    returns a value.
    """

    if type(checkpoint_id) is not str or not checkpoint_id:
        raise TypeError("checkpoint_id must be a non-empty built-in str")

    result = load_checkpoints(store_root, issue_number)

    if checkpoint_id in result.quarantined_checkpoint_ids:
        raise CheckpointQuarantined(checkpoint_id)

    matches = [
        item.checkpoint
        for item in result.valid
        if item.checkpoint.checkpoint_id == checkpoint_id
    ]
    if not matches:
        raise CheckpointNotFound(checkpoint_id)
    if len(matches) > 1:
        raise CheckpointStoreIntegrityConflict(
            f"more than one valid record claims checkpoint_id {checkpoint_id}"
        )
    return matches[0]
