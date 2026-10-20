"""Criterion-level satisfaction projection for issue acceptance (#3678).

Pure and deterministic. This module maps one issue's original acceptance
criteria to evidence gathered across all linked pull requests and gives every
criterion exactly one disposition:

    satisfied | unsatisfied | stale | missing | contradicted | manual-review

Each disposition carries traceable evidence pointers or an explicit
missing-evidence reason. An issue reports complete satisfaction only when
every criterion holds current, uncontradicted, criterion-level evidence.

Satisfaction is evidence, never an admission. Merge state, CI success, and
PR review success are recorded as ``pr-signal`` evidence and can never
satisfy a criterion on their own; only a per-criterion verdict record
(``criterion-verdict``) bound to the exact issue-body version and to the
authoritative PR head can. Missing, stale, contradicted, or unresolved
criteria always prevent complete satisfaction.

The projection is report-only. ``attach_satisfaction_evidence`` registers it
through the existing informational channel
(``AcceptanceReport.informational_checks``, the #3282 / RC5B contract): the
channel is never read by the report's overall status, blockers, or
``exit_code_for``, so existing acceptance behavior is unchanged.

This module performs no GitHub, network, filesystem, subprocess, or provider
I/O; executes no work; mutates no lifecycle state; and creates no authority.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from enum import Enum

from .criterion_preservation import parse_acceptance_criteria
from .models import AcceptanceReport, CheckResult, Status

__all__ = [
    "CriterionDisposition",
    "CriterionEvidence",
    "CriterionSatisfactionStatus",
    "Disposition",
    "PrLineageEntry",
    "SatisfactionProjection",
    "attach_satisfaction_evidence",
    "issue_body_digest",
    "project_criterion_satisfaction",
    "satisfaction_informational_checks",
]

#: Fixed authority boundary line attached to every informational check, in
#: the style of the reuse-evidence channel: satisfaction output is evidence
#: for independent QA judgment, never an admission of any kind.
_AUTHORIZATION_LINE = (
    "authorization=informational-only-not-readiness-merge-closure-or-any-admission"
)

_CRITERIA_HEADING_RE = re.compile(
    r"^##[ \t]+Acceptance criteria[ \t]*$", re.IGNORECASE | re.MULTILINE
)
_NEXT_HEADING_RE = re.compile(r"^##[ \t]+", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^[ \t]*- \[[ xX]\][ \t]+(.*?)[ \t]*$")


class Disposition(str, Enum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    STALE = "stale"
    MISSING = "missing"
    CONTRADICTED = "contradicted"
    MANUAL_REVIEW = "manual-review"


class CriterionSatisfactionStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    MANUAL_REVIEW = "manual-review"


#: PR lineage states. ``head_sha`` on a lineage entry is the authoritative
#: head for that PR: the final merged head for a merged PR, the current head
#: for an open PR.
_PR_STATES = ("merged", "open-primary", "open-non-primary", "closed")

#: Evidence kinds. Only ``criterion-verdict`` records can satisfy a
#: criterion; ``pr-signal`` records (merge state, CI, review outcomes) are
#: preserved as context and never count as criterion evidence.
_EVIDENCE_KINDS = ("criterion-verdict", "pr-signal")
_VERDICTS = ("supports", "contradicts")


def issue_body_digest(issue_body: str) -> str:
    """Return the version digest evidence is bound to: sha256 of the body."""
    return hashlib.sha256((issue_body or "").encode("utf-8")).hexdigest()


def _criterion_identity(index: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"criterion-{index}-{digest[:12]}"


@dataclass(frozen=True, slots=True)
class PrLineageEntry:
    """Authoritative lineage fact for one linked pull request."""

    pr_number: int
    state: str  # one of _PR_STATES
    head_sha: str  # final merged head, or current head for an open PR

    def __post_init__(self) -> None:
        if self.pr_number < 1:
            raise ValueError("pr_number must be positive")
        if self.state not in _PR_STATES:
            raise ValueError(f"unknown PR lineage state: {self.state!r}")
        if not self.head_sha:
            raise ValueError("head_sha must not be empty")


@dataclass(frozen=True, slots=True)
class CriterionEvidence:
    """One evidence record offered for one criterion.

    ``source`` is the traceable pointer a reviewer can follow (for example
    ``pr:3681@bd99dcb5/qa-verdict``). ``issue_body_digest`` binds the record
    to the exact issue-body version it was produced against.
    """

    criterion_index: int
    kind: str  # one of _EVIDENCE_KINDS
    source: str
    issue_body_digest: str
    verdict: str | None = None  # one of _VERDICTS for criterion-verdict records
    pr_number: int | None = None
    pr_head_sha: str | None = None

    def __post_init__(self) -> None:
        if self.criterion_index < 1:
            raise ValueError("criterion_index must be 1-based")
        if self.kind not in _EVIDENCE_KINDS:
            raise ValueError(f"unknown evidence kind: {self.kind!r}")
        if self.kind == "criterion-verdict" and self.verdict not in _VERDICTS:
            raise ValueError("criterion-verdict evidence requires a supports/contradicts verdict")
        if self.kind == "pr-signal" and self.verdict is not None:
            raise ValueError("pr-signal evidence carries no criterion verdict")
        if not self.source:
            raise ValueError("source must not be empty")
        if not self.issue_body_digest:
            raise ValueError("issue_body_digest must not be empty")

    def _dedupe_key(self) -> tuple[object, ...]:
        return (
            self.criterion_index,
            self.kind,
            self.verdict,
            self.pr_number,
            self.pr_head_sha,
            self.issue_body_digest,
            self.source,
        )


@dataclass(frozen=True, slots=True)
class CriterionDisposition:
    """The single disposition assigned to one original criterion."""

    index: int
    identity: str
    text: str
    disposition: Disposition
    reason_code: str
    evidence: tuple[str, ...]  # traceable pointers, or the missing-evidence reason

    @property
    def satisfied(self) -> bool:
        return self.disposition is Disposition.SATISFIED


@dataclass(frozen=True, slots=True)
class SatisfactionProjection:
    """Report-only satisfaction projection for one issue body."""

    issue_body_digest: str
    criteria: tuple[CriterionDisposition, ...]
    status: CriterionSatisfactionStatus
    notes: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status is CriterionSatisfactionStatus.COMPLETE

    @property
    def unsatisfied_criteria(self) -> tuple[CriterionDisposition, ...]:
        """Every criterion that does not hold satisfied (named, never hidden)."""
        return tuple(c for c in self.criteria if not c.satisfied)


@dataclass(frozen=True, slots=True)
class _ParsedCriterion:
    index: int
    identity: str
    text: str
    parsable: bool


def _parse_criteria(issue_body: str) -> tuple[_ParsedCriterion, ...] | None:
    """Parse criterion-like lines of the ``## Acceptance criteria`` section.

    Returns None when the section is absent. Checkbox lines are canonical
    criteria (byte-identical in index, text, and identity to
    ``criterion_preservation.parse_acceptance_criteria`` on a purely
    canonical section). Any other non-empty line is an affected criterion
    that cannot be parsed canonically and is carried as unparsable, so it
    can be dispositioned manual-review instead of silently dropped.
    """
    body = issue_body or ""
    heading = _CRITERIA_HEADING_RE.search(body)
    if heading is None:
        return None
    section = body[heading.end() :]
    following = _NEXT_HEADING_RE.search(section)
    if following is not None:
        section = section[: following.start()]
    parsed: list[_ParsedCriterion] = []
    for line in section.splitlines():
        if not line.strip():
            continue
        match = _CHECKBOX_RE.match(line)
        index = len(parsed) + 1
        if match is not None:
            text = match.group(1)
            parsed.append(_ParsedCriterion(index, _criterion_identity(index, text), text, True))
        else:
            text = line.strip()
            parsed.append(
                _ParsedCriterion(index, _criterion_identity(index, text), text, False)
            )
    return tuple(parsed)


def _stale_reason(item: CriterionEvidence, lineage: dict[int, PrLineageEntry], body_digest: str) -> str | None:
    """Return the staleness reason code for one verdict record, or None if current."""
    if item.issue_body_digest != body_digest:
        return "stale-issue-body-version"
    entry = lineage.get(item.pr_number) if item.pr_number is not None else None
    if entry is None:
        return "stale-source-unverifiable"
    if entry.state == "open-non-primary":
        return "stale-non-primary-pr"
    if entry.state == "closed":
        return "stale-pr-closed-unmerged"
    if item.pr_head_sha != entry.head_sha:
        return "stale-pr-head"
    return None


_STALE_PRIORITY = (
    "stale-issue-body-version",
    "stale-pr-head",
    "stale-non-primary-pr",
    "stale-pr-closed-unmerged",
    "stale-source-unverifiable",
)


def _disposition_for(
    criterion: _ParsedCriterion,
    items: tuple[CriterionEvidence, ...],
    lineage: dict[int, PrLineageEntry],
    body_digest: str,
) -> CriterionDisposition:
    base = (criterion.index, criterion.identity, criterion.text)
    if not criterion.parsable:
        return CriterionDisposition(
            *base,
            Disposition.MANUAL_REVIEW,
            "criterion-unparsable",
            (f"unparsable_line={criterion.text}",),
        )
    if not items:
        return CriterionDisposition(
            *base, Disposition.MISSING, "evidence-missing", ("missing_reason=evidence-missing",)
        )
    verdicts = tuple(i for i in items if i.kind == "criterion-verdict")
    signals = tuple(i for i in items if i.kind == "pr-signal")
    if not verdicts:
        return CriterionDisposition(
            *base,
            Disposition.MISSING,
            "evidence-missing-criterion-verdict",
            (
                "missing_reason=no-criterion-verdict-evidence",
                *(f"pr_signal_not_criterion_evidence={i.source}" for i in signals),
            ),
        )
    current_supports: list[CriterionEvidence] = []
    current_contradicts: list[CriterionEvidence] = []
    stale: list[tuple[CriterionEvidence, str]] = []
    for item in verdicts:
        reason = _stale_reason(item, lineage, body_digest)
        if reason is not None:
            stale.append((item, reason))
        elif item.verdict == "supports":
            current_supports.append(item)
        else:
            current_contradicts.append(item)
    if current_supports and current_contradicts:
        return CriterionDisposition(
            *base,
            Disposition.CONTRADICTED,
            "evidence-contradicted",
            (
                *(f"supports={i.source}" for i in current_supports),
                *(f"contradicts={i.source}" for i in current_contradicts),
            ),
        )
    if current_supports:
        return CriterionDisposition(
            *base,
            Disposition.SATISFIED,
            "criterion-satisfied",
            tuple(f"evidence={i.source}" for i in current_supports),
        )
    if current_contradicts:
        return CriterionDisposition(
            *base,
            Disposition.UNSATISFIED,
            "criterion-reported-unsatisfied",
            tuple(f"contradicting_evidence={i.source}" for i in current_contradicts),
        )
    reasons = sorted({reason for _, reason in stale}, key=_STALE_PRIORITY.index)
    return CriterionDisposition(
        *base,
        Disposition.STALE,
        reasons[0],
        tuple(f"stale_evidence={i.source}; reason={r}" for i, r in stale),
    )


def project_criterion_satisfaction(
    issue_body: str,
    evidence: tuple[CriterionEvidence, ...] | list[CriterionEvidence] = (),
    lineage: tuple[PrLineageEntry, ...] | list[PrLineageEntry] = (),
) -> SatisfactionProjection:
    """Project criterion-level satisfaction for one canonical issue body.

    Pure and deterministic: the same body, evidence, and lineage always
    produce the same projection. Evidence is reconciled (deduplicated)
    before any disposition is selected, and evidence is never inferred
    from merge state, CI, or review outcomes.
    """
    body_digest = issue_body_digest(issue_body)
    parsed = _parse_criteria(issue_body)
    if parsed is None:
        return SatisfactionProjection(
            body_digest,
            (),
            CriterionSatisfactionStatus.MANUAL_REVIEW,
            ("criteria-section-missing",),
        )
    if not parsed:
        return SatisfactionProjection(
            body_digest,
            (),
            CriterionSatisfactionStatus.MANUAL_REVIEW,
            ("criteria-section-empty",),
        )

    lineage_map: dict[int, PrLineageEntry] = {}
    for entry in lineage:
        lineage_map[entry.pr_number] = entry
    open_primaries = [e for e in lineage_map.values() if e.state == "open-primary"]

    # Reconcile first: identical records are one record, never two votes.
    deduped: dict[tuple[object, ...], CriterionEvidence] = {}
    for item in evidence:
        deduped.setdefault(item._dedupe_key(), item)
    known_indexes = {c.index for c in parsed}
    notes: list[str] = []
    if any(i.criterion_index not in known_indexes for i in deduped.values()):
        notes.append("evidence-for-unknown-criterion")

    if len(open_primaries) > 1:
        dispositions = tuple(
            CriterionDisposition(
                c.index,
                c.identity,
                c.text,
                Disposition.MANUAL_REVIEW,
                "lineage-multiple-open-primary",
                (
                    "open_primary_prs="
                    + ",".join(str(e.pr_number) for e in sorted(open_primaries, key=lambda e: e.pr_number)),
                ),
            )
            for c in parsed
        )
        return SatisfactionProjection(
            body_digest, dispositions, CriterionSatisfactionStatus.MANUAL_REVIEW, tuple(notes)
        )

    by_index: dict[int, list[CriterionEvidence]] = {}
    for item in deduped.values():
        if item.criterion_index in known_indexes:
            by_index.setdefault(item.criterion_index, []).append(item)
    dispositions = tuple(
        _disposition_for(
            criterion,
            tuple(
                sorted(
                    by_index.get(criterion.index, ()),
                    key=lambda i: (i.source, i.kind, i.verdict or ""),
                )
            ),
            lineage_map,
            body_digest,
        )
        for criterion in parsed
    )
    if all(d.satisfied for d in dispositions):
        status = CriterionSatisfactionStatus.COMPLETE
    elif any(d.disposition is Disposition.MANUAL_REVIEW for d in dispositions):
        status = CriterionSatisfactionStatus.MANUAL_REVIEW
    else:
        status = CriterionSatisfactionStatus.INCOMPLETE
    return SatisfactionProjection(body_digest, dispositions, status, tuple(notes))


def satisfaction_informational_checks(
    projection: SatisfactionProjection,
) -> tuple[CheckResult, ...]:
    """Render one projection as informational Acceptance Report checks."""
    counts: dict[str, int] = {}
    for item in projection.criteria:
        counts[item.disposition.value] = counts.get(item.disposition.value, 0) + 1
    summary = ", ".join(f"{name}={counts[name]}" for name in sorted(counts)) or "criteria=0"
    evidence = [
        f"issue_body_digest={projection.issue_body_digest}",
        f"satisfaction_status={projection.status.value}",
        f"dispositions: {summary}",
    ]
    for item in projection.criteria:
        evidence.append(
            f"criterion={item.identity}; disposition={item.disposition.value}; "
            f"reason={item.reason_code}"
        )
        evidence.extend(f"  {pointer}" for pointer in item.evidence)
    evidence.extend(f"note={note}" for note in projection.notes)
    evidence.append(_AUTHORIZATION_LINE)
    message = (
        "Criterion-level satisfaction is complete: every original criterion "
        "holds current, uncontradicted evidence."
        if projection.complete
        else "Criterion-level satisfaction is not complete; per-criterion "
        "dispositions are recorded as informational evidence for independent "
        "QA judgment."
    )
    return (
        CheckResult(
            "criterion satisfaction (informational)",
            Status.PASS if projection.complete else Status.MANUAL_REVIEW,
            message,
            evidence,
        ),
    )


def attach_satisfaction_evidence(
    report: AcceptanceReport, projection: SatisfactionProjection
) -> AcceptanceReport:
    """Attach the satisfaction projection through the informational channel.

    Mirrors ``reuse_readiness.attach_reuse_evidence``: only
    ``informational_checks`` changes, so the report's overall status,
    blockers, manual-review items, and exit behavior are unchanged. A
    malformed projection degrades to an informational manual-review error
    check with the base report otherwise untouched.
    """
    if not isinstance(projection, SatisfactionProjection):
        info: tuple[CheckResult, ...] = (
            CheckResult(
                "criterion satisfaction (informational)",
                Status.MANUAL_REVIEW,
                "Criterion satisfaction evidence could not be interpreted; "
                "base acceptance result is unchanged.",
                ["error=projection must be a SatisfactionProjection", _AUTHORIZATION_LINE],
            ),
        )
    else:
        info = satisfaction_informational_checks(projection)
    return replace(
        report,
        checks=[replace(x, evidence=list(x.evidence)) for x in report.checks],
        manual_review_items=list(report.manual_review_items),
        evidence=list(report.evidence),
        blockers=list(report.blockers),
        remaining_risks=list(report.remaining_risks),
        informational_checks=tuple(report.informational_checks) + info,
    )
