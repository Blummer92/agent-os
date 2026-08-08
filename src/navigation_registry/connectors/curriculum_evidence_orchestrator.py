"""Bounded live-read orchestration for current curriculum evidence.

The orchestrator consumes already-resolved teacher intent and canonical curriculum
identity. It plans provider-specific reads but performs no network access itself.
Callers inject the existing #936 read executor and the Navigation Registry remains
the identity/normalization boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from instructional_workflow_contracts.current_curriculum_evidence import (
    assemble_current_curriculum_evidence,
)
from instructional_workflow_contracts.current_curriculum_state import (
    resolve_current_curriculum_state,
)

MAX_RESULTS = 24

CANONICAL_UNIT = "canonical-unit"
UNIT_ALIGNMENT = "unit-alignment"
MODELING = "teacher-modeling"
PACKET = "daily-generation-packet"
SOURCE_CONTROL = "curriculum-source-control"
VISUAL_ASSETS = "visual-asset-library"
MATERIALS = "instructional-materials"
PRODUCTION = "production-control"


@dataclass(frozen=True)
class CurriculumReadRequest:
    action: str
    artifact_type: str = "none"
    relative_time: str = "none"
    requires_reusable_assets: bool = False


@dataclass(frozen=True)
class CurriculumReadStep:
    logical_source: str
    action: str
    relation_first: bool = False
    purpose: str = ""


@dataclass(frozen=True)
class CurriculumReadPlan:
    mode: str
    steps: tuple[CurriculumReadStep, ...]


class CurriculumReadError(ValueError):
    """Fail-closed bounded orchestration error."""


ReadExecutor = Callable[[CurriculumReadStep, Mapping[str, object]], object]
IdentityResolver = Callable[[str], Mapping[str, object]]


def build_curriculum_read_plan(request: CurriculumReadRequest) -> CurriculumReadPlan:
    """Return the smallest deterministic read plan for already-resolved intent."""
    mode = _request_mode(request)
    steps: list[CurriculumReadStep] = [
        CurriculumReadStep(CANONICAL_UNIT, "get_page", purpose="canonical unit/currentness")
    ]
    if mode == "images":
        steps.append(
            CurriculumReadStep(
                VISUAL_ASSETS,
                "query_data_source",
                relation_first=True,
                purpose="canonical-unit-related reusable assets",
            )
        )
    elif mode == "modeling":
        steps.append(CurriculumReadStep(MODELING, "query_data_source", purpose="modeling owner evidence"))
    elif mode == "blockers":
        steps.extend(
            CurriculumReadStep(source, "query_data_source", purpose="material blocker evidence")
            for source in (UNIT_ALIGNMENT, MODELING, PACKET, SOURCE_CONTROL, MATERIALS, PRODUCTION)
        )
    elif mode == "slides":
        steps.extend(
            CurriculumReadStep(source, "query_data_source", purpose="slides planning evidence")
            for source in (UNIT_ALIGNMENT, MODELING, PACKET, MATERIALS, SOURCE_CONTROL, PRODUCTION)
        )
        steps.append(
            CurriculumReadStep(
                VISUAL_ASSETS,
                "query_data_source",
                relation_first=True,
                purpose="canonical-unit-related reusable assets",
            )
        )
    elif mode == "worksheet":
        steps.extend(
            CurriculumReadStep(source, "query_data_source", purpose="worksheet planning evidence")
            for source in (UNIT_ALIGNMENT, PACKET, MATERIALS, SOURCE_CONTROL, PRODUCTION)
        )
        if request.requires_reusable_assets:
            steps.append(
                CurriculumReadStep(
                    VISUAL_ASSETS,
                    "query_data_source",
                    relation_first=True,
                    purpose="canonical-unit-related reusable assets",
                )
            )
    elif mode == "lesson":
        steps.extend(
            CurriculumReadStep(source, "query_data_source", purpose="lesson planning evidence")
            for source in (UNIT_ALIGNMENT, MODELING, PACKET, MATERIALS)
        )
    return CurriculumReadPlan(mode=mode, steps=tuple(steps))


def orchestrate_curriculum_evidence(
    *,
    request: CurriculumReadRequest,
    canonical_unit: Mapping[str, object],
    resolve_identity: IdentityResolver,
    execute_read: ReadExecutor,
    current_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Execute one bounded injected read plan and feed normalized evidence to #975/#973.

    The injected reader is expected to reuse the canonical #936 read path. This
    function does not inspect credentials, access the network, retry, persist,
    search the workspace, or perform writes.
    """
    plan = build_curriculum_read_plan(request)
    unit = dict(canonical_unit)
    unit_id = _required_text(unit.get("stable_id"), "canonical_unit.stable_id")
    provider_page_id = _required_text(unit.get("provider_page_id"), "canonical_unit.provider_page_id")
    owner_evidence: list[dict[str, object]] = []
    asset_evidence: list[dict[str, object]] = []

    for step in plan.steps:
        identity = _verified_identity(resolve_identity(step.logical_source), step.logical_source)
        payload: dict[str, object] = {
            "logical_source": step.logical_source,
            "identity": identity,
            "canonical_unit_id": unit_id,
            "canonical_unit_provider_id": provider_page_id,
            "max_results": MAX_RESULTS,
        }
        if step.relation_first:
            payload["relation_filter"] = {
                "property": "Canonical Unit",
                "contains_page_id": _compact_notion_id(provider_page_id),
            }
        raw = execute_read(step, payload)
        result = _normalize_result(raw, step.logical_source)
        if step.logical_source == CANONICAL_UNIT:
            _verify_live_unit(result, provider_page_id)
            continue
        if step.logical_source == VISUAL_ASSETS:
            asset_evidence.extend(_normalize_assets(result))
        else:
            owner_evidence.extend(_normalize_owners(result))

    packet = assemble_current_curriculum_evidence(
        request={
            "action": request.action,
            "artifact_type": request.artifact_type,
            "relative_time": request.relative_time,
            "requires_reusable_assets": request.requires_reusable_assets,
        },
        canonical_unit={key: value for key, value in unit.items() if key != "provider_page_id"},
        owner_evidence=owner_evidence,
        asset_evidence=asset_evidence,
        current_context=current_context,
    )
    state = resolve_current_curriculum_state(packet)
    if state.record is None:
        raise CurriculumReadError("assembled evidence is incompatible with #973")
    return packet


