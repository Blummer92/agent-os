"""Build-time validation that selected asset slots resolve to live Drive files.

This module is pure repository-side resolution: the caller supplies a
``describe_drive_file`` lookup (the CLI wires it to ``drive_client.get_file_metadata``)
so this module performs no Workspace calls and grants no external-write
authority.

An asset slot is *resolved* only when the lookup returns metadata for a
non-trashed Drive file. Any other outcome -- missing binding, lookup failure,
trashed file -- marks the slot *unresolvable* so the build fails closed instead
of emitting a labeled placeholder for a file that does not exist (#3130).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class AssetSlotResolutionResult:
    status: str
    resolved_slots: tuple[str, ...] = ()
    unresolvable_slots: tuple[str, ...] = ()


def resolve_asset_slots(
    *,
    asset_slots: Mapping[str, str | None],
    describe_drive_file: Callable[[str], Mapping[str, Any]],
) -> AssetSlotResolutionResult:
    """Resolve every required asset slot to a live Drive file.

    ``asset_slots`` maps governed asset IDs to their candidate Drive file IDs.
    ``describe_drive_file`` must return file metadata for a live Drive file ID
    and raise for anything that cannot be described (not found, no access).
    """
    resolved: list[str] = []
    unresolvable: list[str] = []
    for asset_id, drive_file_id in sorted(asset_slots.items()):
        if not drive_file_id:
            unresolvable.append(asset_id)
            continue
        try:
            metadata = describe_drive_file(drive_file_id)
        except Exception:
            unresolvable.append(asset_id)
            continue
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("id") != drive_file_id
            or metadata.get("trashed") is not False
        ):
            unresolvable.append(asset_id)
            continue
        resolved.append(asset_id)
    if unresolvable:
        return AssetSlotResolutionResult("unresolvable", tuple(resolved), tuple(unresolvable))
    return AssetSlotResolutionResult("resolved", tuple(resolved), ())
