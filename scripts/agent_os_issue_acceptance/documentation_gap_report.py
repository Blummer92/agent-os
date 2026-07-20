"""Deterministic report-only documentation-impact gap inventory."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .issue_scanner import IssueScannerRecord
from .models import CheckResult, Status
from .readiness import evaluate_issue_readiness


class DocumentationGapCategory(str, Enum):
    ALREADY_COMPLIANT = "already-compliant"
    BACKFILL_NOW = "backfill-now"
    DEFER_BLOCKED = "defer-blocked"
    MANUAL_OWNER_DECISION = "manual-owner-decision"
    CLEANUP_CANDIDATE = "cleanup-candidate"
    NOT_APPLICABLE = "not-applicable"


@dataclass(frozen=True, slots=True)
class DocumentationGapRow:
    issue_number: int
    category: DocumentationGapCategory
    documentation_impact: str
    reason_codes: tuple[str, ...]
    recommended_action: str
    source_revision: str


@dataclass(frozen=True, slots=True)
class DocumentationGapMetrics:
    open_issue_count: int
    open_implementation_candidate_count: int
    missing_documentation_impact_count: int
    already_compliant_count: int
    manual_review_rate: float
    category_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DocumentationGapReport:
    evaluator_revision: str
    rows: tuple[DocumentationGapRow, ...]
    metrics: DocumentationGapMetrics
    complete: bool = True
    execution_authorized: bool = False
    side_effects_performed: bool = False


_CANDIDATE = frozenset({"type:implementation", "type:tooling", "type:validation", "type:docs", "type:governance"})
_NOT_APPLICABLE = frozenset({"type:roadmap", "type:tracker", "type:discussion"})
_CLEANUP = frozenset({"duplicate", "status:obsolete", "status:superseded"})
_OWNER_HEADINGS = ("owner", "primary owner", "owners", "owner routing")
_SOURCE_HEADINGS = ("source of truth", "owner and source of truth")
_HEADING_RE = re.compile(r"(?im)^#{2,3}\s+(.+?)\s*$")
_CODE_RE = re.compile(r"(?:^|;\s*)code=([a-z0-9-]+)")


def build_documentation_gap_report(records: Iterable[IssueScannerRecord], *, evaluator_revision: str) -> DocumentationGapReport:
    if not evaluator_revision.strip():
        raise ValueError("evaluator_revision is required")
    grouped: dict[int, list[IssueScannerRecord]] = {}
    for record in records:
        if not isinstance(record, IssueScannerRecord):
            raise TypeError("records must contain IssueScannerRecord values")
        if record.state.lower() == "open":
            grouped.setdefault(record.issue_number, []).append(record)
    rows: list[DocumentationGapRow] = []
    for number in sorted(grouped):
        unique = list(dict.fromkeys(grouped[number]))
        if len(unique) > 1:
            latest = max(unique, key=lambda item: (item.source_revision, item.updated_at))
            rows.append(_row(latest, DocumentationGapCategory.MANUAL_OWNER_DECISION, "unknown", ("duplicate-snapshot-conflict",), "Resolve conflicting source snapshots before classification."))
        else:
            rows.append(classify_documentation_gap(unique[0]))
    ordered = tuple(sorted(rows, key=lambda row: (row.category.value, row.issue_number)))
    return DocumentationGapReport(evaluator_revision, ordered, _metrics(ordered))


def classify_documentation_gap(record: IssueScannerRecord) -> DocumentationGapRow:
    labels = frozenset(label.strip().lower() for label in record.labels)
    body = record.body or ""
    check = _documentation_check(body)
    codes = _reason_codes(check)
    impact = _impact_value(check)
    if labels & _NOT_APPLICABLE or _body_has(body, ("this issue is a roadmap only", "this issue is a tracker only", "coordination only; no implementation")):
        return _row(record, DocumentationGapCategory.NOT_APPLICABLE, impact, codes, "No metadata backfill is recommended.")
    if not _is_candidate(labels, body):
        return _row(record, DocumentationGapCategory.NOT_APPLICABLE, impact, codes, "No implementation-candidate evidence is present.")
    if check.status == Status.PASS:
        return _row(record, DocumentationGapCategory.ALREADY_COMPLIANT, impact, codes, "No action is required.")
    if labels & _CLEANUP or _body_has(body, ("this issue is obsolete", "duplicate of #", "superseded by #")):
        return _row(record, DocumentationGapCategory.CLEANUP_CANDIDATE, impact, codes, "Review for closure or supersession; do not mutate automatically.")
    if "status:blocked" in labels:
        return _row(record, DocumentationGapCategory.DEFER_BLOCKED, impact, codes, "Re-evaluate after the recorded blocker clears.")
    if "legacy-metadata-missing" in codes:
        missing = _missing_authority(body)
        if missing:
            return _row(record, DocumentationGapCategory.MANUAL_OWNER_DECISION, impact, tuple(sorted({*codes, *missing})), "Resolve owner and source-of-truth evidence before backfill.")
        return _row(record, DocumentationGapCategory.BACKFILL_NOW, impact, codes, "Add the canonical documentation-impact contract through an authorized issue edit.")
    return _row(record, DocumentationGapCategory.MANUAL_OWNER_DECISION, impact, codes or ("documentation-evidence-review-required",), "Resolve malformed, conflicting, unknown, or incomplete documentation evidence.")


def render_documentation_gap_report_json(report: DocumentationGapReport) -> str:
    return json.dumps(asdict(report), sort_keys=True, separators=(",", ":")) + "\n"


def render_documentation_gap_report_text(report: DocumentationGapReport) -> str:
    metrics = report.metrics
    lines = [
        "Documentation-impact gap report",
        f"evaluator_revision: {report.evaluator_revision}",
        f"open_issue_count: {metrics.open_issue_count}",
        f"open_implementation_candidate_count: {metrics.open_implementation_candidate_count}",
        f"missing_documentation_impact_count: {metrics.missing_documentation_impact_count}",
        f"already_compliant_count: {metrics.already_compliant_count}",
        f"manual_review_rate: {metrics.manual_review_rate:.6f}",
        "rows:",
    ]
    for row in report.rows:
        reasons = ",".join(row.reason_codes) or "none"
        lines.append(f"- issue=#{row.issue_number}; category={row.category.value}; impact={row.documentation_impact}; reasons={reasons}; source_revision={row.source_revision}")
    return "\n".join(lines) + "\n"


def records_from_snapshot(payload: object) -> tuple[IssueScannerRecord, ...]:
    raw = payload.get("issues") if isinstance(payload, Mapping) else payload
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError("snapshot must be a list or an object containing an issues list")
    required = {"issue_number", "title", "state", "body", "labels", "url", "created_at", "updated_at", "source_revision"}
    records: list[IssueScannerRecord] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("each snapshot issue must be an object")
        missing = sorted(required - set(item))
        if missing:
            raise ValueError("snapshot issue missing field(s): " + ", ".join(missing))
        labels = item["labels"]
        if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
            raise ValueError("snapshot labels must be a list")
        records.append(IssueScannerRecord(int(item["issue_number"]), str(item["title"]), str(item["state"]), str(item["body"] or ""), tuple(str(label) for label in labels), str(item["url"]), str(item["created_at"]), str(item["updated_at"]), str(item["source_revision"])))
    return tuple(records)


def _documentation_check(body: str) -> CheckResult:
    matches = [check for check in evaluate_issue_readiness(body).report.checks if check.name == "documentation impact"]
    if len(matches) != 1:
        raise ValueError("canonical readiness result must contain one documentation impact check")
    return matches[0]


def _reason_codes(check: CheckResult) -> tuple[str, ...]:
    return tuple(sorted({match.group(1) for evidence in check.evidence for match in _CODE_RE.finditer(evidence)}))


def _impact_value(check: CheckResult) -> str:
    for evidence in check.evidence:
        if evidence.startswith("impact="):
            return evidence.split("=", 1)[1]
    return "missing" if "legacy-metadata-missing" in _reason_codes(check) else "unknown"


def _row(record: IssueScannerRecord, category: DocumentationGapCategory, impact: str, codes: tuple[str, ...], action: str) -> DocumentationGapRow:
    return DocumentationGapRow(record.issue_number, category, impact, tuple(sorted(set(codes))), action, record.source_revision)


def _headings(body: str) -> set[str]:
    return {" ".join(match.group(1).strip().lower().split()) for match in _HEADING_RE.finditer(body)}


def _is_candidate(labels: frozenset[str], body: str) -> bool:
    headings = _headings(body)
    return bool(labels & _CANDIDATE) or ("objective" in headings and bool({"scope", "acceptance criteria"} & headings))


def _missing_authority(body: str) -> tuple[str, ...]:
    headings = _headings(body)
    missing: list[str] = []
    if not any(value in headings for value in _OWNER_HEADINGS):
        missing.append("owner-evidence-missing")
    if not any(value in headings for value in _SOURCE_HEADINGS):
        missing.append("source-of-truth-evidence-missing")
    return tuple(missing)


def _body_has(body: str, phrases: tuple[str, ...]) -> bool:
    normalized = " ".join(body.lower().split())
    return any(phrase in normalized for phrase in phrases)


def _metrics(rows: tuple[DocumentationGapRow, ...]) -> DocumentationGapMetrics:
    counts = {category.value: 0 for category in DocumentationGapCategory}
    for row in rows:
        counts[row.category.value] += 1
    candidates = [row for row in rows if row.category != DocumentationGapCategory.NOT_APPLICABLE]
    missing = sum(row.documentation_impact == "missing" for row in candidates)
    return DocumentationGapMetrics(len(rows), len(candidates), missing, counts[DocumentationGapCategory.ALREADY_COMPLIANT.value], missing / len(candidates) if candidates else 0.0, tuple(sorted(counts.items())))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evaluator-revision", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    report = build_documentation_gap_report(records_from_snapshot(json.loads(args.input.read_text(encoding="utf-8"))), evaluator_revision=args.evaluator_revision)
    output = render_documentation_gap_report_json(report) if args.format == "json" else render_documentation_gap_report_text(report)
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
