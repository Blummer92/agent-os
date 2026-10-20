"""Criterion-preservation handoff packet for implementation handoffs (#3677).

Pure and deterministic. This module parses the acceptance criteria from a
canonical issue body, carries them in a handoff packet with each criterion's
identity preserved, and verifies a candidate packet against the canonical
criteria. A criterion that is dropped or reworded between the canonical issue
body and the packet is surfaced as a manual-review item for that criterion —
never silently merged, dropped, or restated.

It performs no GitHub, network, filesystem, subprocess, or provider I/O;
executes no work; mutates no lifecycle state; and creates no authority.
Parsing is deliberately narrow: criteria are the checkbox lines of the
issue body's ``## Acceptance criteria`` section, matching the canonical
issue form. Identity is the criterion's position in that section plus a
digest of its exact text, so any wording change produces a different
identity and fails verification closed.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

CRITERION_PACKET_SCHEMA_NAME = "agent-os-criterion-preservation-packet"
CRITERION_PACKET_SCHEMA_VERSION = "1.0"

_CRITERIA_HEADING_RE = re.compile(
    r"^##[ \t]+Acceptance criteria[ \t]*$", re.IGNORECASE | re.MULTILINE
)
_NEXT_HEADING_RE = re.compile(r"^##[ \t]+", re.MULTILINE)
_CHECKBOX_RE = re.compile(r"^[ \t]*- \[[ xX]\][ \t]+(.*?)[ \t]*$")


def _criterion_identity(index: int, text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"criterion-{index}-{digest[:12]}"


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """One acceptance criterion parsed from a canonical issue body."""

    index: int  # 1-based position in the Acceptance criteria section
    text: str  # exact criterion text, checkbox marker stripped
    identity: str  # position + digest of the exact text

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ValueError("criterion index must be 1-based")
        if not self.text:
            raise ValueError("criterion text must not be empty")
        if self.identity != _criterion_identity(self.index, self.text):
            raise ValueError("criterion identity does not match its index and text")


@dataclass(frozen=True, slots=True)
class CriterionVerification:
    """Per-criterion verification outcome against the canonical issue body."""

    index: int
    identity: str
    status: str  # "preserved" | "manual-review"
    reason_code: str  # criterion-preserved | criterion-dropped |
    # criterion-reworded | criterion-identity-mismatch |
    # criterion-not-in-canonical-body


@dataclass(frozen=True, slots=True)
class CriterionPacketVerification:
    """Whole-packet verification outcome."""

    status: str  # "preserved" | "manual-review"
    results: tuple[CriterionVerification, ...]

    @property
    def manual_review_indexes(self) -> tuple[int, ...]:
        return tuple(
            result.index for result in self.results if result.status == "manual-review"
        )


def parse_acceptance_criteria(issue_body: str) -> tuple[AcceptanceCriterion, ...]:
    """Parse the checkbox criteria of the ``## Acceptance criteria`` section.

    Returns the criteria in body order with exact text and identity. A body
    without the section, or a section without checkbox lines, yields an
    empty tuple (fail-closed: callers must not treat that as preservation
    of a non-empty criterion set).
    """
    heading = _CRITERIA_HEADING_RE.search(issue_body or "")
    if heading is None:
        return ()
    section = (issue_body or "")[heading.end() :]
    following = _NEXT_HEADING_RE.search(section)
    if following is not None:
        section = section[: following.start()]
    criteria: list[AcceptanceCriterion] = []
    for line in section.splitlines():
        match = _CHECKBOX_RE.match(line)
        if match is None:
            continue
        text = match.group(1)
        index = len(criteria) + 1
        criteria.append(
            AcceptanceCriterion(
                index=index, text=text, identity=_criterion_identity(index, text)
            )
        )
    return tuple(criteria)


def build_criterion_packet(issue_body: str) -> dict[str, object]:
    """Build the handoff packet output for one canonical issue body.

    The packet reports every criterion parsed from the body, each with its
    identity preserved, so a downstream handoff or PR can carry the set
    without restating it in fresh prose.
    """
    criteria = parse_acceptance_criteria(issue_body)
    return {
        "schema": CRITERION_PACKET_SCHEMA_NAME,
        "schema_version": CRITERION_PACKET_SCHEMA_VERSION,
        "criterion_count": len(criteria),
        "criteria": [
            {"index": c.index, "identity": c.identity, "text": c.text}
            for c in criteria
        ],
    }


def verify_criterion_packet(
    canonical_issue_body: str, packet: dict[str, object]
) -> CriterionPacketVerification:
    """Verify a handoff packet against the canonical issue body.

    Every canonical criterion must appear in the packet at the same index
    with byte-identical text. A missing index is a dropped criterion; the
    same index with different text is a reworded criterion; a packet entry
    with no canonical counterpart is unrecognized. Each is reported as a
    manual-review item for that criterion; only an exact full match is
    ``preserved``.
    """
    canonical = parse_acceptance_criteria(canonical_issue_body)
    entries = packet.get("criteria") if isinstance(packet, dict) else None
    packet_by_index: dict[int, dict[str, object]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("index"), int):
                packet_by_index[entry["index"]] = entry

    results: list[CriterionVerification] = []
    for criterion in canonical:
        entry = packet_by_index.get(criterion.index)
        if entry is None:
            results.append(
                CriterionVerification(
                    index=criterion.index,
                    identity=criterion.identity,
                    status="manual-review",
                    reason_code="criterion-dropped",
                )
            )
        elif entry.get("text") != criterion.text:
            results.append(
                CriterionVerification(
                    index=criterion.index,
                    identity=criterion.identity,
                    status="manual-review",
                    reason_code="criterion-reworded",
                )
            )
        elif entry.get("identity") != criterion.identity:
            results.append(
                CriterionVerification(
                    index=criterion.index,
                    identity=criterion.identity,
                    status="manual-review",
                    reason_code="criterion-identity-mismatch",
                )
            )
        else:
            results.append(
                CriterionVerification(
                    index=criterion.index,
                    identity=criterion.identity,
                    status="preserved",
                    reason_code="criterion-preserved",
                )
            )
    canonical_indexes = {c.index for c in canonical}
    for index in sorted(set(packet_by_index) - canonical_indexes):
        entry = packet_by_index[index]
        results.append(
            CriterionVerification(
                index=index,
                identity=str(entry.get("identity") or ""),
                status="manual-review",
                reason_code="criterion-not-in-canonical-body",
            )
        )
    status = (
        "preserved"
        if results and all(r.status == "preserved" for r in results)
        else "manual-review"
    )
    return CriterionPacketVerification(status=status, results=tuple(results))
