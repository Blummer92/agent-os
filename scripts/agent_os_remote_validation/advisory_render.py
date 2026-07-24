from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from .advisory_gate import (
    AdvisoryEvidenceResult,
    advisory_evidence_result_id,
    serialize_advisory_evidence_result,
)

ADVISORY_RENDER_SCHEMA_NAME = "agent-os-advisory-evidence-render"
ADVISORY_RENDER_SCHEMA_VERSION = "1.0"
MAX_RENDER_LINES = 256
MAX_RENDER_LINE_LENGTH = 8192
MAX_RENDER_SERIALIZED_BYTES = 262_144

_NOTICE_LINES = (
    "advisory_only=true",
    "authoritative=false",
    "implementation_authorized=false",
    "execution_authorized=false",
    "merge_authorized=false",
    "attestation_verified=false",
    "freshness_proven=false",
    "provenance_verified=false",
    "side_effects_performed=false",
)


@dataclass(frozen=True, slots=True, kw_only=True)
class AdvisoryRenderResult:
    schema_name: str
    schema_version: str
    render_id: str
    advisory_result_id: str
    status: str
    lines: tuple[str, ...]
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    attestation_verified: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def render_advisory_evidence(result: object) -> AdvisoryRenderResult:
    """Render one verified GEX3 result without I/O or authority expansion."""
    if not isinstance(result, AdvisoryEvidenceResult):
        raise TypeError("result must be AdvisoryEvidenceResult")

    serialized = serialize_advisory_evidence_result(result)
    verified_id = advisory_evidence_result_id(result)
    if serialized["result_id"] != verified_id:
        raise ValueError("advisory result identity mismatch")

    lines = _render_lines(serialized)
    preliminary = AdvisoryRenderResult(
        schema_name=ADVISORY_RENDER_SCHEMA_NAME,
        schema_version=ADVISORY_RENDER_SCHEMA_VERSION,
        render_id="",
        advisory_result_id=verified_id,
        status=str(serialized["status"]),
        lines=lines,
        reason_codes=tuple(result.reason_codes),
        details=tuple(result.details),
    )
    payload = _render_payload(preliminary)
    _validate_payload(payload)
    render_id = "advisory-render:" + _semantic_digest(payload)
    return AdvisoryRenderResult(
        schema_name=preliminary.schema_name,
        schema_version=preliminary.schema_version,
        render_id=render_id,
        advisory_result_id=preliminary.advisory_result_id,
        status=preliminary.status,
        lines=preliminary.lines,
        reason_codes=preliminary.reason_codes,
        details=preliminary.details,
    )


def observe_advisory_evidence_shadow(
    results: object,
) -> tuple[AdvisoryRenderResult, ...]:
    """Return deterministic in-memory render observations for canonical fixtures."""
    if not isinstance(results, tuple):
        raise TypeError("results must be a tuple of AdvisoryEvidenceResult values")
    rendered = tuple(render_advisory_evidence(result) for result in results)
    if len({item.advisory_result_id for item in rendered}) != len(rendered):
        raise ValueError("duplicate advisory result identity in shadow observation")
    return rendered


def serialize_advisory_render_result(
    result: AdvisoryRenderResult,
) -> dict[str, object]:
    """Return verified JSON-compatible render evidence."""
    if not isinstance(result, AdvisoryRenderResult):
        raise TypeError("result must be AdvisoryRenderResult")
    payload = _render_payload(result)
    _validate_payload(payload)
    expected = "advisory-render:" + _semantic_digest(payload)
    if result.render_id != expected:
        raise ValueError("advisory render ID mismatch")
    serialized = dict(payload)
    serialized["render_id"] = result.render_id
    if len(_canonical_bytes(serialized)) > MAX_RENDER_SERIALIZED_BYTES:
        raise ValueError("advisory render exceeds canonical size limit")
    return serialized


def advisory_render_result_id(result: AdvisoryRenderResult) -> str:
    """Return the verified domain-separated render identity."""
    return str(serialize_advisory_render_result(result)["render_id"])


def _render_lines(serialized: dict[str, object]) -> tuple[str, ...]:
    repository = serialized.get("repository_identity")
    lines = [
        _line("advisory_result_id", serialized.get("result_id")),
        _line("status", serialized.get("status")),
        _line("repository_identity", repository),
        _line("pull_request", serialized.get("pull_request")),
        _line("base_branch", serialized.get("base_branch")),
        _line("base_sha", serialized.get("base_sha")),
        _line("source_head_sha", serialized.get("source_head_sha")),
        _line("tested_sha", serialized.get("tested_sha")),
        _line("plan_id", serialized.get("plan_id")),
        _line("bundle_id", serialized.get("bundle_id")),
        _line("runner_id", serialized.get("runner_id")),
        _line("invocation_id", serialized.get("invocation_id")),
        _line("command_result_ids", serialized.get("command_result_ids")),
        _line("command_result_statuses", serialized.get("command_result_statuses")),
        _line("reason_codes", serialized.get("reason_codes")),
        _line("details", serialized.get("details")),
        *_NOTICE_LINES,
    ]
    if len(lines) > MAX_RENDER_LINES:
        raise ValueError("too many advisory render lines")
    for line in lines:
        if len(line) > MAX_RENDER_LINE_LENGTH:
            raise ValueError("advisory render line exceeds limit")
    return tuple(lines)


def _line(name: str, value: object) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return f"{name}={rendered}"


def _render_payload(result: AdvisoryRenderResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "advisory_result_id": result.advisory_result_id,
        "status": result.status,
        "lines": list(result.lines),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
        "authoritative": False,
        "execution_authorized": False,
        "merge_authorized": False,
        "attestation_verified": False,
        "side_effects_performed": False,
    }


def _validate_payload(payload: dict[str, object]) -> None:
    if payload.get("schema_name") != ADVISORY_RENDER_SCHEMA_NAME:
        raise ValueError("unsupported advisory render schema name")
    if payload.get("schema_version") != ADVISORY_RENDER_SCHEMA_VERSION:
        raise ValueError("unsupported advisory render schema version")
    for field_name in (
        "authoritative",
        "execution_authorized",
        "merge_authorized",
        "attestation_verified",
        "side_effects_performed",
    ):
        if payload.get(field_name) is not False:
            raise ValueError(f"{field_name} must remain false")
    lines = payload.get("lines")
    if not isinstance(lines, list) or len(lines) > MAX_RENDER_LINES:
        raise ValueError("invalid advisory render lines")
    for line in lines:
        if not isinstance(line, str) or len(line) > MAX_RENDER_LINE_LENGTH:
            raise ValueError("invalid advisory render line")
    if len(_canonical_bytes(payload)) > MAX_RENDER_SERIALIZED_BYTES:
        raise ValueError("advisory render exceeds canonical size limit")


def _semantic_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        b"agent-os-advisory-evidence-render:v1\0" + _canonical_bytes(payload)
    ).hexdigest()


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