def _request_mode(request: CurriculumReadRequest) -> str:
    action = _required_text(request.action, "action").lower()
    artifact = _required_text(request.artifact_type, "artifact_type").lower()
    if type(request.requires_reusable_assets) is not bool:
        raise CurriculumReadError("requires_reusable_assets must be boolean")
    if artifact in {"image", "images", "visual-assets"} or action == "images":
        return "images"
    if action in {"modeling", "improve-modeling"}:
        return "modeling"
    if action in {"blockers", "what-is-blocking"}:
        return "blockers"
    if artifact in {"slides", "slide-deck"}:
        return "slides"
    if artifact in {"worksheet", "worksheets"}:
        return "worksheet"
    if artifact in {"lesson", "lesson-plan"} or action in {"teach-next", "next-teaching"}:
        return "lesson"
    return "bounded"


def _verified_identity(value: Mapping[str, object], logical_source: str) -> dict[str, object]:
    identity = dict(value)
    if identity.get("logical_source") != logical_source:
        raise CurriculumReadError(f"identity drift for {logical_source}")
    if not identity.get("data_source_id") and logical_source != CANONICAL_UNIT:
        raise CurriculumReadError(f"missing data-source identity for {logical_source}")
    if identity.get("human_review_required") is True:
        raise CurriculumReadError(f"identity requires review for {logical_source}")
    return identity


def _normalize_result(value: object, logical_source: str) -> list[dict[str, object]]:
    if isinstance(value, Mapping):
        status = value.get("status")
        if status in {"missing", "not-found", "permission-denied", "stale", "unresolved"}:
            return [{
                "logical_source": logical_source,
                "failure_state": status,
                "material": True,
            }]
        results = value.get("results")
        if results is None:
            return [dict(value)]
        value = results
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CurriculumReadError(f"malformed read result for {logical_source}")
    if len(value) > MAX_RESULTS:
        raise CurriculumReadError(f"read result exceeds bound for {logical_source}")
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CurriculumReadError(f"malformed record for {logical_source}")
        normalized.append(dict(item))
    return normalized


def _verify_live_unit(results: list[dict[str, object]], provider_page_id: str) -> None:
    if len(results) != 1:
        raise CurriculumReadError("canonical unit live verification must return exactly one record")
    record = results[0]
    if record.get("failure_state"):
        raise CurriculumReadError("canonical unit live verification failed")
    if record.get("id") != provider_page_id:
        raise CurriculumReadError("canonical unit identity mismatch")


def _normalize_assets(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    for raw in records:
        record = dict(raw)
        if record.get("failure_state"):
            continue
        asset_id = record.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            continue
        assets.append({
            "asset_id": asset_id,
            "exists": bool(record.get("exists", True)),
            "approved_for_requested_use": bool(record.get("approved_for_requested_use", False)),
            "approved_student_reuse": bool(record.get("approved_student_reuse", False)),
            "source_revision": record.get("source_revision", 1),
            "canonical_unit_relation": record.get("canonical_unit_relation") is True,
        })
    return assets[:MAX_RESULTS]


def _normalize_owners(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    owners: list[dict[str, object]] = []
    for raw in records:
        record = dict(raw)
        if record.get("failure_state"):
            continue
        evidence_id = record.get("evidence_id")
        decision_key = record.get("decision_key")
        if not isinstance(evidence_id, str) or not evidence_id:
            continue
        if not isinstance(decision_key, str) or not decision_key:
            continue
        owners.append(record)
    return owners[:MAX_RESULTS]


def _compact_notion_id(value: str) -> str:
    compact = value.replace("-", "")
    if len(compact) != 32 or any(char not in "0123456789abcdefABCDEF" for char in compact):
        raise CurriculumReadError("canonical unit provider id must be a Notion page UUID")
    return compact.lower()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurriculumReadError(f"missing required {field}")
    return value.strip()
