"""Bounded, deterministic, supplied-evidence-only documentation metrics."""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import json
from typing import Mapping, Sequence

from .issue_scanner import IssueScanResult, IssueStateFilter, RetrievalFinding
from .models import AcceptanceReport
from .parse_issue import project_issue_metadata, scan_issue_metadata
from .path_contract import DeclaredPathError, normalize_declared_pattern

CONTRACT_ID = "agent-os-documentation-metrics/v1"
MAX_RECORDS = 500
MAX_OUTPUT_BYTES = 65_536
MAX_REPOSITORY_LENGTH = 200
MAX_IDENTITY_LENGTH = 128
IJSON_MAX_INTEGER = 9_007_199_254_740_991
_RECOGNIZED_DECISIONS = frozenset(
    {"docs-required", "docs-not-required", "docs-needs-decision"}
)
_COVERAGE_STATES = ("pass", "warn", "fail", "manual-review", "missing")
_INCOMPLETE_CODES = frozenset(
    {
        "source-partial",
        "source-inaccessible",
        "source-stale",
        "source-unsupported",
        "pagination-unknown",
        "source-state-mismatch",
        "metadata-duplicated-identical",
        "metadata-conflicting",
    }
)
_DISCLAIMER = (
    "Path coverage does not prove semantic correctness, relevance, sufficiency, "
    "quality, or canonical ownership."
)


@dataclass(frozen=True, slots=True)
class ExactRate:
    numerator: int
    denominator: int
    observation_count: int
    basis_points: int | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CountEntry:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class ObservationIdentity:
    repository: str
    requested_state: str
    window_identity: str
    retrieved_at: str
    evaluator_revision: str
    supported_schema_versions: tuple[str, ...]
    source_fingerprint: str
    record_identities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentationMetricRecord:
    issue_number: int
    decision: str
    required_docs: tuple[str, ...]
    coverage_status: str
    advisory_markers: tuple[str, ...]
    source_revision: str
    source_reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DocumentationObservation:
    identity: ObservationIdentity
    records: tuple[DocumentationMetricRecord, ...]
    retrieval_distribution: tuple[CountEntry, ...]
    complete: bool
    execution_authorized: bool = False
    side_effects_performed: bool = False
    contract_id: str = CONTRACT_ID


@dataclass(frozen=True, slots=True)
class DocumentationMetrics:
    documentation_decision_coverage: ExactRate
    required_documentation_declaration_coverage: ExactRate
    changed_file_coverage_distribution: tuple[CountEntry, ...]
    advisory_review_burden: tuple[CountEntry, ...]
    retrieval_completeness_distribution: tuple[CountEntry, ...]
    operator_review_demand_counts: tuple[CountEntry, ...]


@dataclass(frozen=True, slots=True)
class DocumentationDrift:
    comparison_state: str
    reason_codes: tuple[str, ...]
    documentation_decision_drift: tuple[CountEntry, ...]
    required_documentation_path_set_drift: tuple[CountEntry, ...]


@dataclass(frozen=True, slots=True)
class DocumentationMetricsReport:
    observation: DocumentationObservation
    metrics: DocumentationMetrics
    drift: DocumentationDrift | None = None
    complete: bool = True
    execution_authorized: bool = False
    side_effects_performed: bool = False
    contract_id: str = CONTRACT_ID


