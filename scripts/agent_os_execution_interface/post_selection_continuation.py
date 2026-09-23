"""Post-selection capability-transition continuation for #1237 (AOS-ROUTE2).

The merged pre-tool half of #1237 resolves the governed route *before* a tool is
selected. This module owns the other half of the same seam: what happens when a
tool/action/surface has already been selected and then turns out to be
insufficient for the exact next bounded operation.

The failure this module removes is the #1213 reproduction:

```text
same authorized mission
-> ordinary file read insufficient/truncated
-> unsafe whole-file replacement correctly rejected
-> alternate exact-blob capability discovered
-> blocker resolved
-> execution nevertheless stopped with a handoff to the user
```

The hard invariant is that discovering a capable approved alternative is a
*continuation*, never a blocker:

```text
one tool/action unavailable or insufficient  !=  Agent OS mission unavailable
alternative capability discovered            !=  user handoff required
```

This module is a pure decision function. It consumes the already-merged #1039
:class:`ExecutionSurfaceAvailabilityOutcome` and returns one of #1237's six
fixed classifications together with the obligations the caller must discharge
before the alternative is used. It deliberately owns nothing else:

- it does not select or re-derive a route (#918 owns routing);
- it does not retry, loop, enumerate tools, or schedule anything;
- it does not read, write, or reacquire state itself -- it *requires* the caller
  to have reacquired it, and fails closed when that is unproven;
- it introduces no router, Scheduler, lease, capability registry, checkpoint
  store, persistent state, or execution authority.

Adjacent safety domains stay with their owners. Red CI (#1251), base drift
(#1209), and stale gates (#1235) are refused outright rather than absorbed;
repeated equivalent transitions are handed to #1200 instead of looping; and
cross-surface evidence compatibility is delegated to #1201 as an obligation
rather than reimplemented here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from agent_os_execution_service.execution_surface_availability import (
    ExecutionSurfaceAvailabilityOutcome,
)

POST_SELECTION_CONTINUATION_SCHEMA_NAME = (
    "agent-os.execution-interface-post-selection-continuation"
)
POST_SELECTION_CONTINUATION_SCHEMA_VERSION = "1.0"

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", re.ASCII)

#: The only #1039 outcomes that represent a post-selection limitation. A
#: selected surface that is available is not this module's concern, and calling
#: it with one is a caller contract error rather than a seventh classification.
_LIMITATION_OUTCOMES = frozenset(
    {
        ExecutionSurfaceAvailabilityOutcome.SELECTED_SURFACE_UNAVAILABLE,
        ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION,
    }
)


class ContinuationClassification(str, Enum):
    """#1237's finite post-selection vocabulary. No value is added here."""

    CAPABILITY_ALTERNATIVE_AVAILABLE = "capability-alternative-available"
    PARTIAL_EFFECT_RECONCILIATION_REQUIRED = "partial-effect-reconciliation-required"
    NO_CAPABLE_AUTHORIZED_ROUTE = "no-capable-authorized-route"
    CURRENTNESS_OR_IDENTITY_UNPROVEN = "currentness-or-identity-unproven"
    AUTHORITY_OR_SCOPE_BOUNDARY = "authority-or-scope-boundary"
    MATERIAL_USER_DECISION = "material-user-decision"


class PriorAttemptEffect(str, Enum):
    """What the insufficient attempt is *proven* to have done to canonical state."""

    #: Proven zero effect: the alternative may perform the mutation.
    NONE_PROVEN = "none-proven"
    #: The attempt may or may not have mutated state: read back before writing.
    AMBIGUOUS = "ambiguous"
    #: Readback proved the intended state already exists: converge, do not repeat.
    DESIRED_STATE_ALREADY_PRESENT = "desired-state-already-present"


class NonAbsorbedDomain(str, Enum):
    """Adjacent lifecycles this seam must never decide."""

    BASE_DRIFT = "base-drift"
    RED_CI = "red-ci"
    STALE_GATE = "stale-gate"


#: Each non-absorbed domain names its owning issue, so a caller that misroutes
#: one is told exactly where it belongs instead of receiving a continuation.
NON_ABSORBED_DOMAIN_OWNERS: dict[NonAbsorbedDomain, str] = {
    NonAbsorbedDomain.BASE_DRIFT: "#1209",
    NonAbsorbedDomain.RED_CI: "#1251",
    NonAbsorbedDomain.STALE_GATE: "#1235",
}

