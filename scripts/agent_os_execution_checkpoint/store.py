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
    MAX_SERIALIZED_BYTES,
    ExecutionCheckpoint,
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


def _atomic_write(directory: Path, filename: str, payload: bytes) -> Path:
    """Write payload to directory/filename atomically via temp-then-rename.

    If the destination already exists with identical bytes, this is a
    no-op success (idempotent duplicate). If it exists with *different*
    bytes, raises ``CheckpointStoreIntegrityConflict`` rather than
    silently overwriting -- content-addressed filenames should never
    legitimately disagree with their own content.
    """

    final_path = directory / filename
    _reject_symlink(final_path)
    if final_path.exists():
        existing = final_path.read_bytes()
        if existing == payload:
            return final_path
        raise CheckpointStoreIntegrityConflict(
            f"content-addressed path already holds different content: {final_path}"
        )

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
        os.replace(temp_name, os.fspath(final_path))
        temp_name = None
    except OSError as exc:
        raise CheckpointStoreUnavailable(f"unable to write {final_path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temp_name is not None and os.path.exists(temp_name):
            os.remove(temp_name)
    return final_path


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

    already_present = (checkpoints_dir / filename).exists()
    if not already_present:
        count, total_bytes = _existing_records_footprint(checkpoints_dir)
        if count + 1 > MAX_RECORDS_PER_ISSUE or total_bytes + len(payload) > MAX_BYTES_PER_ISSUE:
            raise CheckpointStoreCapacityExceeded(
                f"issue {checkpoint.issue_number} checkpoint store is at capacity"
            )

    path = _atomic_write(checkpoints_dir, filename, payload)

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
    _ensure_dir(issue_dir)
    payload = (checkpoint_id + "\n").encode("utf-8")
    _atomic_write(issue_dir, "HEAD.tmp-target", payload)
    # HEAD itself is a plain mutable pointer (not content-addressed), so it
    # is written directly rather than through the content-addressed helper.
    head_path = _head_path(issue_dir)
    _reject_symlink(head_path)
    (issue_dir / "HEAD.tmp-target").replace(head_path)


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
    return _atomic_write(quarantine_dir, filename, payload)


def load_checkpoints(store_root: Path | str, issue_number: int) -> LoadResult:
    """Load, verify, and reconstruct every record for one issue.

    Every stored file is independently verified: its content must parse,
    its schema must validate, and its embedded ``checkpoint_id`` must equal
    the filename's hex suffix (recomputed from content, not trusted from
    the name). A file failing any of these is reported in ``quarantined``,
    never raised -- one bad record never blocks reading the rest.
    """

    issue_dir = issue_store_dir(Path(store_root), issue_number)
    _reject_symlink(issue_dir)
    checkpoints_dir = _checkpoints_dir(issue_dir)
    if not checkpoints_dir.exists():
        return LoadResult(valid=(), quarantined=(), quarantined_checkpoint_ids=frozenset())

    already_quarantined = _load_quarantined_ids(issue_dir)

    valid: list[LoadedCheckpoint] = []
    quarantined: list[QuarantinedEntry] = []
    for entry in sorted(checkpoints_dir.iterdir()):
        if not (entry.is_file() and entry.suffix == ".json"):
            continue
        try:
            payload = entry.read_bytes()
        except OSError as exc:
            quarantined.append(
                QuarantinedEntry(checkpoint_id=None, path=entry, reason=f"unreadable: {exc}")
            )
            continue
        try:
            checkpoint = deserialize_checkpoint(payload)
        except (TypeError, ValueError) as exc:
            quarantined.append(
                QuarantinedEntry(checkpoint_id=None, path=entry, reason=f"invalid: {exc}")
            )
            continue

        expected_filename = _filename_for_checkpoint_id(checkpoint.checkpoint_id)
        if entry.name != expected_filename:
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=checkpoint.checkpoint_id,
                    path=entry,
                    reason="filename does not match recomputed checkpoint_id",
                )
            )
            continue

        if checkpoint.checkpoint_id in already_quarantined:
            quarantined.append(
                QuarantinedEntry(
                    checkpoint_id=checkpoint.checkpoint_id,
                    path=entry,
                    reason="previously quarantined",
                )
            )
            continue

        valid.append(LoadedCheckpoint(checkpoint=checkpoint, path=entry))

    quarantined_ids = frozenset(
        entry.checkpoint_id for entry in quarantined if entry.checkpoint_id is not None
    ) | already_quarantined

    # Any record whose parent_checkpoint_id is quarantined is itself
    # quarantined (descendant quarantine), applied to a fixed point so
    # multi-generation chains are fully caught.
    remaining = valid
    changed = True
    while changed:
        changed = False
        kept: list[LoadedCheckpoint] = []
        for item in remaining:
            parent = item.checkpoint.parent_checkpoint_id
            if parent is not None and parent in quarantined_ids:
                quarantined.append(
                    QuarantinedEntry(
                        checkpoint_id=item.checkpoint.checkpoint_id,
                        path=item.path,
                        reason="descendant of a quarantined checkpoint",
                    )
                )
                quarantined_ids = quarantined_ids | {item.checkpoint.checkpoint_id}
                changed = True
            else:
                kept.append(item)
        remaining = kept

    return LoadResult(
        valid=tuple(remaining),
        quarantined=tuple(quarantined),
        quarantined_checkpoint_ids=frozenset(quarantined_ids),
    )


def _load_quarantined_ids(issue_dir: Path) -> frozenset[str]:
    quarantine_dir = _quarantine_dir(issue_dir)
    if not quarantine_dir.exists():
        return frozenset()
    ids: set[str] = set()
    for entry in quarantine_dir.iterdir():
        if not (entry.is_file() and entry.suffix == ".json"):
            continue
        try:
            import json

            record = json.loads(entry.read_bytes().decode("utf-8"))
        except (OSError, ValueError):
            continue
        checkpoint_id = record.get("checkpoint_id") if isinstance(record, dict) else None
        if isinstance(checkpoint_id, str):
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