def build_documentation_observation(
    scan_result: IssueScanResult,
    acceptance_reports: Mapping[int, AcceptanceReport],
    *,
    repository: str,
    evaluator_revision: str,
    window_identity: str,
    source_fingerprint: str,
    supported_schema_versions: Sequence[str],
) -> DocumentationObservation:
    """Project supplied canonical evidence into one immutable bounded observation."""
    if not isinstance(scan_result, IssueScanResult):
        raise TypeError("scan_result must be an IssueScanResult")
    if len(scan_result.records) > MAX_RECORDS:
        raise ValueError("issue record limit exceeded")
    if len(acceptance_reports) > MAX_RECORDS:
        raise ValueError("acceptance report limit exceeded")
    if scan_result.retrieved_at is None:
        raise ValueError("retrieved_at is required")

    repository = _bounded_text(repository, "repository", MAX_REPOSITORY_LENGTH)
    evaluator_revision = _identity_text(evaluator_revision, "evaluator_revision")
    window_identity = _identity_text(window_identity, "window_identity")
    source_fingerprint = _identity_text(source_fingerprint, "source_fingerprint")
    schemas = tuple(
        sorted(
            {
                _identity_text(value, "supported_schema_version")
                for value in supported_schema_versions
            }
        )
    )
    if not schemas:
        raise ValueError("supported_schema_versions must not be empty")

    rows: list[DocumentationMetricRecord] = []
    retrieval_codes = [finding.value for finding in scan_result.findings]
    source_complete = scan_result.complete
    for source_record in scan_result.records:
        report = acceptance_reports.get(source_record.issue_number)
        if report is not None and not isinstance(report, AcceptanceReport):
            raise TypeError("acceptance_reports values must be AcceptanceReport values")
        metadata = project_issue_metadata(
            scan_issue_metadata(
                source_record.body,
                source_locator=f"github:{repository}#{source_record.issue_number}",
                source_revision=source_record.source_revision,
                retrieval_complete=scan_result.complete,
                pagination_complete=(
                    RetrievalFinding.PAGE_MISSING_NEXT not in scan_result.findings
                ),
                accessible=RetrievalFinding.API_ERROR not in scan_result.findings,
                expected_revision=source_record.source_revision,
            )
        )
        source_codes = set(_metadata_reason_codes(metadata.manual_review))
        required_docs, path_invalid = _normalized_required_docs(metadata.required_docs)
        if path_invalid:
            source_codes.add("required-doc-invalid")
        incomplete_codes = source_codes & _INCOMPLETE_CODES
        if incomplete_codes:
            source_complete = False
            retrieval_codes.extend(sorted(incomplete_codes))
        rows.append(
            DocumentationMetricRecord(
                issue_number=_bounded_integer(source_record.issue_number, "issue_number"),
                decision=_decision_state(metadata.documentation_impact, tuple(source_codes)),
                required_docs=required_docs,
                coverage_status=_required_docs_status(report),
                advisory_markers=_advisory_markers(report),
                source_revision=_identity_text(
                    source_record.source_revision, "source_revision"
                ),
                source_reason_codes=tuple(sorted(source_codes)),
            )
        )

    records = tuple(sorted(rows, key=lambda item: item.issue_number))
    identity = ObservationIdentity(
        repository=repository,
        requested_state=_requested_state(scan_result.requested_state),
        window_identity=window_identity,
        retrieved_at=_identity_text(scan_result.retrieved_at, "retrieved_at"),
        evaluator_revision=evaluator_revision,
        supported_schema_versions=schemas,
        source_fingerprint=source_fingerprint,
        record_identities=tuple(
            f"{row.issue_number}:{row.source_revision}" for row in records
        ),
    )
    return DocumentationObservation(
        identity=identity,
        records=records,
        retrieval_distribution=_count_entries(retrieval_codes),
        complete=source_complete,
    )


def build_documentation_metrics_report(
    current: DocumentationObservation,
    *,
    previous: DocumentationObservation | None = None,
) -> DocumentationMetricsReport:
    if not isinstance(current, DocumentationObservation):
        raise TypeError("current must be a DocumentationObservation")
    drift = compare_documentation_observations(previous, current) if previous else None
    return DocumentationMetricsReport(
        observation=current,
        metrics=_metrics(current),
        drift=drift,
        complete=current.complete
        and (drift is None or drift.comparison_state == "comparable"),
    )


