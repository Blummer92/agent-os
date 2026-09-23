"""Freshness binding checks and the dependency-directed invalidation graph.

The graph below is declarative documentation of *what invalidates what*; it
is not itself a live watcher. ``compiler.py`` enforces freshness by
reverifying each supplied identity against the canonical object that should
still agree with it (the binding checks in ``evaluate_freshness_bindings``)
and by embedding ``build_invalidation_manifest``'s description of the graph
in every compiled packet, so a downstream consumer knows what to re-check
before trusting a packet it already holds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import CandidatePacketCompilerInput, CandidatePacketPhase

# (trigger, targets-invalidated-by-that-trigger). Order is authored, not
# alphabetical, so the manifest reads as a dependency trail from source
# toward the packet -- but the manifest itself is rendered in sorted order
# (see ``build_invalidation_manifest``) so two equal graphs always serialize
# identically regardless of authoring order.
_INVALIDATION_EDGES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "source-revision",
        ("source", "issueplan", "readiness", "planning", "repository-evidence",
         "proposal", "approval", "validation", "execution-packet", "candidate-packet"),
    ),
    (
        "issue-body",
        ("source", "issueplan", "readiness", "planning", "repository-evidence",
         "proposal", "approval", "validation", "execution-packet", "candidate-packet"),
    ),
    (
        "evaluator-sha",
        ("planning", "planning-handoff", "proposal", "approval", "validation",
         "execution-packet", "candidate-packet"),
    ),
    (
        "base-sha",
        ("repository-evidence", "proposal", "approval", "validation",
         "execution-packet", "candidate-packet"),
    ),
    (
        "candidate-sha",
        ("repository-evidence", "proposal", "approval", "validation",
         "execution-packet", "candidate-packet"),
    ),
    (
        "tested-sha",
        ("validation", "validation-subject", "validation-plan", "execution-request",
         "runtime-configuration", "candidate-packet"),
    ),
    (
        "implementation-contract",
        ("issueplan", "readiness", "planning", "proposal", "approval", "validation",
         "execution-packet", "candidate-packet"),
    ),
    (
        "proposal",
        ("approval-candidate", "applicability", "projection", "validation",
         "execution-packet", "candidate-packet"),
    ),
    (
        "approval-revision",
        ("applicability", "projection", "validation", "execution-packet",
         "candidate-packet"),
    ),
    ("projection", ("validation", "execution-packet", "candidate-packet")),
    (
        "validation-plan",
        ("execution-request", "runtime-configuration", "candidate-packet"),
    ),
    ("scope-or-tests-or-timeouts", ("candidate-packet",)),
)

_EXECUTION_ONLY_TARGETS = frozenset(
    {
        "validation",
        "validation-subject",
        "validation-plan",
        "execution-request",
        "runtime-configuration",
        "execution-packet",
        "approval-candidate",
        "applicability",
        "projection",
    }
)


def build_invalidation_manifest(phase: CandidatePacketPhase) -> tuple[str, ...]:
    """Deterministic ``"trigger:target,target,..."`` entries for one phase.

    ``approval-ready`` packets drop targets that only exist once an
    execution-candidate compile has run (validation/execution-packet
    objects); a trigger with no remaining target for the phase is omitted
    entirely rather than emitted with an empty target list.
    """
    if not isinstance(phase, CandidatePacketPhase):
        raise TypeError("phase must be a CandidatePacketPhase")
    entries: list[str] = []
    for trigger, targets in _INVALIDATION_EDGES:
        if phase is CandidatePacketPhase.APPROVAL_READY:
            filtered = tuple(
                target for target in targets if target not in _EXECUTION_ONLY_TARGETS
            )
        else:
            filtered = targets
        if not filtered:
            continue
        entries.append(f"{trigger}:{','.join(filtered)}")
    return tuple(sorted(entries))


@dataclass(frozen=True, slots=True)
class FreshnessBindingResult:
    """Whether the compiler input's declared identities still agree.

    ``fresh`` is ``True`` only when every declared identity matches the
    canonical object that should carry it; ``reason_code`` names the first
    mismatch found, in the same fixed order every time the same input is
    checked, so repeated evaluation of stale evidence is deterministic.
    """

    fresh: bool
    reason_code: str | None
    expected_identity: str | None = None
    observed_identity: str | None = None


def evaluate_freshness_bindings(
    compiler_input: CandidatePacketCompilerInput,
) -> FreshnessBindingResult:
    """Reverify the compiler input's expected identities against the stages.

    This performs only the freshness/binding half of validation -- structural
    presence and stage-status checks are ``compiler.py``'s job, run before
    this is ever called. Each check below reads a field that already exists
    on an already-typed canonical object; nothing here infers or guesses.
    """
    readiness = compiler_input.readiness_stage_result
    snapshot = readiness.snapshot
    issueplan = readiness.issueplan_current_state_evidence

    if snapshot.source_revision != compiler_input.expected_source_revision:
        return FreshnessBindingResult(
            False,
            "source-stage.source-revision-mismatch",
            expected_identity=compiler_input.expected_source_revision,
            observed_identity=snapshot.source_revision,
        )
    if issueplan.source_snapshot_fingerprint != compiler_input.expected_source_snapshot_fingerprint:
        return FreshnessBindingResult(
            False,
            "issueplan.fingerprint-mismatch",
            expected_identity=compiler_input.expected_source_snapshot_fingerprint,
            observed_identity=issueplan.source_snapshot_fingerprint,
        )
    if issueplan.scanner_result_fingerprint != compiler_input.expected_scanner_result_fingerprint:
        return FreshnessBindingResult(
            False,
            "issueplan.fingerprint-mismatch",
            expected_identity=compiler_input.expected_scanner_result_fingerprint,
            observed_identity=issueplan.scanner_result_fingerprint,
        )
    if (
        issueplan.source_snapshot.candidate_set_fingerprint
        != compiler_input.expected_candidate_set_fingerprint
    ):
        return FreshnessBindingResult(
            False,
            "issueplan.fingerprint-mismatch",
            expected_identity=compiler_input.expected_candidate_set_fingerprint,
            observed_identity=issueplan.source_snapshot.candidate_set_fingerprint,
        )
    if (
        issueplan.implementation_contract_fingerprint
        != compiler_input.expected_implementation_contract_fingerprint
    ):
        return FreshnessBindingResult(
            False,
            "issueplan.fingerprint-mismatch",
            expected_identity=compiler_input.expected_implementation_contract_fingerprint,
            observed_identity=issueplan.implementation_contract_fingerprint,
        )
    if issueplan.freshness_boundary != compiler_input.freshness_boundary:
        return FreshnessBindingResult(
            False,
            "issueplan.freshness-boundary-mismatch",
            expected_identity=compiler_input.freshness_boundary,
            observed_identity=issueplan.freshness_boundary,
        )

    proposal_evidence = compiler_input.proposal_stage_result.repository_state_evidence
    if proposal_evidence is not None and proposal_evidence.tested_sha != compiler_input.tested_sha:
        return FreshnessBindingResult(
            False,
            "cross-binding.tested-sha-mismatch",
            expected_identity=compiler_input.tested_sha,
            observed_identity=proposal_evidence.tested_sha,
        )

    return FreshnessBindingResult(True, None)
