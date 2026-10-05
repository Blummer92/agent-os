"""Mission-level preferred-execution-surface limitation classification (#3139).

The #3139 regression, observed immediately after PR #3129 merged the #2826
bounded Codespaces continuation acceptance coverage into ``main``:

```text
finite mission has remaining read-only canonical work
-> preferred execution surface cannot be directly observed/entered
-> capability/observability limitation is promoted to shared mission blocker
-> final response emitted
-> independent admissible work is abandoned
```

In the live reproduction the ChatGPT execution found no literal
Codespaces-list/SSH action in its GitHub connector and the Codespaces REST
endpoint rejected through the generic fetch surface, then treated that
tool-surface limitation as a shared blocker instead of continuing the
read-only backlog reconciliation still possible through canonical GitHub
issue/PR/main evidence.

The hard invariant this module enforces is #3139's Expected step 5: a
preferred surface that cannot be observed or entered is reported as an
item-local capability boundary **unless evidence proves it is shared across
the remaining population**. Unproven sharedness fails closed to item-local --
the exact inversion of the bug, which promoted unproven sharedness to a
shared terminal blocker.

This module is a pure decision function in the established seam pattern
(#1237 ``post_selection_continuation.py``). It classifies the limitation; it
does not select routes (#918), retry, schedule, persist state, or grant any
authority. It deliberately creates no scheduler, queue, mission store,
continuation engine, persistence mechanism, or generic Codespaces API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME = (
    "agent-os.execution-interface-preferred-surface-limitation"
)
PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION = "1.0"

_MAX_SURFACE_ID_LENGTH = 256
_MAX_SHAREDNESS_EVIDENCE_LENGTH = 2000


class SurfaceLimitationKind(str, Enum):
    """What exactly is missing about the preferred execution surface."""

    #: The surface cannot be listed or inspected (e.g. no list action, REST
    #: rejected through the generic fetch surface). This is the #3139 shape.
    UNOBSERVABLE = "unobservable"
    #: The surface is observable but cannot be opened/entered (e.g. no SSH
    #: action, entry rejected).
    UNENTERABLE = "unenterable"
    #: The surface is observable and enterable but lacks a required capability.
    MISSING_CAPABILITY = "missing-capability"


class SurfaceLimitationClassification(str, Enum):
    """The mission-level disposition of one preferred-surface limitation."""

    #: The limitation bounds only operations that genuinely require the
    #: surface. The mission cursor is preserved and every independent
    #: operation still admissible through canonical GitHub read evidence
    #: continues.
    ITEM_LOCAL_CAPABILITY_BOUNDARY = "item-local-capability-boundary"
    #: Evidence proves the limitation is shared across the remaining
    #: population. The mission stops.
    SHARED_MISSION_BLOCKER = "shared-mission-blocker"


class SurfaceLimitationReason(str, Enum):
    """Finite reason codes explaining one deterministic classification."""

    PREFERRED_SURFACE_UNOBSERVABLE = "preferred-surface-unobservable"
    PREFERRED_SURFACE_UNENTERABLE = "preferred-surface-unenterable"
    PREFERRED_SURFACE_MISSING_CAPABILITY = "preferred-surface-missing-capability"
    #: #3139's hard invariant: sharedness was not proven, so the limitation
    #: fails closed to item-local instead of being promoted to shared.
    SHAREDNESS_UNPROVEN_FAIL_CLOSED_ITEM_LOCAL = (
        "sharedness-unproven-fail-closed-item-local"
    )
    SHAREDNESS_PROVEN = "sharedness-proven"
    MISSION_CURSOR_PRESERVED = "mission-cursor-preserved"
    REMAINING_OPERATIONS_GITHUB_READ_ADMISSIBLE = (
        "remaining-operations-github-read-admissible"
    )
    NO_REMAINING_ADMISSIBLE_OPERATIONS = "no-remaining-admissible-operations"


@dataclass(frozen=True, slots=True, kw_only=True)
class PreferredSurfaceLimitationEvidence:
    """Evidence about one preferred-surface limitation at mission level.

    Every field is evidence the caller has already established. Unproven
    sharedness fails closed to item-local; claiming sharedness without
    evidence, or supplying sharedness evidence without the claim, is a
    caller contract error.
    """

    limitation_kind: SurfaceLimitationKind
    #: Exact identity of the preferred surface, e.g. ``codespace:<name>``.
    #: Opaque to this module; carried for the report only.
    preferred_surface_id: str
    #: Opaque mission-cursor identity. This module never interprets it; the
    #: classification always preserves it.
    mission_cursor: str
    remaining_operation_count: int
    #: Subset of ``remaining_operation_count`` whose completion genuinely
    #: requires the unavailable surface.
    operations_requiring_surface_count: int
    #: Whether canonical GitHub read evidence is available for the remaining
    #: operations that do not require the surface.
    github_read_evidence_available: bool
    #: True only when the caller has proven the limitation is shared across
    #: the remaining population. Unproven -- including merely plausible --
    #: sharedness must be False.
    sharedness_proven: bool
    #: The proof, required exactly when ``sharedness_proven`` is True.
    sharedness_evidence: str | None = None

    def __post_init__(self) -> None:
        if type(self.limitation_kind) is not SurfaceLimitationKind:
            raise TypeError("limitation_kind must be an exact SurfaceLimitationKind")
        for name, bound in (
            ("preferred_surface_id", _MAX_SURFACE_ID_LENGTH),
            ("mission_cursor", _MAX_SURFACE_ID_LENGTH),
        ):
            value = getattr(self, name)
            if (
                type(value) is not str
                or not value
                or len(value) > bound
                or any(ch.isspace() for ch in value)
            ):
                raise ValueError(f"{name} must be bounded non-whitespace text")
        for name in ("remaining_operation_count", "operations_requiring_surface_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative built-in integer")
        if self.operations_requiring_surface_count > self.remaining_operation_count:
            raise ValueError(
                "operations_requiring_surface_count cannot exceed "
                "remaining_operation_count"
            )
        for name in ("github_read_evidence_available", "sharedness_proven"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.sharedness_proven:
            evidence = self.sharedness_evidence
            if (
                type(evidence) is not str
                or not evidence.strip()
                or len(evidence) > _MAX_SHAREDNESS_EVIDENCE_LENGTH
            ):
                raise ValueError(
                    "sharedness_evidence must be non-empty bounded text when "
                    "sharedness_proven is True"
                )
        elif self.sharedness_evidence is not None:
            raise ValueError(
                "sharedness_evidence requires sharedness_proven=True; unproven "
                "sharedness carries no evidence"
            )

    @property
    def read_admissible_remaining_count(self) -> int:
        """Remaining operations not requiring the surface.

        Admissible through canonical GitHub read evidence exactly when
        ``github_read_evidence_available`` is True.
        """
        return (
            self.remaining_operation_count - self.operations_requiring_surface_count
        )


@dataclass(frozen=True, slots=True)
class PreferredSurfaceLimitationDecision:
    """One bounded, non-authorizing mission-level limitation decision."""

    schema_name: Literal["agent-os.execution-interface-preferred-surface-limitation"]
    schema_version: Literal["1.0"]
    classification: SurfaceLimitationClassification
    reason_codes: tuple[SurfaceLimitationReason, ...]
    #: True when independently actionable work remains admissible through
    #: canonical GitHub read evidence.
    mission_continues: bool
    #: Operations genuinely requiring the surface stop as item-local; they
    #: never promote the limitation to shared by themselves.
    surface_requiring_operations_terminal_item_local: bool
    blocker: str | None
    clearing_condition: str | None
    #: The mission cursor is never dropped by this classification.
    mission_cursor_preserved: Literal[True] = field(default=True, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME:
            raise ValueError("unsupported preferred-surface limitation schema name")
        if self.schema_version != PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION:
            raise ValueError("unsupported preferred-surface limitation schema version")
        if type(self.classification) is not SurfaceLimitationClassification:
            raise TypeError(
                "classification must be an exact SurfaceLimitationClassification"
            )
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(type(item) is not SurfaceLimitationReason for item in self.reason_codes):
            raise TypeError("reason_codes contain an invalid value")
        if self.reason_codes != tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        ):
            raise ValueError("reason_codes must be sorted and unique")
        for name in (
            "mission_continues",
            "surface_requiring_operations_terminal_item_local",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        # Structural form of #1237's invariant at mission level: a shared
        # classification is representable only with proven sharedness, and an
        # available alternative is never reported as a blocker.
        if (
            self.classification
            is SurfaceLimitationClassification.SHARED_MISSION_BLOCKER
        ):
            if SurfaceLimitationReason.SHAREDNESS_PROVEN not in self.reason_codes:
                raise ValueError("a shared classification requires proven sharedness")
            if not self.blocker or not self.clearing_condition:
                raise ValueError(
                    "a shared mission blocker must state one blocker and its "
                    "exact clearing condition"
                )
            if self.mission_continues:
                raise ValueError("a shared mission blocker stops the mission")
        else:
            if SurfaceLimitationReason.SHAREDNESS_PROVEN in self.reason_codes:
                raise ValueError(
                    "proven sharedness cannot accompany an item-local classification"
                )
            # #1237: an item-local capability boundary is never reported as a
            # mission blocker.
            if self.blocker is not None or self.clearing_condition is not None:
                raise ValueError(
                    "an item-local capability boundary must not carry a mission "
                    "blocker"
                )


_KIND_REASONS: dict[SurfaceLimitationKind, SurfaceLimitationReason] = {
    SurfaceLimitationKind.UNOBSERVABLE: (
        SurfaceLimitationReason.PREFERRED_SURFACE_UNOBSERVABLE
    ),
    SurfaceLimitationKind.UNENTERABLE: (
        SurfaceLimitationReason.PREFERRED_SURFACE_UNENTERABLE
    ),
    SurfaceLimitationKind.MISSING_CAPABILITY: (
        SurfaceLimitationReason.PREFERRED_SURFACE_MISSING_CAPABILITY
    ),
}


def classify_preferred_surface_limitation(
    evidence: PreferredSurfaceLimitationEvidence,
) -> PreferredSurfaceLimitationDecision:
    """Classify one preferred-surface limitation at mission level.

    Fixed precedence, fail-closed:

    1. proven sharedness across the remaining population -> shared blocker;
    2. otherwise the limitation is an item-local capability boundary --
       unproven (including merely plausible) sharedness never promotes it;
    3. the mission continues exactly when independently actionable work
       remains admissible through canonical GitHub read evidence;
    4. operations genuinely requiring the surface stop as item-local, never
       as a mission blocker.

    The mission cursor is preserved in every classification.
    """
    if type(evidence) is not PreferredSurfaceLimitationEvidence:
        raise TypeError("evidence must be an exact PreferredSurfaceLimitationEvidence")

    kind_reason = _KIND_REASONS[evidence.limitation_kind]
    base_reasons = (
        kind_reason,
        SurfaceLimitationReason.MISSION_CURSOR_PRESERVED,
    )

    if evidence.sharedness_proven:
        return PreferredSurfaceLimitationDecision(
            schema_name=PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME,
            schema_version=PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION,
            classification=SurfaceLimitationClassification.SHARED_MISSION_BLOCKER,
            reason_codes=tuple(
                sorted(
                    set(
                        base_reasons
                        + (SurfaceLimitationReason.SHAREDNESS_PROVEN,)
                    ),
                    key=lambda item: item.value,
                )
            ),
            mission_continues=False,
            surface_requiring_operations_terminal_item_local=(
                evidence.operations_requiring_surface_count > 0
            ),
            blocker=(
                "preferred execution surface limitation proven shared across "
                f"the remaining population: {evidence.sharedness_evidence}"
            ),
            clearing_condition=(
                "re-establish a preferred execution surface, or prove the "
                "limitation no longer holds for the remaining population"
            ),
        )

    read_admissible = (
        evidence.github_read_evidence_available
        and evidence.read_admissible_remaining_count > 0
    )
    return PreferredSurfaceLimitationDecision(
        schema_name=PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME,
        schema_version=PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION,
        classification=SurfaceLimitationClassification.ITEM_LOCAL_CAPABILITY_BOUNDARY,
        reason_codes=tuple(
            sorted(
                set(
                    base_reasons
                    + (
                        SurfaceLimitationReason.SHAREDNESS_UNPROVEN_FAIL_CLOSED_ITEM_LOCAL,
                    )
                    + (
                        (
                            SurfaceLimitationReason.REMAINING_OPERATIONS_GITHUB_READ_ADMISSIBLE,
                        )
                        if read_admissible
                        else (
                            SurfaceLimitationReason.NO_REMAINING_ADMISSIBLE_OPERATIONS,
                        )
                    )
                ),
                key=lambda item: item.value,
            )
        ),
        mission_continues=read_admissible,
        surface_requiring_operations_terminal_item_local=(
            evidence.operations_requiring_surface_count > 0
        ),
        blocker=None,
        clearing_condition=None,
    )


__all__ = [
    "PREFERRED_SURFACE_LIMITATION_SCHEMA_NAME",
    "PREFERRED_SURFACE_LIMITATION_SCHEMA_VERSION",
    "PreferredSurfaceLimitationDecision",
    "PreferredSurfaceLimitationEvidence",
    "SurfaceLimitationClassification",
    "SurfaceLimitationKind",
    "SurfaceLimitationReason",
    "classify_preferred_surface_limitation",
]