#: Repeated equivalent transitions belong to #1200 semantic no-progress
#: detection; this seam stops offering alternatives rather than looping.
SEMANTIC_NO_PROGRESS_OWNER = "#1200"
#: Cross-surface evidence compatibility belongs to #1201.
EVIDENCE_COMPATIBILITY_OWNER = "#1201"


class ContinuationReason(str, Enum):
    """Finite reason codes explaining one deterministic classification."""

    ALTERNATIVE_CAPABILITY_APPROVED = "alternative-capability-approved"
    DESIRED_STATE_ALREADY_PRESENT = "desired-state-already-present"
    PRIOR_EFFECT_AMBIGUOUS = "prior-effect-ambiguous"
    NO_APPROVED_ALTERNATIVE = "no-approved-alternative"
    EQUIVALENT_TRANSITION_REPEATED = "equivalent-transition-repeated"
    TARGET_IDENTITY_UNPROVEN = "target-identity-unproven"
    EXACT_BLOB_IDENTITY_UNPROVEN = "exact-blob-identity-unproven"
    CROSS_SURFACE_EVIDENCE_UNVERIFIED = "cross-surface-evidence-unverified"
    ALTERNATIVE_TARGETS_DIFFERENT_LINEAGE = "alternative-targets-different-lineage"
    ALTERNATIVE_WIDENS_AUTHORITY = "alternative-widens-authority"
    ACTIVE_FOREIGN_LEASE = "active-foreign-lease"
    MATERIAL_DECISION_REQUIRED = "material-decision-required"


class ContinuationObligation(str, Enum):
    """What the caller must discharge before and while using the alternative."""

    REACQUIRE_OPERATION_BINDINGS = "reacquire-operation-bindings"
    REACQUIRE_EXACT_HEAD = "reacquire-exact-head"
    REACQUIRE_EXACT_BLOB = "reacquire-exact-blob"
    READ_BACK_CANONICAL_STATE = "read-back-canonical-state"
    PRESERVE_EXISTING_LINEAGE = "preserve-existing-lineage"
    REUSE_EVIDENCE_COMPATIBILITY = "reuse-evidence-compatibility"
    ROUTE_THROUGH_OWNING_WRITER = "route-through-owning-writer"
    SUPPRESS_DUPLICATE_MUTATION = "suppress-duplicate-mutation"


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuationLineage:
    """The existing issue/branch/PR/checkpoint/lease identity being continued.

    Equality is structural, which is what makes the same-lineage invariant
    checkable: an alternative that resolves to a different branch, pull request,
    checkpoint, or lease is not the same lineage and is rejected rather than
    silently substituted.
    """

    repository: str
    issue_number: int
    branch: str | None = None
    pull_request: int | None = None
    checkpoint_id: str | None = None
    lease_id: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.repository) is not str
            or _REPOSITORY_RE.fullmatch(self.repository) is None
        ):
            raise ValueError("repository must be owner/name syntax")
        if type(self.issue_number) is not int or self.issue_number < 1:
            raise TypeError("issue_number must be a positive built-in integer")
        for name in ("branch", "checkpoint_id", "lease_id"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value):
                raise ValueError(f"{name} must be None or non-empty exact text")
        if self.pull_request is not None and (
            type(self.pull_request) is not int or self.pull_request < 1
        ):
            raise TypeError("pull_request must be None or a positive built-in integer")


