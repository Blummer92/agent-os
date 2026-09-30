"""Bounded Drive lookup for the Teacher-Directed Revision Lane (Issue #2745).

Live reproduction (2026-09-21): a teacher-directed worksheet revision
("Update the worksheet to match that decision. Keep everything else the
same.") acknowledged the plan, then froze indefinitely in a Google Drive
search ("Searching Drive for Photography Co..." with an opaque Thinking
state). The requested revision never reached a completed artifact or a
visible governed blocker.

This module is the provider-thin repository contract the host consumes. It
imports no Google client and performs no network calls itself. A host
connector implements :class:`DriveLookupClient`; the contract then
guarantees every teacher-directed revision target lookup terminates in
exactly one bounded disposition:

- ``RESOLVED`` -- exact target identity established; the authorized
  bounded revision may continue automatically.
- ``AMBIGUOUS`` -- several candidates; fails visibly and asks only for
  the smallest necessary target clarification.
- ``NOT_FOUND`` -- no candidate; fails visibly with a resumable handoff.
- ``LOOKUP_TIMEOUT`` -- attempt/elapsed bounds exhausted; fails visibly
  with a resumable handoff.
- ``LOOKUP_ERROR`` -- provider failure or invalid contract input; fails
  visibly with preserved failure detail and a resumable handoff.

Bounds enforced by the contract (repository-owned): attempt cap, elapsed
budget between provider calls, and search-scope limits (title-hint length,
page size, worksheet MIME type, ``trashed = false``). Per-call provider
latency remains host-owned: the contract requires the injected client to
bound each provider call and surface ``TimeoutError`` on expiry. A provider
call that never returns is a host contract violation, not a permitted
state; the contract documents that requirement explicitly and converts a
surfaced ``TimeoutError`` into a visible ``LOOKUP_TIMEOUT`` blocker.

The module performs no Drive mutation and grants no authority. Every
non-resolved disposition carries a teacher-visible blocker message and a
read-only resumable handoff preserving the requested revision scope, so a
recoverable lookup failure resumes from the target instead of restarting
planning.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence

from .common import (
    MAX_DETAIL_LENGTH,
    ContractValidationError,
    canonical_reason_codes,
    freeze_json,
    sanitize_detail,
    validate_reason_code,
    validate_stable_id,
    validate_text,
)

CONTRACT_ID = "revision-target-drive-lookup-v1"

# Repository-owned lookup bounds.  A teacher-directed revision target lookup
# must terminate inside these bounds; it must never wait indefinitely.
MAX_LOOKUP_ATTEMPTS = 3
MAX_LOOKUP_SECONDS = 60.0
MAX_TITLE_HINT_CHARS = 80
LOOKUP_PAGE_SIZE = 10
MAX_CANDIDATES = 10

GOOGLE_DOCS_MIME_TYPE = "application/vnd.google-apps.document"

_REASON_NAMESPACE = "artifact-drive-lookup"


class BoundedLookupDisposition(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    LOOKUP_TIMEOUT = "LOOKUP_TIMEOUT"
    LOOKUP_ERROR = "LOOKUP_ERROR"


def _reason(code: str) -> str:
    return validate_reason_code(f"{_REASON_NAMESPACE}-{code}")


TERMINAL_BLOCKER_DISPOSITIONS = frozenset(
    {
        BoundedLookupDisposition.AMBIGUOUS,
        BoundedLookupDisposition.NOT_FOUND,
        BoundedLookupDisposition.LOOKUP_TIMEOUT,
        BoundedLookupDisposition.LOOKUP_ERROR,
    }
)


class DriveLookupClient(Protocol):
    """Host-owned Drive lookup surface consumed by the bounded contract.

    Implementations must bound each provider call with a per-call timeout
    and surface :class:`TimeoutError` when the provider does not respond in
    time. A call that blocks forever violates this contract.
    """

    def search_files(self, query: str, page_size: int) -> Sequence[Mapping[str, Any]]: ...
    def get_file_metadata(self, file_id: str) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True, slots=True)
class BoundedLookupResult:
    disposition: BoundedLookupDisposition
    file_id: str | None
    candidates: tuple[Mapping[str, Any], ...]
    reason_codes: tuple[str, ...]
    user_visible_message: str
    resumable_handoff: Mapping[str, Any]
    attempts_used: int
    timed_out: bool = False
    failure_detail: str | None = None


def resolve_revision_target(
    *,
    client: DriveLookupClient | None = None,
    exact_drive_id: str | None = None,
    title_hint: str | None = None,
    changed_sections: Sequence[str] = (),
    preserved_sections: Sequence[str] = (),
    max_attempts: int = MAX_LOOKUP_ATTEMPTS,
    max_elapsed_seconds: float = MAX_LOOKUP_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> BoundedLookupResult:
    """Resolve a teacher-directed revision target through a bounded Drive lookup.

    Every path returns a terminal :class:`BoundedLookupResult`; no path
    leaves the caller waiting for more provider activity. Invalid caller
    input (bad revision scope or widened bounds) raises
    :class:`ContractValidationError` immediately.
    """
    request = _validate_revision_request(changed_sections, preserved_sections)
    bounds = _validate_bounds(max_attempts, max_elapsed_seconds)
    if client is None:
        return _blocked(
            BoundedLookupDisposition.LOOKUP_ERROR,
            _reason("client-required"),
            "I can't reach Google Drive right now, so I can't find the "
            "worksheet to revise. Please try again in a moment.",
            request,
            detail="no Drive lookup client was supplied",
        )
    if exact_drive_id is not None:
        return _resolve_by_exact_id(
            client,
            exact_drive_id,
            request,
            clock,
            budget_seconds=bounds[1],
        )
    if title_hint is not None:
        return _resolve_by_scoped_search(
            client,
            title_hint,
            request,
            max_attempts=bounds[0],
            budget_seconds=bounds[1],
            clock=clock,
        )
    return _blocked(
        BoundedLookupDisposition.LOOKUP_ERROR,
        _reason("target-identity-missing"),
        "I don't have enough information to find the worksheet to revise. "
        "Please tell me the worksheet name or its Drive link.",
        request,
        detail="neither exact_drive_id nor title_hint was supplied",
    )


def _resolve_by_exact_id(client, exact_drive_id, request, clock, *, budget_seconds):
    """Reuse an exact Drive identity; never broad-search when it is known."""
    try:
        wanted = validate_stable_id(exact_drive_id, "exact_drive_id")
    except ContractValidationError as exc:
        return _blocked(
            BoundedLookupDisposition.LOOKUP_ERROR,
            _reason("exact-id-invalid"),
            "The worksheet reference I have looks invalid, so I can't revise "
            "it yet. Please share the worksheet name or its Drive link.",
            request,
            detail=exc.detail,
        )
    started = clock()
    try:
        metadata = client.get_file_metadata(wanted)
    except Exception as exc:  # provider failure detail is preserved, not swallowed
        return _blocked(
            BoundedLookupDisposition.LOOKUP_ERROR,
            _reason("exact-metadata-failed"),
            "Google Drive didn't respond when I checked the worksheet, so I "
            "can't revise it yet. Please try again in a moment.",
            request,
            detail=sanitize_detail(str(exc)),
            elapsed=_elapsed(started, clock),
        )
    if metadata is None:
        return _blocked(
            BoundedLookupDisposition.NOT_FOUND,
            _reason("exact-id-not-found"),
            "I couldn't find that worksheet in Google Drive, so I can't "
            "revise it yet. Please check the link or tell me the worksheet "
            "name.",
            request,
            detail=f"exact drive id not found: {wanted}",
            elapsed=_elapsed(started, clock),
        )
    if not isinstance(metadata, Mapping) or metadata.get("trashed") is True:
        return _blocked(
            BoundedLookupDisposition.NOT_FOUND,
            _reason("exact-id-unusable"),
            "That worksheet isn't available to revise right now (it may be "
            "trashed or inaccessible). Please confirm the worksheet and try "
            "again.",
            request,
            detail=f"exact drive id not usable: {wanted}",
            elapsed=_elapsed(started, clock),
        )
    return BoundedLookupResult(
        disposition=BoundedLookupDisposition.RESOLVED,
        file_id=wanted,
        candidates=(),
        reason_codes=(_reason("resolved-by-exact-id"),),
        user_visible_message="",
        resumable_handoff={},
        attempts_used=1,
        timed_out=False,
        failure_detail=None,
    )


def _resolve_by_scoped_search(client, title_hint, request, *, max_attempts, budget_seconds, clock):
    try:
        hint = validate_text(title_hint, "title_hint", max_length=MAX_TITLE_HINT_CHARS)
    except (ContractValidationError, ValueError) as exc:
        detail = exc.detail if isinstance(exc, ContractValidationError) else sanitize_detail(str(exc))
        return _blocked(
            BoundedLookupDisposition.LOOKUP_ERROR,
            _reason("title-hint-invalid"),
            "The worksheet name I have is too long or unusable to search "
            "Google Drive. Please give me a shorter worksheet name.",
            request,
            detail=detail,
        )
    if not hint.strip():
        return _blocked(
            BoundedLookupDisposition.LOOKUP_ERROR,
            _reason("title-hint-empty"),
            "I don't have a worksheet name to search Google Drive. Please "
            "tell me the worksheet name or its Drive link.",
            request,
            detail="title_hint is blank",
        )
    query = _scoped_query(hint.strip())
    started = clock()
    attempts = 0
    last_detail: str | None = None
    saw_timeout = False
    while attempts < max_attempts:
        if clock() - started >= budget_seconds:
            return _blocked(
                BoundedLookupDisposition.LOOKUP_TIMEOUT,
                _reason("elapsed-budget-exhausted"),
                "Searching Google Drive for the worksheet is taking too long, "
                "so I've stopped rather than keep you waiting. Please try "
                "again, or share the worksheet's Drive link to go straight to "
                "it.",
                request,
                detail=f"elapsed budget of {budget_seconds} seconds exhausted",
                attempts=attempts,
                elapsed=clock() - started,
                timed_out=True,
            )
        attempts += 1
        try:
            raw = client.search_files(query, LOOKUP_PAGE_SIZE)
        except TimeoutError:
            last_detail = "provider search call exceeded its per-call timeout"
            saw_timeout = True
            continue
        except Exception as exc:
            last_detail = sanitize_detail(str(exc))
            continue
        candidates = _normalize_candidates(raw)
        if not candidates:
            return _blocked(
                BoundedLookupDisposition.NOT_FOUND,
                _reason("no-candidates"),
                f"I couldn't find a worksheet named '{hint.strip()}' in "
                "Google Drive, so I can't revise it yet. Please check the "
                "name or share the worksheet's Drive link.",
                request,
                detail=f"scoped search returned zero candidates for query: {query}",
                attempts=attempts,
                elapsed=_elapsed(started, clock),
            )
        if len(candidates) == 1:
            return BoundedLookupResult(
                disposition=BoundedLookupDisposition.RESOLVED,
                file_id=candidates[0]["drive_file_id"],
                candidates=tuple(),
                reason_codes=(_reason("resolved-by-scoped-search"),),
                user_visible_message="",
                resumable_handoff={},
                attempts_used=attempts,
                timed_out=False,
                failure_detail=None,
            )
        return _blocked(
            BoundedLookupDisposition.AMBIGUOUS,
            _reason("ambiguous-candidates"),
            "I found several worksheets that could match, so I can't tell "
            "which one to revise yet. Please pick one: "
            + "; ".join(f"'{c['display_name']}'" for c in candidates),
            request,
            detail=f"scoped search returned {len(candidates)} candidates",
            candidates=tuple(candidates),
            attempts=attempts,
            elapsed=_elapsed(started, clock),
        )
    # Attempt cap exhausted after repeated provider failures.
    exhausted_budget = _budget_exhausted(started, clock, budget_seconds)
    timed_out = saw_timeout or exhausted_budget
    return _blocked(
        BoundedLookupDisposition.LOOKUP_TIMEOUT if timed_out else BoundedLookupDisposition.LOOKUP_ERROR,
        _reason("attempt-cap-exhausted"),
        "Google Drive didn't return a usable result after several tries, so "
        "I've stopped rather than keep you waiting. Please try again in a "
        "moment, or share the worksheet's Drive link to go straight to it.",
        request,
        detail=last_detail or "provider search attempts exhausted",
        attempts=attempts,
        elapsed=clock() - started,
        timed_out=timed_out,
    )


def _scoped_query(hint: str) -> str:
    safe = hint.replace("'", "\\'")
    return (
        f"name contains '{safe}' and mimeType = '{GOOGLE_DOCS_MIME_TYPE}' "
        "and trashed = false"
    )


def _normalize_candidates(raw: object) -> tuple[Mapping[str, Any], ...]:
    if raw is None:
        return ()
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    candidates = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        file_id = item.get("id")
        name = item.get("name")
        if type(file_id) is not str or not file_id.strip():
            continue
        if type(name) is not str or not name.strip():
            continue
        if item.get("trashed") is True:
            continue
        candidates.append(
            {
                "drive_file_id": file_id.strip(),
                "display_name": name.strip(),
                "mime_type": item.get("mimeType"),
            }
        )
        if len(candidates) >= MAX_CANDIDATES:
            break
    return tuple(candidates)


def _validate_revision_request(changed_sections, preserved_sections):
    def _sections(value, name):
        if not isinstance(value, (list, tuple)):
            raise ContractValidationError(_reason("revision-scope-invalid"), f"{name} must be a list")
        return [validate_text(item, name, max_length=MAX_DETAIL_LENGTH) for item in value]

    return {
        "changed_sections": _sections(changed_sections, "changed_section"),
        "preserved_sections": _sections(preserved_sections, "preserved_section"),
    }


def _validate_bounds(max_attempts, max_elapsed_seconds):
    if type(max_attempts) is not int or max_attempts < 1 or max_attempts > MAX_LOOKUP_ATTEMPTS:
        raise ContractValidationError(
            _reason("attempt-bound-invalid"),
            f"max_attempts must be an int in [1, {MAX_LOOKUP_ATTEMPTS}]",
        )
    if (
        type(max_elapsed_seconds) not in (int, float)
        or not (0 < max_elapsed_seconds <= MAX_LOOKUP_SECONDS)
    ):
        raise ContractValidationError(
            _reason("elapsed-bound-invalid"),
            f"max_elapsed_seconds must be in (0, {MAX_LOOKUP_SECONDS}]",
        )
    return max_attempts, float(max_elapsed_seconds)


def _elapsed(started: float, clock: Callable[[], float]) -> float:
    return max(0.0, clock() - started)


def _budget_exhausted(started: float, clock: Callable[[], float], budget_seconds: float) -> bool:
    return _elapsed(started, clock) >= budget_seconds


def _blocked(
    disposition: BoundedLookupDisposition,
    reason_code: str,
    user_visible_message: str,
    request: Mapping[str, Any],
    *,
    detail: str | None = None,
    candidates: tuple[Mapping[str, Any], ...] = (),
    attempts: int = 0,
    elapsed: float = 0.0,
    timed_out: bool = False,
) -> BoundedLookupResult:
    codes = canonical_reason_codes((reason_code,), 32)
    handoff = freeze_json(
        {
            "contract_version": CONTRACT_ID,
            "disposition": disposition.value,
            "reason_codes": list(codes),
            "teacher_revision_request": {
                "changed_sections": list(request.get("changed_sections", [])),
                "preserved_sections": list(request.get("preserved_sections", [])),
            },
            "failure_detail": detail,
            "candidates": [dict(candidate) for candidate in candidates],
            "resume_instruction": (
                "Re-run resolve_revision_target with exact_drive_id set to the "
                "confirmed worksheet Drive file ID to continue the "
                "teacher-directed revision without broad-searching again."
            ),
            "authority": {
                "execution_authorized": False,
                "external_write_authorized": False,
                "approval_authorized": False,
                "classroom_readiness_authorized": False,
                "publication_authorized": False,
                "production_authorized": False,
            },
        }
    )
    return BoundedLookupResult(
        disposition=disposition,
        file_id=None,
        candidates=candidates,
        reason_codes=codes,
        user_visible_message=user_visible_message,
        resumable_handoff=handoff,
        attempts_used=attempts,
        timed_out=timed_out,
        failure_detail=detail,
    )
