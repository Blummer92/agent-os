from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Literal

MAIN_HEALTH_SCHEMA_NAME = "agent-os-main-health"
MAIN_HEALTH_SCHEMA_VERSION = "1.0"

HealthState = Literal["healthy", "unhealthy", "unknown"]
AdmissionDisposition = Literal["ordinary-open", "ordinary-frozen", "recovery-only"]
ValidationConclusion = Literal[
    "success",
    "repository-failure",
    "infrastructure-failure",
    "pending",
    "missing",
    "cancelled",
]


@dataclass(frozen=True, slots=True, kw_only=True)
class MainHealthResult:
    schema_name: str = MAIN_HEALTH_SCHEMA_NAME
    schema_version: str = MAIN_HEALTH_SCHEMA_VERSION
    result_id: str
    repository: str
    main_sha: str
    evidence_sha: str | None
    health: HealthState
    ordinary_admission_allowed: bool
    recovery_admission_allowed: bool
    disposition: AdmissionDisposition
    reason_codes: tuple[str, ...]
    authoritative: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    revert_authorized: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)


def project_main_health(
    *,
    repository: object,
    current_main_sha: object,
    evidence_sha: object | None,
    validation_conclusion: object,
    recovery_requested: bool = False,
) -> MainHealthResult:
    """Project existing post-merge evidence into exact-main health.

    This pure function does not fetch CI, mutate GitHub, authorize a merge/revert,
    or diagnose a candidate PR.  Callers must supply current canonical main and
    already-classified post-merge validation evidence.
    """
    if not _text(repository) or not _sha(current_main_sha):
        return _result(
            repository,
            current_main_sha,
            evidence_sha,
            "unknown",
            False,
            False,
            "ordinary-frozen",
            ("main-health.identity-invalid",),
        )
    if not isinstance(recovery_requested, bool):
        return _result(
            repository,
            current_main_sha,
            evidence_sha,
            "unknown",
            False,
            False,
            "ordinary-frozen",
            ("main-health.recovery-request-invalid",),
        )
    if evidence_sha != current_main_sha:
        reason = (
            "main-health.evidence-missing"
            if evidence_sha is None
            else "main-health.evidence-stale"
        )
        return _result(
            repository,
            current_main_sha,
            evidence_sha,
            "unknown",
            False,
            recovery_requested,
            "recovery-only" if recovery_requested else "ordinary-frozen",
            (reason,),
        )

    if validation_conclusion == "success":
        return _result(
            repository,
            current_main_sha,
            evidence_sha,
            "healthy",
            True,
            recovery_requested,
            "ordinary-open",
            ("main-health.exact-main-green",),
        )
    if validation_conclusion == "repository-failure":
        return _result(
            repository,
            current_main_sha,
            evidence_sha,
            "unhealthy",
            False,
            recovery_requested,
            "recovery-only" if recovery_requested else "ordinary-frozen",
            ("main-health.exact-main-red",),
        )
    if validation_conclusion == "infrastructure-failure":
        return _result(
            repository,
            current_main_sha,
            evidence_sha,
            "unknown",
            False,
            recovery_requested,
            "recovery-only" if recovery_requested else "ordinary-frozen",
            ("main-health.infrastructure-unproven",),
        )
    if validation_conclusion == "pending":
        reason = "main-health.validation-pending"
    elif validation_conclusion == "cancelled":
        reason = "main-health.validation-cancelled"
    elif validation_conclusion == "missing":
        reason = "main-health.validation-missing"
    else:
        reason = "main-health.validation-invalid"
    return _result(
        repository,
        current_main_sha,
        evidence_sha,
        "unknown",
        False,
        recovery_requested,
        "recovery-only" if recovery_requested else "ordinary-frozen",
        (reason,),
    )


def serialize_main_health(result: MainHealthResult) -> dict[str, object]:
    if not isinstance(result, MainHealthResult):
        raise TypeError("result must be MainHealthResult")
    payload = _payload(result)
    expected = "main-health:" + _digest(payload)
    if result.result_id != expected:
        raise ValueError("main health result ID mismatch")
    serialized = dict(payload)
    serialized["result_id"] = result.result_id
    return serialized


def main_health_result_id(result: MainHealthResult) -> str:
    return str(serialize_main_health(result)["result_id"])


def _result(
    repository: object,
    main_sha: object,
    evidence_sha: object | None,
    health: HealthState,
    ordinary_allowed: bool,
    recovery_allowed: bool,
    disposition: AdmissionDisposition,
    reasons: tuple[str, ...],
) -> MainHealthResult:
    preliminary = MainHealthResult(
        result_id="",
        repository=repository if _text(repository) else "unavailable",
        main_sha=main_sha if _sha(main_sha) else "unavailable",
        evidence_sha=evidence_sha if _sha(evidence_sha) else None,
        health=health,
        ordinary_admission_allowed=ordinary_allowed,
        recovery_admission_allowed=recovery_allowed,
        disposition=disposition,
        reason_codes=tuple(sorted(set(reasons))),
    )
    return replace(preliminary, result_id="main-health:" + _digest(_payload(preliminary)))


def _payload(result: MainHealthResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "repository": result.repository,
        "main_sha": result.main_sha,
        "evidence_sha": result.evidence_sha,
        "health": result.health,
        "ordinary_admission_allowed": result.ordinary_admission_allowed,
        "recovery_admission_allowed": result.recovery_admission_allowed,
        "disposition": result.disposition,
        "reason_codes": list(result.reason_codes),
        "authoritative": False,
        "merge_authorized": False,
        "revert_authorized": False,
        "side_effects_performed": False,
    }


def _digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(b"agent-os-main-health:v1\0" + encoded).hexdigest()


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 512


def _sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)
