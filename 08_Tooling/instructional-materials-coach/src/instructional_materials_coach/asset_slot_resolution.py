"""Build-time validation that selected asset slots resolve to live Drive files.

This module is pure repository-side resolution: the caller supplies a
``describe_drive_file`` lookup (the CLI wires it to ``drive_client.get_file_metadata``)
so this module performs no Workspace calls and grants no external-write
authority.

An asset slot is *resolved* only when the lookup returns metadata for a
non-trashed Drive file. Any other outcome -- missing binding, lookup failure,
trashed file -- marks the slot *unresolvable* so the build fails closed instead
of emitting a labeled placeholder for a file that does not exist (#3130).

Content identity (#3256)
------------------------
Callers may additionally supply ``expected_content_identities`` mapping asset
IDs to the canonical content identity recorded at approval/selection. When an
expected identity is present, the slot's live Drive metadata must verify
against it:

- ``content-identity-match`` -> the slot resolves as before;
- ``content-identity-mismatch`` -> the slot fails closed per asset with the
  explicit ``content-identity-mismatch`` outcome. A mismatch is never absence
  and never authorizes a generation handoff;
- ``content-identity-unverifiable`` -> the slot fails closed as a distinct
  non-absence state.

Lookup failures are classified per slot: ``not-found`` (deleted),
``no-access`` (permission gap), and ``unresolvable`` (any other failure) are
distinct outcomes. The legacy ``resolved_slots`` / ``unresolvable_slots`` /
``status`` fields are preserved: ``unresolvable_slots`` names every slot that
did not resolve, whatever the reason; ``slot_outcomes`` carries the
fine-grained per-slot outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from instructional_workflow_contracts.asset_content_identity import (
    OUTCOME_MISMATCH,
    OUTCOME_UNVERIFIABLE,
    verify_content_identity,
)


@dataclass(frozen=True)
class AssetSlotResolutionResult:
    status: str
    resolved_slots: tuple[str, ...] = ()
    unresolvable_slots: tuple[str, ...] = ()
    slot_outcomes: Mapping[str, str] = field(default_factory=dict)
    content_identity_mismatches: tuple[str, ...] = ()


def _lookup_outcome(describe_drive_file: Callable[[str], Mapping[str, Any]], file_id: str) -> tuple[str, Mapping[str, Any] | None]:
    """Run the lookup and classify the outcome.

    Understands three shapes: a raw metadata mapping (legacy), an outcome
    envelope ``{"outcome": ..., "metadata": ...}`` (see
    ``drive_client.describe_drive_file_outcome``), and a raised exception
    (optionally carrying a ``drive_outcome`` attribute, as raised by
    ``drive_client.DriveLookupError``).
    """
    try:
        result = describe_drive_file(file_id)
    except Exception as exc:  # noqa: BLE001 - classified below
        outcome = getattr(exc, "drive_outcome", None)
        if outcome not in ("not-found", "no-access", "lookup-failed"):
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 404:
                outcome = "not-found"
            elif status == 403:
                outcome = "no-access"
            else:
                outcome = "lookup-failed"
        return outcome, None
    if isinstance(result, Mapping) and "outcome" in result:
        outcome = result.get("outcome")
        metadata = result.get("metadata")
        if outcome == "ok" and isinstance(metadata, Mapping):
            return "ok", metadata
        if outcome in ("not-found", "no-access", "lookup-failed"):
            return outcome, None
        return "lookup-failed", None
    if isinstance(result, Mapping):
        return "ok", result
    return "lookup-failed", None


def resolve_asset_slots(
    *,
    asset_slots: Mapping[str, str | None],
    describe_drive_file: Callable[[str], Mapping[str, Any]],
    expected_content_identities: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> AssetSlotResolutionResult:
    """Resolve every required asset slot to a live Drive file.

    ``asset_slots`` maps governed asset IDs to their candidate Drive file IDs.
    ``describe_drive_file`` must return file metadata for a live Drive file ID
    and raise for anything that cannot be described (not found, no access), or
    return a governed outcome envelope.

    ``expected_content_identities`` optionally maps asset IDs to the canonical
    content identity recorded at approval/selection (#3256). A slot whose live
    metadata does not verify against its expected identity fails closed with
    the explicit ``content-identity-mismatch`` outcome.
    """
    expected = expected_content_identities or {}
    resolved: list[str] = []
    unresolvable: list[str] = []
    mismatches: list[str] = []
    outcomes: dict[str, str] = {}
    for asset_id, drive_file_id in sorted(asset_slots.items()):
        if not drive_file_id:
            outcomes[asset_id] = "unresolvable"
            unresolvable.append(asset_id)
            continue
        outcome, metadata = _lookup_outcome(describe_drive_file, drive_file_id)
        if outcome != "ok" or metadata is None:
            outcomes[asset_id] = outcome if outcome in ("not-found", "no-access") else "unresolvable"
            unresolvable.append(asset_id)
            continue
        if (
            metadata.get("id") != drive_file_id
            or metadata.get("trashed") is not False
        ):
            outcomes[asset_id] = "unresolvable"
            unresolvable.append(asset_id)
            continue
        expected_identity = expected.get(asset_id)
        if expected_identity is not None:
            verified = verify_content_identity(expected=expected_identity, metadata=metadata)
            if verified == OUTCOME_MISMATCH:
                outcomes[asset_id] = OUTCOME_MISMATCH
                mismatches.append(asset_id)
                unresolvable.append(asset_id)
                continue
            if verified == OUTCOME_UNVERIFIABLE:
                outcomes[asset_id] = OUTCOME_UNVERIFIABLE
                unresolvable.append(asset_id)
                continue
        outcomes[asset_id] = "resolved"
        resolved.append(asset_id)
    if unresolvable:
        return AssetSlotResolutionResult(
            "unresolvable",
            tuple(resolved),
            tuple(unresolvable),
            dict(outcomes),
            tuple(mismatches),
        )
    return AssetSlotResolutionResult("resolved", tuple(resolved), (), dict(outcomes), ())
