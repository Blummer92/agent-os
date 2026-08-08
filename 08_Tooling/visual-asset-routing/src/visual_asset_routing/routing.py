"""Deterministic provider-neutral routing for incoming visual assets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

MAX_TEXT = 256
MAX_REFERENCE = 512
_SUPPORTED_DUPLICATE_DISPOSITIONS = frozenset(
    {"EXACT_EXISTING", "NORMALIZED_EXISTING", "POSSIBLE_NEAR_DUPLICATE", "NO_DUPLICATE_FOUND", "MANUAL_REVIEW_REQUIRED", "INVALID"}
)


class RoutingState(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    AMBIGUOUS = "AMBIGUOUS"
    DESTINATION_STALE = "DESTINATION_STALE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SKIPPED = "SKIPPED"
    CONFIRMED = "CONFIRMED"


class TeacherAction(str, Enum):
    ADD = "ADD"
    CHANGE = "CHANGE"
    SKIP = "SKIP"
    USE_EXISTING = "USE_EXISTING"
    KEEP_NEW = "KEEP_NEW"
    REVIEW = "REVIEW"


@dataclass(frozen=True, slots=True)
class SemanticObservation:
    concept: str
    canonical_unit: str | None
    instructional_role: str | None
    provenance: str = "advisory"
    ambiguous: bool = False
    privacy_or_provenance_concern: bool = False


@dataclass(frozen=True, slots=True)
class DestinationContext:
    drive_destination_ref: str | None
    notion_destination_ref: str | None
    current: bool


@dataclass(frozen=True, slots=True)
class AssetRoutingPlan:
    intake_reference: str
    duplicate_disposition: str
    existing_identity: str | None
    concept: str
    canonical_unit: str | None
    instructional_role: str | None
    drive_destination_ref: str | None
    notion_destination_ref: str | None
    semantic_provenance: str
    prior_advisory_concept: str | None
    state: RoutingState
    allowed_actions: tuple[TeacherAction, ...]
    reason_codes: tuple[str, ...]
    teacher_confirmed: bool = False
    execution_authorized: bool = False
    external_write_authorized: bool = False
    approval_authorized: bool = False
    classroom_readiness_authorized: bool = False
    production_authorized: bool = False


def recommend_route(*, intake_reference: str, duplicate_disposition: str, existing_identity: str | None, observation: SemanticObservation, destination: DestinationContext) -> AssetRoutingPlan:
    """Project supplied semantic/context evidence into a bounded routing plan."""
    if not _valid_text(duplicate_disposition, MAX_TEXT):
        return _review_plan(intake_reference, duplicate_disposition, existing_identity, "routing-invalid-duplicate-disposition")
    if duplicate_disposition not in _SUPPORTED_DUPLICATE_DISPOSITIONS:
        return _review_plan(intake_reference, duplicate_disposition, existing_identity, "routing-duplicate-state-unsupported")
    if not _valid_text(intake_reference, MAX_REFERENCE) or not _valid_observation(observation):
        return _review_plan(intake_reference, duplicate_disposition, existing_identity, "routing-invalid-evidence")
    if existing_identity is not None and not _valid_text(existing_identity, MAX_REFERENCE):
        return _review_plan(intake_reference, duplicate_disposition, None, "routing-invalid-identity")
    if not _valid_destination(destination):
        return _review_plan(intake_reference, duplicate_disposition, existing_identity, "routing-invalid-destination")

    if duplicate_disposition in {"EXACT_EXISTING", "NORMALIZED_EXISTING"}:
        if existing_identity is None:
            return _review_plan(intake_reference, duplicate_disposition, None, "routing-existing-identity-missing")
        return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.REVIEW_REQUIRED, (TeacherAction.USE_EXISTING, TeacherAction.REVIEW), ("routing-existing-asset",))
    if duplicate_disposition in {"MANUAL_REVIEW_REQUIRED", "INVALID"}:
        return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.REVIEW_REQUIRED, (TeacherAction.REVIEW, TeacherAction.SKIP), ("routing-duplicate-review-required",))
    if observation.privacy_or_provenance_concern:
        return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.REVIEW_REQUIRED, (TeacherAction.REVIEW, TeacherAction.SKIP), ("routing-source-review-required",))
    if observation.ambiguous or observation.canonical_unit is None or observation.instructional_role is None:
        return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.AMBIGUOUS, (TeacherAction.CHANGE, TeacherAction.SKIP), ("routing-semantic-ambiguous",))
    if not destination.current or destination.drive_destination_ref is None or destination.notion_destination_ref is None:
        return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.DESTINATION_STALE, (TeacherAction.CHANGE, TeacherAction.SKIP), ("routing-destination-unavailable",))
    if duplicate_disposition == "POSSIBLE_NEAR_DUPLICATE":
        actions = (TeacherAction.KEEP_NEW, TeacherAction.REVIEW)
        if existing_identity is not None:
            actions = (TeacherAction.USE_EXISTING, TeacherAction.KEEP_NEW, TeacherAction.REVIEW)
        return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.RECOMMENDED, actions, ("routing-near-duplicate-review",))
    return _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, RoutingState.RECOMMENDED, (TeacherAction.ADD, TeacherAction.CHANGE, TeacherAction.SKIP), ("routing-recommendation-ready",))


def apply_teacher_action(plan: AssetRoutingPlan, action: TeacherAction, *, correction: SemanticObservation | None = None) -> AssetRoutingPlan:
    """Apply one teacher routing decision without performing external execution."""
    if plan.state in {RoutingState.SKIPPED, RoutingState.CONFIRMED}:
        return plan
    if action not in plan.allowed_actions:
        return replace(plan, state=RoutingState.REVIEW_REQUIRED, allowed_actions=(TeacherAction.REVIEW,), reason_codes=("routing-action-not-allowed",))
    if action is TeacherAction.SKIP:
        return replace(plan, state=RoutingState.SKIPPED, allowed_actions=(), reason_codes=("routing-skipped",))
    if action is TeacherAction.ADD:
        return replace(plan, state=RoutingState.CONFIRMED, allowed_actions=(), teacher_confirmed=True, reason_codes=("routing-plan-confirmed",))
    if action is TeacherAction.USE_EXISTING:
        if plan.existing_identity is None:
            return replace(plan, state=RoutingState.REVIEW_REQUIRED, allowed_actions=(TeacherAction.REVIEW,), reason_codes=("routing-existing-identity-missing",))
        return replace(plan, state=RoutingState.CONFIRMED, allowed_actions=(), teacher_confirmed=True, reason_codes=("routing-use-existing-selected",))
    if action is TeacherAction.KEEP_NEW:
        return replace(plan, state=RoutingState.CONFIRMED, allowed_actions=(), teacher_confirmed=True, reason_codes=("routing-keep-new-selected",))
    if action is TeacherAction.CHANGE:
        if correction is None or not _valid_observation(correction) or correction.ambiguous:
            return replace(plan, state=RoutingState.REVIEW_REQUIRED, allowed_actions=(TeacherAction.REVIEW, TeacherAction.SKIP), reason_codes=("routing-correction-invalid",))
        destination = DestinationContext(plan.drive_destination_ref, plan.notion_destination_ref, plan.state is not RoutingState.DESTINATION_STALE)
        rerouted = recommend_route(intake_reference=plan.intake_reference, duplicate_disposition=plan.duplicate_disposition, existing_identity=plan.existing_identity, observation=correction, destination=destination)
        return replace(rerouted, semantic_provenance="teacher-confirmed", prior_advisory_concept=plan.concept, teacher_confirmed=True, reason_codes=("routing-teacher-correction",) + rerouted.reason_codes)
    return replace(plan, state=RoutingState.REVIEW_REQUIRED, allowed_actions=(TeacherAction.REVIEW,), reason_codes=("routing-review-selected",))


def _plan(intake_reference, duplicate_disposition, existing_identity, observation, destination, state, actions, reasons):
    return AssetRoutingPlan(intake_reference, duplicate_disposition, existing_identity, observation.concept, observation.canonical_unit, observation.instructional_role, destination.drive_destination_ref, destination.notion_destination_ref, observation.provenance, None, state, actions, reasons)


def _review_plan(intake_reference, duplicate_disposition, existing_identity, reason):
    safe_reference = intake_reference if _valid_text(intake_reference, MAX_REFERENCE) else "invalid-intake"
    safe_disposition = duplicate_disposition if _valid_text(duplicate_disposition, MAX_TEXT) else "INVALID"
    return _plan(safe_reference, safe_disposition, existing_identity, SemanticObservation("review-required", None, None), DestinationContext(None, None, False), RoutingState.REVIEW_REQUIRED, (TeacherAction.REVIEW, TeacherAction.SKIP), (reason,))


def _valid_observation(value: SemanticObservation) -> bool:
    return type(value) is SemanticObservation and _valid_text(value.concept, MAX_TEXT) and (value.canonical_unit is None or _valid_text(value.canonical_unit, MAX_TEXT)) and (value.instructional_role is None or _valid_text(value.instructional_role, MAX_TEXT)) and _valid_text(value.provenance, MAX_TEXT) and type(value.ambiguous) is bool and type(value.privacy_or_provenance_concern) is bool


def _valid_destination(value: DestinationContext) -> bool:
    return type(value) is DestinationContext and (value.drive_destination_ref is None or _valid_text(value.drive_destination_ref, MAX_REFERENCE)) and (value.notion_destination_ref is None or _valid_text(value.notion_destination_ref, MAX_REFERENCE)) and type(value.current) is bool


def _valid_text(value: object, maximum: int) -> bool:
    return type(value) is str and bool(value.strip()) and len(value) <= maximum
