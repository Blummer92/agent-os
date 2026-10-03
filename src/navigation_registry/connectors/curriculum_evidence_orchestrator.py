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
    # #3253: governed reuse-scope class for this step's asset read. None means
    # the step carries no scope semantic (owner evidence, unit read). The
    # coursewide step reuses the same VISUAL_ASSETS logical source, #936
    # executor, and finite binding architecture — it is not a second reader.
    reuse_scope: str | None = None


# #3253: the Icon System scope signal. This is the existing "Reusable Across
# Units?" checkbox — no Notion schema change, no writes. #3254 owns the
# Notion field projection; this module only names the governed property the
# coursewide read filter selects on.
REUSABLE_ACROSS_UNITS_PROPERTY = "Reusable Across Units?"
COURSEWIDE_SCOPE = "coursewide"


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
        steps.append(_unit_scoped_asset_step())
        steps.append(_coursewide_asset_step())
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
        steps.append(_unit_scoped_asset_step())
        steps.append(_coursewide_asset_step())
    elif mode == "worksheet":
        steps.extend(
            CurriculumReadStep(source, "query_data_source", purpose="worksheet planning evidence")
            for source in (UNIT_ALIGNMENT, PACKET, MATERIALS, SOURCE_CONTROL, PRODUCTION)
        )
        if request.requires_reusable_assets:
            steps.append(_unit_scoped_asset_step())
            steps.append(_coursewide_asset_step())
    elif mode == "lesson":
        steps.extend(
            CurriculumReadStep(source, "query_data_source", purpose="lesson planning evidence")
            for source in (UNIT_ALIGNMENT, MODELING, PACKET, MATERIALS)
        )
    return CurriculumReadPlan(mode=mode, steps=tuple(steps))


def _unit_scoped_asset_step() -> CurriculumReadStep:
    """Relation-first unit-scoped read (#2816's requirement, unchanged)."""
    return CurriculumReadStep(
        VISUAL_ASSETS,
        "query_data_source",
        relation_first=True,
        purpose="canonical-unit-related reusable assets",
        reuse_scope="unit-specific",
    )


