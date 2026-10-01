"""ERG result vocabulary and evidence records (#581 consumes #580).

The result vocabulary is owned by the #580 shared standard
(``01_Shared_Standards/github/external-repository-governance.md``):
``pass``, ``warning``, ``fail``, ``manual-review``, ``infrastructure-error``.
Results are evidence only; every report states that it authorizes nothing.

``infrastructure-error`` means trusted validation evidence could not be
produced. It is never converted to ``pass``, ``warning``, or ``fail``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErgVerdict(str, Enum):
    """Canonical ERG result vocabulary, verbatim from the #580 standard."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    MANUAL_REVIEW = "manual-review"
    INFRASTRUCTURE_ERROR = "infrastructure-error"


_VERDICT_RANK = {
    ErgVerdict.PASS: 0,
    ErgVerdict.WARNING: 1,
    ErgVerdict.MANUAL_REVIEW: 2,
    ErgVerdict.FAIL: 3,
}


@dataclass(frozen=True)
class ErgCheck:
    """One evaluated ERG control with its verdict and evidence."""

    name: str
    verdict: ErgVerdict
    detail: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ErgValidationReport:
    """Evidence-only ERG validation report. Authorizes nothing."""

    subject: str
    document_kind: str | None
    contract_version: str | None
    verdict: ErgVerdict
    checks: tuple[ErgCheck, ...] = ()
    evaluated: tuple[str, ...] = ()
    not_evaluated: tuple[str, ...] = ()

    AUTHORIZES = "nothing"

    def to_dict(self) -> dict[str, Any]:
        """Plain JSON-serializable evidence record (stdlib ``json`` at the boundary)."""
        return {
            "subject": self.subject,
            "document_kind": self.document_kind,
            "contract_version": self.contract_version,
            "verdict": self.verdict.value,
            "authorizes": self.AUTHORIZES,
            "checks": [
                {
                    "name": check.name,
                    "verdict": check.verdict.value,
                    "detail": check.detail,
                    "evidence": list(check.evidence),
                }
                for check in self.checks
            ],
            "evaluated": list(self.evaluated),
            "not_evaluated": list(self.not_evaluated),
        }


def combine_verdicts(checks: tuple[ErgCheck, ...]) -> ErgVerdict:
    """Overall verdict: ``infrastructure-error`` wins and never converts;
    otherwise the strongest policy verdict wins. Deterministic."""
    if not checks:
        return ErgVerdict.MANUAL_REVIEW
    if any(check.verdict is ErgVerdict.INFRASTRUCTURE_ERROR for check in checks):
        return ErgVerdict.INFRASTRUCTURE_ERROR
    return max((check.verdict for check in checks), key=lambda v: _VERDICT_RANK[v])


def report_from_checks(
    *,
    subject: str,
    document_kind: str | None,
    contract_version: str | None,
    checks: list[ErgCheck],
    evaluated: tuple[str, ...],
    not_evaluated: tuple[str, ...],
) -> ErgValidationReport:
    frozen = tuple(checks)
    return ErgValidationReport(
        subject=subject,
        document_kind=document_kind,
        contract_version=contract_version,
        verdict=combine_verdicts(frozen),
        checks=frozen,
        evaluated=evaluated,
        not_evaluated=not_evaluated,
    )
