"""Fail-closed admission for the #2283 bounded GitHub-controlled Notion read.

Admission is pure: it reads no environment variable, opens no socket, and never
touches a credential. Every identity, target, replay, vocabulary, and source
constraint is decided here so that the single downstream gate
(``secret_dispatch_authorized``) can guard every secret-bearing step.

The low-trust GitHub envelope is validated upstream by the existing governed
``issue_comment`` ingress. This module re-verifies the repository and actor from
caller-supplied expectations rather than trusting the transport file alone.
"""

from __future__ import annotations

from typing import Mapping

from navigation_registry.connectors.curriculum_evidence_orchestrator import (
    CurriculumReadRequest,
    build_curriculum_read_plan,
)

from .models import (
    INGRESS_REASON,
    REQUEST_CLASS_INTENT,
    REQUEST_CLASSES,
    NotionReadAdmission,
    NotionReadCatalog,
    looks_like_notion_id,
)

_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def build_curriculum_read_request(request_class: str) -> CurriculumReadRequest:
    """Return the already-resolved #980 intent for one finite request class."""
    intent = REQUEST_CLASS_INTENT.get(request_class)
    if intent is None:
        raise KeyError(request_class)
    return CurriculumReadRequest(
        action=str(intent["action"]),
        artifact_type=str(intent["artifact_type"]),
        requires_reusable_assets=bool(intent["requires_reusable_assets"]),
    )


def required_logical_sources(request_class: str) -> tuple[str, ...]:
    """Return the #980 plan's logical sources for one request class.

    The plan is *read*, never re-derived: request sensitivity and relation-first
    Visual Asset Library behavior stay owned by #980/#971.
    """
    plan = build_curriculum_read_plan(build_curriculum_read_request(request_class))
    ordered: list[str] = []
    for step in plan.steps:
        if step.logical_source not in ordered:
            ordered.append(step.logical_source)
    return tuple(ordered)


def admit_notion_read_request(
    transport: object,
    *,
    catalog: NotionReadCatalog,
    expected_repository: str,
    expected_actor: str,
) -> NotionReadAdmission:
    """Decide whether one transport envelope may reach a secret-bearing step."""
    if not isinstance(transport, Mapping):
        return _reject(expected_repository, "transport-malformed")

    if transport.get("status") != "accepted":
        return _reject(expected_repository, "transport-not-accepted")
    if transport.get("reason") != INGRESS_REASON:
        return _reject(expected_repository, "transport-reason-mismatch")
    for claim in ("execution_authorized", "scheduler_invoked", "side_effects_performed"):
        if transport.get(claim) is not False:
            return _reject(expected_repository, "transport-claims-authority")

    if expected_repository != catalog.repository:
        return _reject(expected_repository, "repository-mismatch")
    if transport.get("repository") != expected_repository:
        return _reject(expected_repository, "repository-mismatch")

    run_attempt = transport.get("run_attempt")
    if type(run_attempt) is not int or run_attempt != 1:
        return _reject(expected_repository, "run-attempt-replay")

    if transport.get("actor") != expected_actor:
        return _reject(expected_repository, "actor-not-allowed")

    request_id = transport.get("notion_read_request_id_or_none")
    if not _valid_slug(request_id):
        return _reject(expected_repository, "request-id-malformed")

    record = catalog.request(request_id)
    if record is None:
        return _reject(expected_repository, "request-id-unknown", request_id=request_id)

    issue_number = transport.get("issue_number")
    if type(issue_number) is not int or issue_number != record.issue_number:
        return _reject(
            expected_repository, "issue-target-mismatch", request_id=request_id
        )

    if record.request_class not in REQUEST_CLASSES:
        return _reject(
            expected_repository, "request-class-not-allowed", request_id=request_id
        )

    unit = catalog.canonical_unit(record.canonical_unit_key)
    if unit is None:
        return _reject(
            expected_repository, "canonical-unit-unknown", request_id=request_id
        )
    if not unit.dispatchable:
        return _reject(
            expected_repository, "canonical-unit-unverified", request_id=request_id
        )

    sources = required_logical_sources(record.request_class)
    for logical_source in sources:
        binding = catalog.source(logical_source)
        if binding is None:
            return _reject(
                expected_repository, "source-not-allowlisted", request_id=request_id
            )
        if not binding.dispatchable:
            return _reject(
                expected_repository, "source-unverified", request_id=request_id
            )

    return NotionReadAdmission(
        status="admitted",
        reason_codes=("admitted",),
        repository=expected_repository,
        issue_number=issue_number,
        request_id=record.request_id,
        request_class=record.request_class,
        canonical_unit_key=record.canonical_unit_key,
        required_logical_sources=sources,
        secret_dispatch_authorized=True,
    )


def _valid_slug(value: object) -> bool:
    """Re-check the slug shape independently of the transport parser.

    The ingress already rejects a bare Notion id, but this path must not depend
    on a transport file it did not produce, so the same structural refusal is
    restated on this side of the boundary.
    """
    return (
        type(value) is str
        and 3 <= len(value) <= 63
        and not set(value) - _SLUG_CHARS
        and not value.startswith("-")
        and not value.endswith("-")
        and "--" not in value
        and not looks_like_notion_id(value)
    )


def _reject(
    repository: str, reason: str, *, request_id: str | None = None
) -> NotionReadAdmission:
    return NotionReadAdmission(
        status="rejected",
        reason_codes=(reason,),
        repository=repository,
        request_id=request_id,
        secret_dispatch_authorized=False,
    )


__all__ = [
    "admit_notion_read_request",
    "build_curriculum_read_request",
    "required_logical_sources",
]
