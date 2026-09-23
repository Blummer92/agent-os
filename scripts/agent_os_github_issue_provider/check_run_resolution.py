"""Pure helpers for resolving duplicate GitHub check runs.

The resolver is deliberately separate from transport. It consumes already-fetched
check-run mappings and never performs network or repository writes.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def logical_check_identity(run: Mapping[str, object]) -> tuple[str, str | None]:
    """Return a bounded logical identity: display name plus producer app slug."""
    name = run.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("check run name is required")
    app = run.get("app")
    slug = app.get("slug") if isinstance(app, Mapping) else None
    if slug is not None and not isinstance(slug, str):
        raise ValueError("check run app slug must be text")
    return name, slug


def _ordering_key(run: Mapping[str, object]) -> tuple[datetime, int]:
    stamp = _timestamp(run.get("completed_at")) or _timestamp(run.get("started_at")) or _timestamp(run.get("created_at"))
    run_id = run.get("id")
    if stamp is None or not isinstance(run_id, int) or isinstance(run_id, bool):
        raise ValueError("duplicate check runs require timestamp and numeric id ordering evidence")
    return stamp, run_id


def authoritative_check_runs(runs: Sequence[Mapping[str, object]]) -> tuple[Mapping[str, object], ...]:
    """Collapse historical duplicate runs while preserving distinct checks.

    Duplicate identity is `(name, app.slug)`, so same-named checks from different
    producer apps remain independent. A duplicate group is resolved only when
    every member has deterministic ordering metadata. Missing/ambiguous ordering
    fails closed instead of guessing which historical result is authoritative.
    """
    groups: dict[tuple[str, str | None], list[Mapping[str, object]]] = {}
    for run in runs:
        groups.setdefault(logical_check_identity(run), []).append(run)

    resolved: list[Mapping[str, object]] = []
    for identity in sorted(groups, key=lambda item: (item[0], item[1] or "")):
        group = groups[identity]
        if len(group) == 1:
            resolved.append(group[0])
            continue
        ordered = sorted(group, key=_ordering_key)
        if len(ordered) > 1 and _ordering_key(ordered[-1]) == _ordering_key(ordered[-2]):
            raise ValueError("duplicate check run ordering is ambiguous")
        resolved.append(ordered[-1])
    return tuple(resolved)