def compare_documentation_observations(
    previous: DocumentationObservation,
    current: DocumentationObservation,
) -> DocumentationDrift:
    if not isinstance(previous, DocumentationObservation) or not isinstance(
        current, DocumentationObservation
    ):
        raise TypeError("previous and current must be DocumentationObservation values")
    if previous.identity == current.identity:
        raise ValueError("the same observation cannot be compared with itself")
    mismatches = _comparison_mismatches(previous, current)
    if mismatches:
        incomparable = _count_entries(("incomparable",))
        return DocumentationDrift(
            comparison_state="incomparable",
            reason_codes=tuple(mismatches),
            documentation_decision_drift=incomparable,
            required_documentation_path_set_drift=incomparable,
        )

    old = {row.issue_number: row for row in previous.records}
    new = {row.issue_number: row for row in current.records}
    decisions: list[str] = []
    paths: list[str] = []
    for number in sorted(set(old) | set(new)):
        before = old.get(number)
        after = new.get(number)
        if before is None:
            decisions.append("added")
            paths.append("additions-only")
            continue
        if after is None:
            decisions.append("removed")
            paths.append("removals-only")
            continue
        decisions.append("unchanged" if before.decision == after.decision else "changed")
        added = set(after.required_docs) - set(before.required_docs)
        removed = set(before.required_docs) - set(after.required_docs)
        if not added and not removed:
            paths.append("unchanged")
        elif added and removed:
            paths.append("mixed-change")
        elif added:
            paths.append("additions-only")
        else:
            paths.append("removals-only")
    return DocumentationDrift(
        comparison_state="comparable",
        reason_codes=(),
        documentation_decision_drift=_count_entries(decisions),
        required_documentation_path_set_drift=_count_entries(paths),
    )


def render_documentation_metrics_json(report: DocumentationMetricsReport) -> str:
    if not isinstance(report, DocumentationMetricsReport):
        raise TypeError("report must be a DocumentationMetricsReport")
    return _encode_canonical(report).decode("utf-8")


def render_documentation_metrics_text(report: DocumentationMetricsReport) -> str:
    if not isinstance(report, DocumentationMetricsReport):
        raise TypeError("report must be a DocumentationMetricsReport")
    identity = report.observation.identity
    lines = [
        "Documentation coverage and drift metrics",
        f"contract_id: {report.contract_id}",
        f"repository: {identity.repository}",
        f"requested_state: {identity.requested_state}",
        f"window_identity: {identity.window_identity}",
        f"retrieved_at: {identity.retrieved_at}",
        f"evaluator_revision: {identity.evaluator_revision}",
        f"complete: {str(report.complete).lower()}",
        "execution_authorized: false",
        "side_effects_performed: false",
        _DISCLAIMER,
        "metrics_json: "
        + json.dumps(_primitive(report.metrics), sort_keys=True, separators=(",", ":")),
    ]
    if report.drift is not None:
        lines.append(
            "drift_json: "
            + json.dumps(_primitive(report.drift), sort_keys=True, separators=(",", ":"))
        )
    encoded = ("\n".join(lines) + "\n").encode("utf-8", "strict")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ValueError("text output exceeds 65536 UTF-8 bytes")
    return encoded.decode("utf-8")


def _metrics(observation: DocumentationObservation) -> DocumentationMetrics:
    records = observation.records
    recognized = sum(row.decision in _RECOGNIZED_DECISIONS for row in records)
    required = [row for row in records if row.decision == "docs-required"]
    advisory_records = sum(bool(row.advisory_markers) for row in records)
    return DocumentationMetrics(
        documentation_decision_coverage=_rate(recognized, len(records)),
        required_documentation_declaration_coverage=_rate(
            sum(bool(row.required_docs) for row in required), len(required)
        ),
        changed_file_coverage_distribution=_count_entries(
            [row.coverage_status for row in required], names=_COVERAGE_STATES
        ),
        advisory_review_burden=(
            CountEntry("records-with-advisory", advisory_records),
            CountEntry(
                "advisory-marker-count",
                sum(len(row.advisory_markers) for row in records),
            ),
        ),
        retrieval_completeness_distribution=observation.retrieval_distribution,
        operator_review_demand_counts=(
            CountEntry(
                "decision-review",
                sum(
                    row.decision not in {"docs-required", "docs-not-required"}
                    for row in records
                ),
            ),
            CountEntry(
                "coverage-review",
                sum(
                    row.coverage_status in {"manual-review", "missing"}
                    for row in required
                ),
            ),
            CountEntry("advisory-review", advisory_records),
            CountEntry("incomplete-source", 0 if observation.complete else 1),
        ),
    )


def _rate(numerator: int, denominator: int) -> ExactRate:
    numerator = _bounded_integer(numerator, "numerator", allow_zero=True)
    denominator = _bounded_integer(denominator, "denominator", allow_zero=True)
    if numerator > denominator:
        raise ValueError("numerator cannot exceed denominator")
    if denominator == 0:
        return ExactRate(0, 0, 0, None, ("denominator-empty",))
    return ExactRate(
        numerator=numerator,
        denominator=denominator,
        observation_count=denominator,
        basis_points=(numerator * 10_000) // denominator,
        reasons=("limited-observations",) if denominator < 30 else (),
    )


