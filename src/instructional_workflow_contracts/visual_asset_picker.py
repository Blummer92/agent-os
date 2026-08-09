"""Pure governed selection contract for reusable classroom visual assets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, Sequence

SourcePreference = Literal["reuse-only", "reuse-first", "find", "explicit-existing", "review-compare"]
SelectionAuthority = Literal["recommend", "teacher-select"]
ReviewStatus = Literal["approved", "needs-review"]


class AssetPickerError(ValueError):
    """Fail-closed Asset Picker contract error."""


@dataclass(frozen=True, slots=True)
class AssetPickerIntent:
    """Already-interpreted semantic intent; no phrase parsing occurs here."""

    source_preference: SourcePreference | None = None
    generation_allowed: bool | None = None
    selection_authority: SelectionAuthority = "recommend"
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


@dataclass(frozen=True, slots=True)
class SelectedAssetReference:
    asset_id: str
    source_reference: str
    review_status: ReviewStatus


@dataclass(frozen=True, slots=True)
class AssetPickerDecision:
    outcome: Literal[
        "recommended",
        "candidate-choice-required",
        "visual-gap",
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
    if len(candidates) > 64:
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
        return AssetPickerDecision(
            outcome="visual-gap",
            source_preference=source_preference,
            generation_allowed=generation_allowed,
            recommended_asset_ids=(),
            needs_review_asset_ids=needs_review,
            selected_references=(),
            create_new_handoff_allowed=generation_allowed,
        )

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
    return SelectedAssetReference(candidate.asset_id, candidate.source_reference, candidate.review_status)


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