def _coursewide_asset_step() -> CurriculumReadStep:
    """Governed coursewide read: same source/executor/bounds, no unit relation.

    Selects on the Icon System "Reusable Across Units?" checkbox rather than
    the Canonical Unit relation. No Canonical Unit relation is fabricated;
    no second reader, catalog, or broad search is introduced.
    """
    return CurriculumReadStep(
        VISUAL_ASSETS,
        "query_data_source",
        purpose="coursewide reusable assets",
        reuse_scope=COURSEWIDE_SCOPE,
    )


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
        elif step.reuse_scope == COURSEWIDE_SCOPE:
            # #3253: governed coursewide selection on the Icon System
            # "Reusable Across Units?" checkbox — never a unit relation.
            payload["property_filter"] = {
                "property": REUSABLE_ACROSS_UNITS_PROPERTY,
                "checkbox": {"equals": True},
            }
        raw = execute_read(step, payload)
        result = _normalize_result(raw, step.logical_source)
        if step.logical_source == CANONICAL_UNIT:
            _verify_live_unit(result, provider_page_id)
            continue
        if step.logical_source == VISUAL_ASSETS:
            incoming_assets = _normalize_assets(
                result, relation_first=step.relation_first, reuse_scope=step.reuse_scope
            )
            if len(asset_evidence) + len(incoming_assets) > MAX_RESULTS:
                raise CurriculumReadError("asset evidence exceeds handoff bound")
            asset_evidence.extend(incoming_assets)
        else:
            incoming_owners = _normalize_owners(result)
            if len(owner_evidence) + len(incoming_owners) > MAX_RESULTS:
                raise CurriculumReadError("owner evidence exceeds handoff bound")
            owner_evidence.extend(incoming_owners)

    packet = assemble_current_curriculum_evidence(
        request={
            "action": request.action,
            "artifact_type": request.artifact_type,
            "relative_time": request.relative_time,
            "requires_reusable_assets": request.requires_reusable_assets,
        },
        canonical_unit={key: value for key, value in unit.items() if key != "provider_page_id"},
        owner_evidence=owner_evidence,
        asset_evidence=_dedupe_assets(asset_evidence),
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
    review_required = identity.get("human_review_required")
    if type(review_required) is not bool:
        raise CurriculumReadError(f"malformed review flag for {logical_source}")
    if review_required:
        raise CurriculumReadError(f"identity requires review for {logical_source}")
    if logical_source != CANONICAL_UNIT:
        data_source_id = identity.get("data_source_id")
        if not isinstance(data_source_id, str) or not data_source_id.strip():
            raise CurriculumReadError(f"missing data-source identity for {logical_source}")
    return identity


def _normalize_result(value: object, logical_source: str) -> list[dict[str, object]]:
    if isinstance(value, Mapping):
        status = value.get("status")
        if status in {"missing", "not-found", "permission-denied", "stale", "unresolved"}:
            raise CurriculumReadError(f"provider {status} for {logical_source}")
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
    if record.get("id") != provider_page_id:
        raise CurriculumReadError("canonical unit identity mismatch")


def _dedupe_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep the first record per asset_id; the relation-first step runs first,
    so unit-scoped evidence wins over a coursewide duplicate (#2816 precedence)."""
    seen: set[object] = set()
    deduped: list[dict[str, object]] = []
    for asset in assets:
        asset_id = asset.get("asset_id")
        if asset_id in seen:
            continue
        seen.add(asset_id)
        deduped.append(asset)
    return deduped


def _normalize_assets(
    records: Iterable[Mapping[str, object]],
    *,
    relation_first: bool,
    reuse_scope: str | None,
) -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    for raw in records:
        record = dict(raw)
        if _is_raw_notion_page(record):
            record = _normalize_raw_notion_asset(
                record, relation_first=relation_first, reuse_scope=reuse_scope
            )

        asset_id = _required_record_text(record.get("asset_id"), "asset_id")
        exists = record.get("exists", True)
        approved_for_requested_use = record.get("approved_for_requested_use", False)
        approved_student_reuse = record.get("approved_student_reuse", False)
        for field, value in (
            ("exists", exists),
            ("approved_for_requested_use", approved_for_requested_use),
            ("approved_student_reuse", approved_student_reuse),
        ):
            if type(value) is not bool:
                raise CurriculumReadError(f"malformed asset boolean {field}")
        # Scope is contract data, never inferred from prose: the read step's
        # own provenance decides when the record does not declare it. A
        # relation-first hit proves unit-specific membership; the coursewide
        # step proves coursewide eligibility. Nothing is fabricated.
        scope = record.get("reuse_scope")
        if scope is None:
            scope = "unit-specific" if relation_first else (reuse_scope or "unknown")
        if scope not in {"unit-specific", "coursewide", "cross-unit", "global", "unrelated", "unknown"}:
            raise CurriculumReadError(f"unsupported asset reuse_scope {scope!r}")
        status = record.get("reuse_status", "unknown")
        if status not in {"reusable", "single-use", "unknown"}:
            raise CurriculumReadError(f"unsupported asset reuse_status {status!r}")
        asset = {
            "asset_id": asset_id,
            "exists": exists,
            "approved_for_requested_use": approved_for_requested_use,
            "approved_student_reuse": approved_student_reuse,
            "source_revision": record.get("source_revision", 1),
            "reuse_scope": scope,
            "reuse_status": status,
            # The relation marker stays provider-specific and is never
            # fabricated: raw pages get it from the step's own provenance;
            # already-normalized records keep the producer's assertion.
            "canonical_unit_relation": bool(record.get("canonical_unit_relation")),
        }
        library_reference = record.get("library_reference")
        if isinstance(library_reference, Mapping):
            page_id = library_reference.get("page_id")
            drive_file_id = library_reference.get("drive_file_id")
        else:
            page_id = record.get("page_id") or record.get("id")
            drive_file_id = record.get("drive_file_id")
        if isinstance(page_id, str) and page_id.strip() and isinstance(drive_file_id, str) and drive_file_id.strip():
            asset["library_reference"] = {
                "page_id": page_id.strip(),
                "drive_file_id": drive_file_id.strip(),
            }
        assets.append(asset)
    return assets


def _normalize_owners(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    owners: list[dict[str, object]] = []
    for raw in records:
        record = dict(raw)
        if _is_raw_notion_page(record):
            record = _normalize_raw_notion_owner(record)

        _required_record_text(record.get("evidence_id"), "evidence_id")
        _required_record_text(record.get("decision_key"), "decision_key")
        owners.append(record)
    return owners


def _is_raw_notion_page(record: Mapping[str, object]) -> bool:
    return isinstance(record.get("id"), str) and isinstance(record.get("properties"), Mapping)


def _normalize_raw_notion_asset(
    record: Mapping[str, object], *, relation_first: bool, reuse_scope: str | None
) -> dict[str, object]:
    """Project only provider facts already proven by the bounded read itself.

    The relation-first query is constructed upstream from the verified canonical
    unit identity, so a returned page proves existence and relation membership
    (scope "unit-specific"). The coursewide query selects on the Icon System
    "Reusable Across Units?" checkbox, so a returned page proves coursewide
    eligibility without any unit relation (scope "coursewide"); the relation
    marker stays False and is never fabricated. Property names and approval
    semantics are not inferred here: those require a separately verified
    source-schema mapping (#3254).
    """
    page_id = _required_record_text(record.get("id"), "Notion page id")
    properties = record.get("properties")
    if not isinstance(properties, Mapping):
        raise CurriculumReadError("raw Notion asset is missing properties")
    if relation_first:
        scope: object = "unit-specific"
        related = True
    else:
        scope = reuse_scope or "unknown"
        related = False
    return {
        "asset_id": page_id,
        "page_id": page_id,
        "exists": True,
        "approved_for_requested_use": False,
        "approved_student_reuse": False,
        "canonical_unit_relation": related,
        "reuse_scope": scope,
        "reuse_status": _reusable_checkbox_status(properties),
        "source_revision": 1,
    }


def _reusable_checkbox_status(properties: Mapping[str, object]) -> str:
    """Read only the governed Icon System scope signal; anything else is unknown."""
    prop = properties.get(REUSABLE_ACROSS_UNITS_PROPERTY)
    if isinstance(prop, Mapping):
        checkbox = prop.get("checkbox")
        if checkbox is True:
            return "reusable"
    return "unknown"


def _normalize_raw_notion_owner(record: Mapping[str, object]) -> dict[str, object]:
    """Fail closed until an exact source-specific owner schema is verified."""
    _required_record_text(record.get("id"), "Notion page id")
    if not isinstance(record.get("properties"), Mapping):
        raise CurriculumReadError("raw Notion owner evidence is missing properties")
    raise CurriculumReadError(
        "raw Notion owner evidence requires a verified provider-neutral schema mapping"
    )


def _required_record_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurriculumReadError(f"missing required {field}")
    return value.strip()


def _compact_notion_id(value: str) -> str:
    compact = value.replace("-", "")
    if len(compact) != 32 or any(char not in "0123456789abcdefABCDEF" for char in compact):
        raise CurriculumReadError("canonical unit provider id must be a Notion page UUID")
    return compact.lower()


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CurriculumReadError(f"missing required {field}")
    return value.strip()
