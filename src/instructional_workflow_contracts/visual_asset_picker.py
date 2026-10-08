"""Pure governed selection contract for reusable classroom visual assets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Sequence

SourcePreference = Literal["reuse-only", "reuse-first", "find", "explicit-existing", "review-compare"]
SelectionAuthority = Literal["recommend", "teacher-select"]
ReviewStatus = Literal["approved", "needs-review"]

# Governed input bound, reconciled with the candidate filter's maximum (#3255).
# The filter (consumer) accepts at least this many candidates.
MAX_CANDIDATES = 64


class AssetPickerError(ValueError):
    """Fail-closed Asset Picker contract error."""


@dataclass(frozen=True, slots=True)
class AssetPickerIntent:
    """Already-interpreted semantic intent; no phrase parsing occurs here."""

    source_preference: SourcePreference | None = None
    generation_allowed: bool | None = None
    selection_authority: SelectionAuthority = "recommend"
    # #3251: binds to the visual-needs plan's stable role_ids (never bare
    # role_type strings); a role_id is the only identity the plan guarantees
    # across revisions.
    visual_roles: tuple[str, ...] = ()
    target_context: str | None = None
    requested_asset_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source_preference not in {None, "reuse-only", "reuse-first", "find", "explicit-existing", "review-compare"}:
            raise AssetPickerError("unsupported source preference")
        if self.generation_allowed is not None and type(self.generation_allowed) is not bool:
            raise AssetPickerError("generation_allowed must be boolean or None")
        if self.selection_authority not in {"recommend", "teacher-select"}:
            raise AssetPickerError("unsupported selection authority")
        _validate_ids(self.visual_roles, "visual role")
        _validate_ids(self.requested_asset_ids, "requested asset")
        if self.target_context is not None and (not isinstance(self.target_context, str) or not self.target_context.strip()):
            raise AssetPickerError("target_context must be non-empty text")


@dataclass(frozen=True, slots=True)
class AssetCandidate:
    asset_id: str
    source_reference: str
    eligible: bool
    review_status: ReviewStatus
    unit_match: bool = False
    concept_match: bool = False
    role_match: bool = False
    explicit_context_match: bool = False
    same_unit_use: bool = False
    coursewide_reusable: bool = False
    recency_rank: int = 0
    # #3251: the governed visual role (and slot) this candidate is offered
    # for. Carried into the selection reference so a selection can never be
    # silently re-attributed to a different role/slot downstream.
    role_id: str | None = None
    slot_id: str | None = None

    def __post_init__(self) -> None:
        _validate_ids((self.asset_id,), "asset")
        if not isinstance(self.source_reference, str) or not self.source_reference.strip():
            raise AssetPickerError("source_reference must be non-empty text")
        for name in ("eligible", "unit_match", "concept_match", "role_match", "explicit_context_match", "same_unit_use", "coursewide_reusable"):
            if type(getattr(self, name)) is not bool:
                raise AssetPickerError(f"{name} must be boolean")
        if self.review_status not in {"approved", "needs-review"}:
            raise AssetPickerError("unsupported review_status")
        if type(self.recency_rank) is not int:
            raise AssetPickerError("recency_rank must be an integer")
        _validate_optional_binding(self.role_id, self.slot_id)


@dataclass(frozen=True, slots=True)
class SelectedAssetReference:
    asset_id: str
    source_reference: str
    review_status: ReviewStatus
    # #3251: the governed (role_id, slot_id) binding this selection
    # satisfies. Identity conflicts fail closed: presenting this reference
    # for a different role/slot is rejected, never re-attributed.
    role_id: str | None = None
    slot_id: str | None = None

    def __post_init__(self) -> None:
        _validate_ids((self.asset_id,), "asset")
        if not isinstance(self.source_reference, str) or not self.source_reference.strip():
            raise AssetPickerError("source_reference must be non-empty text")
        if self.review_status not in {"approved", "needs-review"}:
            raise AssetPickerError("unsupported review_status")
        _validate_optional_binding(self.role_id, self.slot_id)


def _validate_optional_binding(role_id: object, slot_id: object) -> None:
    if role_id is not None and (
        not isinstance(role_id, str) or not role_id.strip() or len(role_id) > 256
    ):
        raise AssetPickerError("role_id must be non-empty text when supplied")
    if slot_id is not None and (
        not isinstance(slot_id, str) or not slot_id.strip() or len(slot_id) > 64
    ):
        raise AssetPickerError("slot_id must be non-empty text when supplied")


def check_reference_role_binding(
    reference: SelectedAssetReference,
    *,
    role_id: str,
    slot_id: str | None = None,
) -> None:
    """Fail closed when a selected reference is presented for the wrong binding.

    A reference bound to role R1 (slot S1) must never be silently
    re-attributed to R2's slot (#3251 identity-conflict rule). An unbound
    reference (no role_id) is rejected rather than guessed. A missing
    slot_id normalizes to the implicit single slot ``"0"``.
    """
    if not isinstance(reference, SelectedAssetReference):
        raise AssetPickerError("reference must be a SelectedAssetReference")
    if not isinstance(role_id, str) or not role_id.strip():
        raise AssetPickerError("role_id must be non-empty text")
    expected_slot = "0" if slot_id is None else slot_id
    actual_slot = "0" if reference.slot_id is None else reference.slot_id
    if reference.role_id != role_id or actual_slot != expected_slot:
        raise AssetPickerError(
            "selected asset reference is not bound to the requested role/slot"
        )


@dataclass(frozen=True, slots=True)
class AssetPickerDecision:
    outcome: Literal[
        "recommended",
        "candidate-choice-required",
        "review-required",
        "blocked",
        "library-unavailable",
        "selection-invalidated",
    ]
    source_preference: SourcePreference
    generation_allowed: bool
    recommended_asset_ids: tuple[str, ...]
    needs_review_asset_ids: tuple[str, ...]
    selected_references: tuple[SelectedAssetReference, ...]
    create_new_handoff_allowed: bool


def merge_asset_picker_intent(*instructions: AssetPickerIntent) -> AssetPickerIntent:
    """Merge semantic instructions in order; later explicit values override earlier ones."""
    merged = AssetPickerIntent()
    for instruction in instructions:
        if not isinstance(instruction, AssetPickerIntent):
            raise AssetPickerError("instructions must be AssetPickerIntent values")
        updates: dict[str, object] = {}
        if instruction.source_preference is not None:
            updates["source_preference"] = instruction.source_preference
        if instruction.generation_allowed is not None:
            updates["generation_allowed"] = instruction.generation_allowed
        if instruction.selection_authority != "recommend" or merged.selection_authority == "recommend":
            updates["selection_authority"] = instruction.selection_authority
        if instruction.visual_roles:
            updates["visual_roles"] = instruction.visual_roles
        if instruction.target_context is not None:
            updates["target_context"] = instruction.target_context
        if instruction.requested_asset_ids:
            updates["requested_asset_ids"] = instruction.requested_asset_ids
        merged = replace(merged, **updates)
    return merged


def resolve_visual_asset_picker(
    intent: AssetPickerIntent,
    candidates: Sequence[AssetCandidate],
    *,
    library_available: bool = True,
    selected_asset_ids: Sequence[str] = (),
) -> AssetPickerDecision:
    """Resolve reusable-asset selection without generating, writing, or reinterpreting teacher language."""
    if not isinstance(intent, AssetPickerIntent):
        raise AssetPickerError("intent must be AssetPickerIntent")
    if type(library_available) is not bool:
        raise AssetPickerError("library_available must be boolean")
    if len(candidates) > MAX_CANDIDATES:
        raise AssetPickerError("candidate collection exceeds bound")
    if any(not isinstance(candidate, AssetCandidate) for candidate in candidates):
        raise AssetPickerError("candidates must contain AssetCandidate values")
    selected_ids = tuple(selected_asset_ids)
    _validate_ids(selected_ids, "selected asset")

    source_preference: SourcePreference = intent.source_preference or "reuse-first"
    generation_allowed = False if intent.generation_allowed is None else intent.generation_allowed
    if source_preference == "reuse-only":
        generation_allowed = False

    if not library_available:
        return AssetPickerDecision(
            outcome="library-unavailable",
            source_preference=source_preference,
            generation_allowed=generation_allowed,
            recommended_asset_ids=(),
            needs_review_asset_ids=(),
            selected_references=(),
            create_new_handoff_allowed=False,
        )

    by_id = {candidate.asset_id: candidate for candidate in candidates}
    if len(by_id) != len(candidates):
        raise AssetPickerError("duplicate asset identity")

    if selected_ids:
        if any(asset_id not in by_id for asset_id in selected_ids):
            return _invalidated(source_preference, generation_allowed)
        selected = tuple(by_id[asset_id] for asset_id in selected_ids)
        if any((not candidate.eligible) or candidate.review_status != "approved" for candidate in selected):
            return _invalidated(source_preference, generation_allowed)
        # #3251: one asset may be selected for several roles/slots, but the
        # same (role_id, slot_id) binding may not be claimed twice -- that is
        # an identity conflict and fails closed.
        seen_bindings: set[tuple[str | None, str | None]] = set()
        for candidate in selected:
            if candidate.role_id is not None:
                binding = (candidate.role_id, candidate.slot_id)
                if binding in seen_bindings:
                    raise AssetPickerError("duplicate selection for the same role/slot binding")
                seen_bindings.add(binding)
        return AssetPickerDecision(
            outcome="recommended",
            source_preference=source_preference,
            generation_allowed=generation_allowed,
            recommended_asset_ids=selected_ids,
            needs_review_asset_ids=(),
            selected_references=tuple(_reference(candidate) for candidate in selected),
            create_new_handoff_allowed=False,
        )

    pool = list(candidates)
    if intent.requested_asset_ids:
        requested = set(intent.requested_asset_ids)
        pool = [candidate for candidate in pool if candidate.asset_id in requested]

    approved = [candidate for candidate in pool if candidate.eligible and candidate.review_status == "approved"]
    needs_review = tuple(
        candidate.asset_id
        for candidate in _rank([candidate for candidate in pool if candidate.eligible and candidate.review_status == "needs-review"])
    )
    ranked = _rank(approved)

    if not ranked:
        # The pure picker has no read-evidence input, so it can never prove
        # absence: no empty/unresolvable pool becomes a visual gap, and none
        # of these non-absence states authorizes a creation handoff.
        if not candidates:
            return AssetPickerDecision(
                outcome="blocked",
                source_preference=source_preference,
                generation_allowed=generation_allowed,
                recommended_asset_ids=(),
                needs_review_asset_ids=(),
                selected_references=(),
                create_new_handoff_allowed=False,
            )
        if intent.requested_asset_ids and not (
            set(intent.requested_asset_ids) & set(by_id)
        ):
            # Requested-ID miss: the teacher-named asset is not in the pool.
            return _invalidated(source_preference, generation_allowed)
        if needs_review:
            return AssetPickerDecision(
                outcome="review-required",
                source_preference=source_preference,
                generation_allowed=generation_allowed,
                recommended_asset_ids=(),
                needs_review_asset_ids=needs_review,
                selected_references=(),
                create_new_handoff_allowed=False,
            )
        return _invalidated(source_preference, generation_allowed)

    recommended_ids = tuple(candidate.asset_id for candidate in ranked)
    needs_choice = intent.selection_authority == "teacher-select" or source_preference in {"review-compare", "explicit-existing"} and len(ranked) > 1
    if needs_choice:
        return AssetPickerDecision(
            outcome="candidate-choice-required",
            source_preference=source_preference,
            generation_allowed=generation_allowed,
            recommended_asset_ids=recommended_ids,
            needs_review_asset_ids=needs_review,
            selected_references=(),
            create_new_handoff_allowed=generation_allowed,
        )

    winner = ranked[0]
    return AssetPickerDecision(
        outcome="recommended",
        source_preference=source_preference,
        generation_allowed=generation_allowed,
        recommended_asset_ids=recommended_ids,
        needs_review_asset_ids=needs_review,
        selected_references=(_reference(winner),),
        create_new_handoff_allowed=False,
    )


def _rank(candidates: Sequence[AssetCandidate]) -> list[AssetCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            not candidate.eligible,
            not candidate.unit_match,
            not candidate.concept_match,
            not candidate.role_match,
            not candidate.explicit_context_match,
            not candidate.same_unit_use,
            not candidate.coursewide_reusable,
            -candidate.recency_rank,
            candidate.asset_id,
        ),
    )


def _reference(candidate: AssetCandidate) -> SelectedAssetReference:
    return SelectedAssetReference(
        candidate.asset_id,
        candidate.source_reference,
        candidate.review_status,
        role_id=candidate.role_id,
        slot_id=candidate.slot_id,
    )


def _invalidated(source_preference: SourcePreference, generation_allowed: bool) -> AssetPickerDecision:
    return AssetPickerDecision(
        outcome="selection-invalidated",
        source_preference=source_preference,
        generation_allowed=generation_allowed,
        recommended_asset_ids=(),
        needs_review_asset_ids=(),
        selected_references=(),
        create_new_handoff_allowed=False,
    )


def _validate_ids(values: Sequence[str], label: str) -> None:
    if len(values) > 32:
        raise AssetPickerError(f"{label} collection exceeds bound")
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value) > 128:
            raise AssetPickerError(f"{label} identity is malformed")
