"""AOS-TTFD-1 Phase 1 diagnostic timeline layered on the CRH8A benchmark.

This module deliberately reuses CRH8A reviewer packets, hidden answer keys,
fingerprints, contamination state, run identity, and scoring vocabulary. It adds
only bounded diagnostic-action/timeline and native-canary evidence semantics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .code_review_benchmark import AnswerKey, ReviewerPacket, validate_case
from .models import EvidenceValidationError, deterministic_id

BENCHMARK_VERSION = "1.0.0"
SCORER_VERSION = "1.0.0"
CASE_VERSION = "1.0.0"
MAX_ACTIONS = 128
MAX_ITEMS = 64
MAX_TEXT = 10000

PHASE1_CASES = (
    "TTFD-A02", "TTFD-B01", "TTFD-B02", "TTFD-B05", "TTFD-C01",
    "TTFD-D01", "TTFD-D02", "TTFD-E02", "TTFD-F01", "TTFD-G04",
)
NATIVE_CANARY_CASES = frozenset({"TTFD-D01", "TTFD-D02"})


class TraceEvent(str, Enum):
    T0_MISSION_RECEIVED = "T0"
    T1_AUTHORITATIVE_READ = "T1"
    T2_CORRECT_HYPOTHESIS = "T2"
    T3_DEFECT_CONFIRMED = "T3"
    T4_OWNER_ACTION_IDENTIFIED = "T4"
    T5_TERMINAL_DISPOSITION = "T5"


class ActionKind(str, Enum):
    AUTHORITATIVE_READ = "authoritative-read"
    REDUNDANT_READ = "redundant-read"
    SURFACE_FAILURE = "surface-failure"
    ALTERNATE_ROUTE = "alternate-route"
    STALE_EVIDENCE = "stale-evidence"
    DUPLICATE_VALIDATION = "duplicate-validation"
    INCORRECT_HYPOTHESIS = "incorrect-hypothesis"
    USER_PROMPT = "unnecessary-user-prompt"
    NO_PROGRESS = "no-progress"
    PARENT_RESUMPTION = "parent-mission-resumption"
    DISCOVERY = "tool-or-capability-discovery"
    SUBORDINATE_MUTATION = "subordinate-mutation"
    NEXT_ADMITTED_OPERATION = "next-admitted-operation"


class ConformanceResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not-applicable"
    INCOMPLETE = "integration-evidence-incomplete"


class ComparabilityClass(str, Enum):
    BEHAVIORALLY_ELIGIBLE = "behaviorally-eligible"
    PROFILE_COMPARABLE = "profile-comparable"
    RUNTIME_EXACT_COMPARABLE = "runtime-exact-comparable"
    INTEGRATION_EVIDENCE_INCOMPLETE = "integration-evidence-incomplete"
    CONTAMINATED_OR_INELIGIBLE = "contaminated-or-ineligible"


def _text(value: object, field: str, *, required: bool = True) -> str:
    if type(value) is not str or len(value) > MAX_TEXT or (required and not value.strip()):
        raise EvidenceValidationError(f"{field} must be a bounded string")
    return value.strip()


def _items(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if type(values) is not tuple or len(values) > MAX_ITEMS:
        raise EvidenceValidationError(f"{field} must be a bounded tuple")
    return tuple(sorted({_text(value, field) for value in values}))


@dataclass(frozen=True, slots=True)
class TimelinePoint:
    event: TraceEvent
    monotonic_seconds: float

    def __post_init__(self) -> None:
        if type(self.event) is not TraceEvent:
            raise EvidenceValidationError("timeline event must use TraceEvent")
        if type(self.monotonic_seconds) not in {int, float} or self.monotonic_seconds < 0:
            raise EvidenceValidationError("timeline time must be non-negative monotonic seconds")


@dataclass(frozen=True, slots=True)
class DiagnosticAction:
    sequence: int
    kind: ActionKind
    evidence_ref: str
    monotonic_seconds: float

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise EvidenceValidationError("diagnostic action sequence must be positive")
        if type(self.kind) is not ActionKind:
            raise EvidenceValidationError("diagnostic action kind must use ActionKind")
        _text(self.evidence_ref, "diagnostic_action.evidence_ref")
        if type(self.monotonic_seconds) not in {int, float} or self.monotonic_seconds < 0:
            raise EvidenceValidationError("diagnostic action time must be non-negative monotonic seconds")


@dataclass(frozen=True, slots=True)
class NativeCanaryEvidence:
    host_surface: str
    client_version_if_exposed: str = ""
    native_runtime_identity_if_exposed: str = ""
    native_runtime_identity_available: bool = False
    tool_profile_fingerprint: str = ""
    continuation_contract_fingerprint: str = ""
    parent_lineage_identity: str = ""
    observed_sequence_fingerprint: str = ""
    comparability_class: ComparabilityClass = ComparabilityClass.INTEGRATION_EVIDENCE_INCOMPLETE
    missing_comparability_fields: tuple[str, ...] = ()
    next_admitted_operation_executed: bool | None = None
    genuine_terminal_blocker: bool | None = None

    def __post_init__(self) -> None:
        _text(self.host_surface, "native_canary.host_surface")
        _text(self.client_version_if_exposed, "native_canary.client_version", required=False)
        _text(self.native_runtime_identity_if_exposed, "native_canary.runtime_identity", required=False)
        _text(self.tool_profile_fingerprint, "native_canary.tool_profile_fingerprint", required=False)
        _text(self.continuation_contract_fingerprint, "native_canary.continuation_contract_fingerprint", required=False)
        _text(self.parent_lineage_identity, "native_canary.parent_lineage_identity", required=False)
        _text(self.observed_sequence_fingerprint, "native_canary.observed_sequence_fingerprint", required=False)
        _items(self.missing_comparability_fields, "native_canary.missing_comparability_fields")
        if type(self.comparability_class) is not ComparabilityClass:
            raise EvidenceValidationError("native canary comparability class is unsupported")
        if self.native_runtime_identity_available and not self.native_runtime_identity_if_exposed:
            raise EvidenceValidationError("available native runtime identity must be recorded")
        if self.comparability_class is ComparabilityClass.RUNTIME_EXACT_COMPARABLE and not self.native_runtime_identity_available:
            raise EvidenceValidationError("runtime-exact-comparable requires exposed runtime identity")
        if self.comparability_class in {
            ComparabilityClass.BEHAVIORALLY_ELIGIBLE,
            ComparabilityClass.PROFILE_COMPARABLE,
            ComparabilityClass.RUNTIME_EXACT_COMPARABLE,
        } and (self.next_admitted_operation_executed is None or self.genuine_terminal_blocker is None):
            raise EvidenceValidationError("behaviorally eligible canary requires bounded continuation outcome")


@dataclass(frozen=True, slots=True)
class TTFDCase:
    packet: ReviewerPacket
    answer_key: AnswerKey
    canonical_anchor_refs: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        return deterministic_id({
            "packet_fingerprint": self.packet.fingerprint,
            "canonical_anchor_refs": _items(self.canonical_anchor_refs, "canonical_anchor_refs"),
            "case_version": CASE_VERSION,
        })

    def __post_init__(self) -> None:
        validate_case(self.packet, self.answer_key)
        if self.packet.case_id not in PHASE1_CASES:
            raise EvidenceValidationError("case is not in the frozen AOS-TTFD Phase 1 matrix")
        _items(self.canonical_anchor_refs, "canonical_anchor_refs")


@dataclass(frozen=True, slots=True)
class TTFDRun:
    benchmark_version: str
    scorer_version: str
    case_id: str
    case_version: str
    packet_fingerprint: str
    model_identity: str
    reasoning_setting: str
    run_number: int
    tool_profile: tuple[str, ...]
    baseline_sha: str
    fixture_sha: str
    timeline: tuple[TimelinePoint, ...]
    actions: tuple[DiagnosticAction, ...]
    discovered_outcome: str
    classification_correct: bool
    owner_next_action_correct: bool
    repository_conformance: ConformanceResult
    native_host_conformance: ConformanceResult = ConformanceResult.NOT_APPLICABLE
    native_canary: NativeCanaryEvidence | None = None
    false_positive: bool = False
    contaminated: bool = False
    contamination_reasons: tuple[str, ...] = ()

    @property
    def run_identity(self) -> str:
        return deterministic_id({
            "benchmark_version": self.benchmark_version,
            "scorer_version": self.scorer_version,
            "case_id": self.case_id,
            "case_version": self.case_version,
            "packet_fingerprint": self.packet_fingerprint,
            "model_identity": self.model_identity,
            "reasoning_setting": self.reasoning_setting,
            "run_number": self.run_number,
            "tool_profile": self.tool_profile,
            "baseline_sha": self.baseline_sha,
            "fixture_sha": self.fixture_sha,
        })


@dataclass(frozen=True, slots=True)
class TTFDScore:
    eligible: bool
    result: str
    ttfe: float | None
    ttfh: float | None
    ttcd: float | None
    ttaa: float | None
    tttd: float | None
    diagnostic_actions_to_confirmation: int | None
    authoritative_reads: int
    redundant_reads: int
    stale_evidence_attempts: int
    duplicate_validation_attempts: int
    incorrect_hypotheses: int
    surface_failures_recovered: int
    unnecessary_user_prompts: int
    no_progress_transitions: int
    parent_mission_resumptions: int
    premature_stop: bool
    false_positive: bool
    repository_conformance: str
    native_host_conformance: str
    comparability_class: str | None
    execution_authorized: bool = False
    merge_authorized: bool = False
    closure_authorized: bool = False
    external_write_authorized: bool = False
    side_effects_performed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate_sha(value: str, field: str) -> str:
    value = _text(value, field).lower()
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise EvidenceValidationError(f"{field} must be a 40-character hexadecimal SHA")
    return value


def validate_run(case: TTFDCase, run: TTFDRun) -> None:
    if run.benchmark_version != BENCHMARK_VERSION or run.scorer_version != SCORER_VERSION:
        raise EvidenceValidationError("run benchmark/scorer version mismatch")
    if run.case_id != case.packet.case_id or run.case_version != case.packet.case_version:
        raise EvidenceValidationError("run case identity mismatch")
    if run.packet_fingerprint != case.packet.fingerprint:
        raise EvidenceValidationError("run packet fingerprint mismatch")
    if type(run.run_number) is not int or run.run_number < 1:
        raise EvidenceValidationError("run_number must be positive")
    _items(run.tool_profile, "tool_profile")
    _validate_sha(run.baseline_sha, "baseline_sha")
    _validate_sha(run.fixture_sha, "fixture_sha")
    if type(run.timeline) is not tuple or len(run.timeline) != 6:
        raise EvidenceValidationError("timeline must contain exactly T0 through T5")
    expected = tuple(TraceEvent)
    observed = tuple(point.event for point in run.timeline)
    if observed != expected:
        raise EvidenceValidationError("timeline events must be ordered exactly T0 through T5")
    times = tuple(float(point.monotonic_seconds) for point in run.timeline)
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        raise EvidenceValidationError("timeline monotonic times must not move backwards")
    if type(run.actions) is not tuple or len(run.actions) > MAX_ACTIONS:
        raise EvidenceValidationError("actions must be a bounded tuple")
    if tuple(action.sequence for action in run.actions) != tuple(range(1, len(run.actions) + 1)):
        raise EvidenceValidationError("diagnostic action sequence must be contiguous")
    if any(run.actions[index].monotonic_seconds < run.actions[index - 1].monotonic_seconds for index in range(1, len(run.actions))):
        raise EvidenceValidationError("diagnostic action times must not move backwards")
    if run.actions and (run.actions[0].monotonic_seconds < times[0] or run.actions[-1].monotonic_seconds > times[-1]):
        raise EvidenceValidationError("diagnostic actions must stay inside T0-T5")
    _text(run.discovered_outcome, "discovered_outcome")
    _items(run.contamination_reasons, "contamination_reasons")
    if run.contaminated != bool(run.contamination_reasons):
        raise EvidenceValidationError("contamination flag and reasons must agree")
    if run.case_id in NATIVE_CANARY_CASES:
        if run.native_canary is None:
            if run.native_host_conformance is not ConformanceResult.INCOMPLETE:
                raise EvidenceValidationError("D01/D02 without live canary evidence must be integration-evidence-incomplete")
        elif run.native_host_conformance is ConformanceResult.NOT_APPLICABLE:
            raise EvidenceValidationError("D01/D02 live canary requires native-host conformance result")
    elif run.native_canary is not None or run.native_host_conformance is not ConformanceResult.NOT_APPLICABLE:
        raise EvidenceValidationError("native canary evidence is reserved for D01/D02")


def _duration(points: dict[TraceEvent, float], event: TraceEvent) -> float:
    return points[event] - points[TraceEvent.T0_MISSION_RECEIVED]


def score_run(case: TTFDCase, run: TTFDRun) -> TTFDScore:
    validate_run(case, run)
    counts = {kind: 0 for kind in ActionKind}
    for action in run.actions:
        counts[action.kind] += 1
    points = {point.event: float(point.monotonic_seconds) for point in run.timeline}
    t3_time = points[TraceEvent.T3_DEFECT_CONFIRMED]
    actions_to_t3 = sum(1 for action in run.actions if action.monotonic_seconds <= t3_time)
    premature_stop = (
        run.case_id in NATIVE_CANARY_CASES
        and run.native_canary is not None
        and run.native_canary.genuine_terminal_blocker is False
        and run.native_canary.next_admitted_operation_executed is False
    )
    eligible = not run.contaminated
    comparability = run.native_canary.comparability_class.value if run.native_canary else None
    if run.case_id in NATIVE_CANARY_CASES and run.native_host_conformance is ConformanceResult.INCOMPLETE:
        result = ConformanceResult.INCOMPLETE.value
    elif run.false_positive or not run.classification_correct or not run.owner_next_action_correct:
        result = ConformanceResult.FAIL.value
    elif run.repository_conformance is ConformanceResult.FAIL or run.native_host_conformance is ConformanceResult.FAIL or premature_stop:
        result = ConformanceResult.FAIL.value
    elif not eligible:
        result = "ineligible"
    else:
        result = ConformanceResult.PASS.value
    return TTFDScore(
        eligible=eligible,
        result=result,
        ttfe=_duration(points, TraceEvent.T1_AUTHORITATIVE_READ),
        ttfh=_duration(points, TraceEvent.T2_CORRECT_HYPOTHESIS),
        ttcd=_duration(points, TraceEvent.T3_DEFECT_CONFIRMED),
        ttaa=_duration(points, TraceEvent.T4_OWNER_ACTION_IDENTIFIED),
        tttd=_duration(points, TraceEvent.T5_TERMINAL_DISPOSITION),
        diagnostic_actions_to_confirmation=actions_to_t3,
        authoritative_reads=counts[ActionKind.AUTHORITATIVE_READ],
        redundant_reads=counts[ActionKind.REDUNDANT_READ],
        stale_evidence_attempts=counts[ActionKind.STALE_EVIDENCE],
        duplicate_validation_attempts=counts[ActionKind.DUPLICATE_VALIDATION],
        incorrect_hypotheses=counts[ActionKind.INCORRECT_HYPOTHESIS],
        surface_failures_recovered=min(counts[ActionKind.SURFACE_FAILURE], counts[ActionKind.ALTERNATE_ROUTE]),
        unnecessary_user_prompts=counts[ActionKind.USER_PROMPT],
        no_progress_transitions=counts[ActionKind.NO_PROGRESS],
        parent_mission_resumptions=counts[ActionKind.PARENT_RESUMPTION],
        premature_stop=premature_stop,
        false_positive=run.false_positive,
        repository_conformance=run.repository_conformance.value,
        native_host_conformance=run.native_host_conformance.value,
        comparability_class=comparability,
    )