@dataclass(frozen=True, slots=True, kw_only=True)
class PostSelectionAttemptEvidence:
    """Evidence about one insufficient attempt at one exact bounded operation.

    Every field is evidence the caller has already established. This module
    proves nothing on its own: an unset proof flag means *unproven*, and
    unproven fails closed.
    """

    operation_id: str
    lineage: ContinuationLineage
    surface_outcome: ExecutionSurfaceAvailabilityOutcome
    #: Identity of an already-approved capability that can perform the *same*
    #: bounded operation. ``None`` means no capable authorized route is known.
    approved_alternative_capability: str | None = None
    #: The lineage the alternative would actually act on, when it differs from
    #: the caller's assertion. ``None`` asserts the same lineage.
    alternative_lineage: ContinuationLineage | None = None
    alternative_widens_authority: bool = False
    prior_effect: PriorAttemptEffect = PriorAttemptEffect.NONE_PROVEN
    #: True once the caller has reacquired the operation's current target
    #: identity (head, target, descriptor) after the failure.
    target_identity_reacquired: bool = False
    #: True when the operation replaces whole-file content and therefore needs
    #: exact current blob identity, not a truncated or rendered view.
    requires_exact_blob_identity: bool = False
    exact_blob_identity_reacquired: bool = False
    runtime_surface_transition: bool = False
    evidence_compatibility_confirmed: bool = False
    #: A valid active lease held by another execution. Never taken over here.
    active_foreign_lease: bool = False
    equivalent_transition_repeated: bool = False
    material_decision_required: bool = False
    #: Set only when the caller misrouted an adjacent lifecycle into this seam.
    non_absorbed_domain: NonAbsorbedDomain | None = None

    def __post_init__(self) -> None:
        if type(self.operation_id) is not str or not self.operation_id:
            raise ValueError("operation_id must be non-empty exact text")
        if type(self.lineage) is not ContinuationLineage:
            raise TypeError("lineage must be an exact ContinuationLineage")
        if type(self.surface_outcome) is not ExecutionSurfaceAvailabilityOutcome:
            raise TypeError(
                "surface_outcome must be an exact ExecutionSurfaceAvailabilityOutcome"
            )
        if self.approved_alternative_capability is not None and (
            type(self.approved_alternative_capability) is not str
            or not self.approved_alternative_capability
        ):
            raise ValueError(
                "approved_alternative_capability must be None or non-empty exact text"
            )
        if self.alternative_lineage is not None and (
            type(self.alternative_lineage) is not ContinuationLineage
        ):
            raise TypeError("alternative_lineage must be None or ContinuationLineage")
        if type(self.prior_effect) is not PriorAttemptEffect:
            raise TypeError("prior_effect must be an exact PriorAttemptEffect")
        if self.non_absorbed_domain is not None and (
            type(self.non_absorbed_domain) is not NonAbsorbedDomain
        ):
            raise TypeError("non_absorbed_domain must be None or NonAbsorbedDomain")
        for name in (
            "alternative_widens_authority",
            "target_identity_reacquired",
            "requires_exact_blob_identity",
            "exact_blob_identity_reacquired",
            "runtime_surface_transition",
            "evidence_compatibility_confirmed",
            "active_foreign_lease",
            "equivalent_transition_repeated",
            "material_decision_required",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuationDecision:
    """One bounded, non-authorizing post-selection continuation decision."""

    schema_name: Literal["agent-os.execution-interface-post-selection-continuation"]
    schema_version: Literal["1.0"]
    decision_id: str
    operation_id: str
    lineage: ContinuationLineage
    classification: ContinuationClassification
    reason_codes: tuple[ContinuationReason, ...]
    obligations: tuple[ContinuationObligation, ...]
    #: Continue the same mission automatically, without a new user prompt.
    continue_automatically: bool
    #: Whether the alternative may perform the mutation now. False whenever the
    #: intended state already exists, so convergence never writes twice.
    mutation_permitted: bool
    alternative_capability: str | None
    delegated_owner: str | None
    blocker: str | None
    clearing_condition: str | None
    #: Fixed-false contract fields. ``capability_limitation_is_mission_blocker``
    #: encodes #1237's hard invariant: one unavailable or insufficient
    #: tool/action/surface is capability evidence, never evidence that the Agent
    #: OS mission is blocked.
    capability_limitation_is_mission_blocker: Literal[False] = field(
        default=False, init=False
    )
    execution_authorized: Literal[False] = field(default=False, init=False)
    github_writes_authorized: Literal[False] = field(default=False, init=False)
    merge_authorized: Literal[False] = field(default=False, init=False)
    issue_closure_authorized: Literal[False] = field(default=False, init=False)
    external_writes_authorized: Literal[False] = field(default=False, init=False)
    lease_acquired: Literal[False] = field(default=False, init=False)
    scheduler_invoked: Literal[False] = field(default=False, init=False)
    competing_lineage_created: Literal[False] = field(default=False, init=False)
    side_effects_performed: Literal[False] = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.schema_name != POST_SELECTION_CONTINUATION_SCHEMA_NAME:
            raise ValueError("unsupported post-selection continuation schema name")
        if self.schema_version != POST_SELECTION_CONTINUATION_SCHEMA_VERSION:
            raise ValueError("unsupported post-selection continuation schema version")
        if type(self.classification) is not ContinuationClassification:
            raise TypeError("classification must be exact ContinuationClassification")
        if type(self.reason_codes) is not tuple or not self.reason_codes:
            raise ValueError("reason_codes must be a non-empty exact tuple")
        if any(type(item) is not ContinuationReason for item in self.reason_codes):
            raise TypeError("reason_codes contain an invalid value")
        if self.reason_codes != tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        ):
            raise ValueError("reason_codes must be sorted and unique")
        if type(self.obligations) is not tuple:
            raise TypeError("obligations must be an exact tuple")
        if any(type(item) is not ContinuationObligation for item in self.obligations):
            raise TypeError("obligations contain an invalid value")
        if self.obligations != tuple(
            sorted(set(self.obligations), key=lambda item: item.value)
        ):
            raise ValueError("obligations must be sorted and unique")
        for name in ("continue_automatically", "mutation_permitted"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")

        continuing = (
            self.classification
            is ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE
        )
        if continuing:
            # #1237: "Do not report CAPABILITY_ALTERNATIVE_AVAILABLE as a
            # blocker." The contract makes that structurally impossible.
            if not self.continue_automatically:
                raise ValueError("an available alternative must continue automatically")
            if self.blocker is not None or self.clearing_condition is not None:
                raise ValueError("an available alternative must not carry a blocker")
            if not self.alternative_capability:
                raise ValueError("an available alternative must name the capability")
            if ContinuationObligation.PRESERVE_EXISTING_LINEAGE not in self.obligations:
                raise ValueError("continuation must preserve the existing lineage")
        else:
            if self.continue_automatically:
                raise ValueError("only an available alternative continues automatically")
            if self.mutation_permitted:
                raise ValueError("only an available alternative may mutate")
        if self.mutation_permitted and not continuing:
            raise ValueError("mutation requires an available alternative")
        if self.classification is ContinuationClassification.NO_CAPABLE_AUTHORIZED_ROUTE:
            if not self.blocker or not self.clearing_condition:
                raise ValueError(
                    "no capable authorized route must state one blocker and its "
                    "exact clearing condition"
                )
        if self.decision_id != _decision_id(
            operation_id=self.operation_id,
            lineage=self.lineage,
            classification=self.classification,
            reasons=self.reason_codes,
            obligations=self.obligations,
        ):
            raise ValueError("decision_id does not match continuation decision")


def _decision_id(
    *,
    operation_id: str,
    lineage: ContinuationLineage,
    classification: ContinuationClassification,
    reasons: tuple[ContinuationReason, ...],
    obligations: tuple[ContinuationObligation, ...],
) -> str:
    payload = {
        "schema_name": POST_SELECTION_CONTINUATION_SCHEMA_NAME,
        "schema_version": POST_SELECTION_CONTINUATION_SCHEMA_VERSION,
        "operation_id": operation_id,
        "lineage": {
            "repository": lineage.repository,
            "issue_number": lineage.issue_number,
            "branch": lineage.branch,
            "pull_request": lineage.pull_request,
            "checkpoint_id": lineage.checkpoint_id,
            "lease_id": lineage.lease_id,
        },
        "classification": classification.value,
        "reason_codes": [item.value for item in reasons],
        "obligations": [item.value for item in obligations],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = hashlib.sha256(
        b"agent-os.execution-interface-post-selection-continuation:v1\0" + encoded
    ).hexdigest()
    return f"post-selection-continuation:{digest}"


def _decision(
    *,
    evidence: PostSelectionAttemptEvidence,
    classification: ContinuationClassification,
    reasons: tuple[ContinuationReason, ...],
    obligations: tuple[ContinuationObligation, ...],
    continue_automatically: bool = False,
    mutation_permitted: bool = False,
    alternative_capability: str | None = None,
    delegated_owner: str | None = None,
    blocker: str | None = None,
    clearing_condition: str | None = None,
) -> ContinuationDecision:
    canonical_reasons = tuple(sorted(set(reasons), key=lambda item: item.value))
    canonical_obligations = tuple(
        sorted(set(obligations), key=lambda item: item.value)
    )
    return ContinuationDecision(
        schema_name=POST_SELECTION_CONTINUATION_SCHEMA_NAME,
        schema_version=POST_SELECTION_CONTINUATION_SCHEMA_VERSION,
        decision_id=_decision_id(
            operation_id=evidence.operation_id,
            lineage=evidence.lineage,
            classification=classification,
            reasons=canonical_reasons,
            obligations=canonical_obligations,
        ),
        operation_id=evidence.operation_id,
        lineage=evidence.lineage,
        classification=classification,
        reason_codes=canonical_reasons,
        obligations=canonical_obligations,
        continue_automatically=continue_automatically,
        mutation_permitted=mutation_permitted,
        alternative_capability=alternative_capability,
        delegated_owner=delegated_owner,
        blocker=blocker,
        clearing_condition=clearing_condition,
    )


def classify_post_selection_continuation(
    evidence: PostSelectionAttemptEvidence,
) -> ContinuationDecision:
    """Classify one insufficient attempt into #1237's finite continuation states.

    Precedence is fixed and fail-closed, strongest governance boundary first:

    1. an adjacent lifecycle misrouted into this seam is refused outright;
    2. a valid active foreign lease -- never taken over;
    3. an alternative that widens authority or changes lineage -- never
       silently substituted;
    4. a genuine material decision, including a route that already required one;
    5. ambiguous prior effects -- read back before any alternate write;
    6. no approved alternative, or a repeated equivalent transition (#1200);
    7. currentness or identity that the caller has not reacquired;
    8. otherwise the alternative is consumed and the mission continues.

    Raises ``ValueError`` when called for a domain this seam does not own or for
    a surface outcome that is not a limitation at all.
    """

    if type(evidence) is not PostSelectionAttemptEvidence:
        raise TypeError("evidence must be an exact PostSelectionAttemptEvidence")
    if evidence.non_absorbed_domain is not None:
        owner = NON_ABSORBED_DOMAIN_OWNERS[evidence.non_absorbed_domain]
        raise ValueError(
            f"{evidence.non_absorbed_domain.value} lifecycle is owned by {owner}; "
            "#1237 post-selection continuation must not absorb it"
        )
    if evidence.surface_outcome not in _LIMITATION_OUTCOMES:
        raise ValueError(
            "post-selection continuation applies only after a capability "
            "limitation; an available selected surface needs no continuation "
            "decision"
        )

    lineage_obligations = (
        ContinuationObligation.PRESERVE_EXISTING_LINEAGE,
        ContinuationObligation.ROUTE_THROUGH_OWNING_WRITER,
    )

    if evidence.active_foreign_lease:
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY,
            reasons=(ContinuationReason.ACTIVE_FOREIGN_LEASE,),
            obligations=lineage_obligations,
        )

    if evidence.alternative_widens_authority:
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY,
            reasons=(ContinuationReason.ALTERNATIVE_WIDENS_AUTHORITY,),
            obligations=lineage_obligations,
        )

    if (
        evidence.alternative_lineage is not None
        and evidence.alternative_lineage != evidence.lineage
    ):
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.AUTHORITY_OR_SCOPE_BOUNDARY,
            reasons=(ContinuationReason.ALTERNATIVE_TARGETS_DIFFERENT_LINEAGE,),
            obligations=lineage_obligations,
        )

    if (
        evidence.material_decision_required
        or evidence.surface_outcome
        is ExecutionSurfaceAvailabilityOutcome.NEEDS_DECISION
    ):
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.MATERIAL_USER_DECISION,
            reasons=(ContinuationReason.MATERIAL_DECISION_REQUIRED,),
            obligations=lineage_obligations,
        )

    if evidence.prior_effect is PriorAttemptEffect.AMBIGUOUS:
        return _decision(
            evidence=evidence,
            classification=(
                ContinuationClassification.PARTIAL_EFFECT_RECONCILIATION_REQUIRED
            ),
            reasons=(ContinuationReason.PRIOR_EFFECT_AMBIGUOUS,),
            obligations=lineage_obligations
            + (ContinuationObligation.READ_BACK_CANONICAL_STATE,),
        )

    if evidence.approved_alternative_capability is None:
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.NO_CAPABLE_AUTHORIZED_ROUTE,
            reasons=(ContinuationReason.NO_APPROVED_ALTERNATIVE,),
            obligations=lineage_obligations,
            blocker=(
                "no already-approved capability can perform the exact next "
                f"bounded operation {evidence.operation_id}"
            ),
            clearing_condition=(
                "approve or make available one capability that can perform this "
                "exact operation on the existing lineage"
            ),
        )

    if evidence.equivalent_transition_repeated:
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.NO_CAPABLE_AUTHORIZED_ROUTE,
            reasons=(ContinuationReason.EQUIVALENT_TRANSITION_REPEATED,),
            obligations=lineage_obligations,
            delegated_owner=SEMANTIC_NO_PROGRESS_OWNER,
            blocker=(
                "an equivalent capability transition has already repeated for "
                f"operation {evidence.operation_id}"
            ),
            clearing_condition=(
                f"{SEMANTIC_NO_PROGRESS_OWNER} semantic no-progress evaluation "
                "resolves the repeated transition; this seam does not retry"
            ),
        )

    currentness_reasons: list[ContinuationReason] = []
    currentness_obligations: list[ContinuationObligation] = []
    if not evidence.target_identity_reacquired:
        currentness_reasons.append(ContinuationReason.TARGET_IDENTITY_UNPROVEN)
        currentness_obligations.append(ContinuationObligation.REACQUIRE_EXACT_HEAD)
    if evidence.requires_exact_blob_identity and not evidence.exact_blob_identity_reacquired:
        currentness_reasons.append(ContinuationReason.EXACT_BLOB_IDENTITY_UNPROVEN)
        currentness_obligations.append(ContinuationObligation.REACQUIRE_EXACT_BLOB)
    if evidence.runtime_surface_transition and not evidence.evidence_compatibility_confirmed:
        currentness_reasons.append(ContinuationReason.CROSS_SURFACE_EVIDENCE_UNVERIFIED)
        currentness_obligations.append(ContinuationObligation.REUSE_EVIDENCE_COMPATIBILITY)
    if currentness_reasons:
        return _decision(
            evidence=evidence,
            classification=ContinuationClassification.CURRENTNESS_OR_IDENTITY_UNPROVEN,
            reasons=tuple(currentness_reasons),
            obligations=lineage_obligations
            + tuple(currentness_obligations)
            + (ContinuationObligation.REACQUIRE_OPERATION_BINDINGS,),
            delegated_owner=(
                EVIDENCE_COMPATIBILITY_OWNER
                if ContinuationReason.CROSS_SURFACE_EVIDENCE_UNVERIFIED
                in currentness_reasons
                else None
            ),
        )

    already_present = (
        evidence.prior_effect is PriorAttemptEffect.DESIRED_STATE_ALREADY_PRESENT
    )
    obligations = list(lineage_obligations)
    obligations.append(ContinuationObligation.REACQUIRE_OPERATION_BINDINGS)
    if evidence.runtime_surface_transition:
        obligations.append(ContinuationObligation.REUSE_EVIDENCE_COMPATIBILITY)
    if already_present:
        obligations.append(ContinuationObligation.SUPPRESS_DUPLICATE_MUTATION)

    return _decision(
        evidence=evidence,
        classification=ContinuationClassification.CAPABILITY_ALTERNATIVE_AVAILABLE,
        reasons=(
            (ContinuationReason.DESIRED_STATE_ALREADY_PRESENT,)
            if already_present
            else (ContinuationReason.ALTERNATIVE_CAPABILITY_APPROVED,)
        ),
        obligations=tuple(obligations),
        continue_automatically=True,
        mutation_permitted=not already_present,
        alternative_capability=evidence.approved_alternative_capability,
        delegated_owner=(
            EVIDENCE_COMPATIBILITY_OWNER
            if evidence.runtime_surface_transition
            else None
        ),
    )
