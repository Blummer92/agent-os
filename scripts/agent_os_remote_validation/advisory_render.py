from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from .advisory_gate import (
    MAX_ADVISORY_DETAILS,
    MAX_ADVISORY_REASON_CODES,
    MAX_ADVISORY_STRING_LENGTH,
    AdvisoryEvidenceResult,
    advisory_evidence_result_id,
    serialize_advisory_evidence_result,
)

ADVISORY_RENDER_SCHEMA_NAME = "agent-os-advisory-evidence-render"
ADVISORY_RENDER_SCHEMA_VERSION = "1.0"
MAX_RENDER_LINES = 256
MAX_RENDER_LINE_LENGTH = 8192
MAX_RENDER_SERIALIZED_BYTES = 262_144

_ADVISORY_STATUSES = {
    "passed",
    "failed",
    "incomplete",
    "stale",
    "invalid",
    "needs-decision",
}
_RENDER_FIELD_NAMES = (
    "advisory_result_id",
    "status",
    "repository_identity",
    "pull_request",
    "base_branch",
    "base_sha",
    "source_head_sha",
    "tested_sha",
    "plan_id",
    "bundle_id",
    "runner_id",
    "invocation_id",
    "command_result_ids",
    "command_result_statuses",
    "reason_codes",
    "details",
)
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
    implementation_authorized: Literal[False] = field(default=False, init=False)
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
    values = (
        serialized.get("result_id"),
        serialized.get("status"),
        serialized.get("repository_identity"),
        serialized.get("pull_request"),
        serialized.get("base_branch"),
        serialized.get("base_sha"),
        serialized.get("source_head_sha"),
        serialized.get("tested_sha"),
        serialized.get("plan_id"),
        serialized.get("bundle_id"),
        serialized.get("runner_id"),
        serialized.get("invocation_id"),
        serialized.get("command_result_ids"),
        serialized.get("command_result_statuses"),
        serialized.get("reason_codes"),
        serialized.get("details"),
    )
    lines = [
        *(_line(name, value) for name, value in zip(_RENDER_FIELD_NAMES, values)),
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
        "implementation_authorized": False,
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
    if payload.get("status") not in _ADVISORY_STATUSES:
        raise ValueError("unsupported advisory render status")
    if not _is_advisory_result_id(payload.get("advisory_result_id")):
        raise ValueError("invalid advisory result identity")
    for field_name in (
        "authoritative",
        "implementation_authorized",
        "execution_authorized",
        "merge_authorized",
        "attestation_verified",
        "side_effects_performed",
    ):
        if payload.get(field_name) is not False:
            raise ValueError(f"{field_name} must remain false")

    reason_codes = _validate_string_list(
        payload.get("reason_codes"),
        field_name="reason_codes",
        maximum=MAX_ADVISORY_REASON_CODES,
    )
    details = _validate_string_list(
        payload.get("details"),
        field_name="details",
        maximum=MAX_ADVISORY_DETAILS,
    )

    lines = payload.get("lines")
    expected_count = len(_RENDER_FIELD_NAMES) + len(_NOTICE_LINES)
    if not isinstance(lines, list) or len(lines) != expected_count:
        raise ValueError("invalid advisory render lines")
    for index, name in enumerate(_RENDER_FIELD_NAMES):
        line = lines[index]
        if (
            not isinstance(line, str)
            or len(line) > MAX_RENDER_LINE_LENGTH
            or "\n" in line
            or "\r" in line
            or not line.startswith(f"{name}=")
        ):
            raise ValueError("invalid advisory render line")
    if tuple(lines[len(_RENDER_FIELD_NAMES) :]) != _NOTICE_LINES:
        raise ValueError("advisory authority notices are missing or altered")

    if _line_value(lines[0]) != payload["advisory_result_id"]:
        raise ValueError("rendered advisory identity mismatch")
    if _line_value(lines[1]) != payload["status"]:
        raise ValueError("rendered advisory status mismatch")
    if _line_value(lines[14]) != reason_codes:
        raise ValueError("rendered reason codes mismatch")
    if _line_value(lines[15]) != details:
        raise ValueError("rendered details mismatch")

    if len(_canonical_bytes(payload)) > MAX_RENDER_SERIALIZED_BYTES:
        raise ValueError("advisory render exceeds canonical size limit")


def _validate_string_list(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"invalid advisory render {field_name}")
    for item in value:
        if not isinstance(item, str) or len(item) > MAX_ADVISORY_STRING_LENGTH:
            raise ValueError(f"invalid advisory render {field_name}")
    return value


def _line_value(line: str) -> object:
    return json.loads(line.split("=", 1)[1])


def _is_advisory_result_id(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("advisory-evidence:"):
        return False
    digest = value.removeprefix("advisory-evidence:")
    return len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


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