def _required_docs_status(report: AcceptanceReport | None) -> str:
    if report is None:
        return "missing"
    matches = [check for check in report.checks if check.name == "required docs"]
    if len(matches) != 1:
        return "missing"
    status = matches[0].status.value
    return status if status in _COVERAGE_STATES else "missing"


def _advisory_markers(report: AcceptanceReport | None) -> tuple[str, ...]:
    if report is None:
        return ()
    allowed = {
        "documentation_advisory=present",
        "ownership_verification=human-review-required",
        "semantic_relevance_verification=human-review-required",
        "authorization=advisory-only-not-readiness-write-or-merge",
    }
    return tuple(sorted(set(report.evidence) & allowed))


def _decision_state(value: str | None, reason_codes: Sequence[str]) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if normalized in _RECOGNIZED_DECISIONS:
        return normalized
    codes = set(reason_codes)
    if codes & {"metadata-conflicting", "metadata-duplicated-identical"}:
        return "conflicting"
    if "metadata-malformed" in codes:
        return "malformed"
    if codes & {"source-unsupported", "profile-version-unsupported"}:
        return "unsupported"
    return "missing"


def _normalized_required_docs(values: Sequence[str]) -> tuple[tuple[str, ...], bool]:
    normalized: set[str] = set()
    invalid = False
    for value in values:
        try:
            normalized.add(normalize_declared_pattern(value))
        except DeclaredPathError:
            invalid = True
    return tuple(sorted(normalized)), invalid


def _metadata_reason_codes(values: Sequence[str]) -> set[str]:
    prefix = "issueplan-scanner:"
    return {value[len(prefix) :] for value in values if value.startswith(prefix)}


def _comparison_mismatches(
    previous: DocumentationObservation,
    current: DocumentationObservation,
) -> list[str]:
    checks = (
        ("repository-mismatch", previous.identity.repository, current.identity.repository),
        ("state-mismatch", previous.identity.requested_state, current.identity.requested_state),
        ("window-mismatch", previous.identity.window_identity, current.identity.window_identity),
        (
            "schema-mismatch",
            previous.identity.supported_schema_versions,
            current.identity.supported_schema_versions,
        ),
        (
            "evaluator-mismatch",
            previous.identity.evaluator_revision,
            current.identity.evaluator_revision,
        ),
    )
    reasons = [name for name, before, after in checks if before != after]
    if not previous.complete or not current.complete:
        reasons.append("incomplete-evidence")
    return reasons


def _count_entries(
    values: Sequence[str], *, names: Sequence[str] | None = None
) -> tuple[CountEntry, ...]:
    counts = {name: 0 for name in names or ()}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(CountEntry(name, counts[name]) for name in sorted(counts))


def _requested_state(value: IssueStateFilter) -> str:
    if not isinstance(value, IssueStateFilter):
        raise TypeError("requested_state must be an IssueStateFilter")
    return value.value


def _identity_text(value: object, field: str) -> str:
    return _bounded_text(value, field, MAX_IDENTITY_LENGTH)


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    _reject_surrogates(value, field)
    return value


def _bounded_integer(value: object, field: str, *, allow_zero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum or value > IJSON_MAX_INTEGER:
        raise ValueError(f"{field} is outside the supported integer range")
    return value


def _reject_surrogates(value: str, field: str) -> None:
    try:
        value.encode("utf-8", "strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field} contains an invalid Unicode surrogate") from error


def _primitive(value: object) -> object:
    if is_dataclass(value):
        return {
            field.name: _primitive(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise TypeError("floating-point values are not permitted")
    if isinstance(value, int):
        return _bounded_integer(value, "serialized integer", allow_zero=True)
    if isinstance(value, str):
        _reject_surrogates(value, "serialized string")
        return value
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _encode_canonical(payload: object, *, max_bytes: int = MAX_OUTPUT_BYTES) -> bytes:
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    text = json.dumps(
        _primitive(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    encoded = text.encode("utf-8", "strict")
    if len(encoded) > max_bytes:
        raise ValueError(f"JSON output exceeds {max_bytes} UTF-8 bytes")
    return encoded
