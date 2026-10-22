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
issue body's acceptance-criteria section, matching the canonical issue
form. The section heading is accepted at levels 2 and 3, with or without
the attested ``and definition of done`` suffix (the forms carried by
issues #3257 and #3337); no other heading text is recognized. One shared
section walk (``parse_criteria_section``) enumerates every non-empty
section line at its position: checkbox lines are parsable criteria, any
other line is carried as an unparsable entry so it can be reported as
manual-review instead of silently dropped, and never promoted to a
criterion. Identity is the entry's position in that section plus a
digest of its exact text, so any wording change produces a different
identity and fails verification closed, and the preservation and
satisfaction modules assign identical identities to the same line.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

CRITERION_PACKET_SCHEMA_NAME = "agent-os-criterion-preservation-packet"
CRITERION_PACKET_SCHEMA_VERSION = "1.0"

_CRITERIA_HEADING_RE = re.compile(
    r"^#{2,3}[ \t]+Acceptance criteria(?:[ \t]+and definition of done)?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
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


@dataclass(frozen=True, slots=True)
class CriterionSectionEntry:
    """One non-empty line of the acceptance-criteria section, at its position.

    ``parsable`` is True exactly for checkbox lines: those are the canonical
    criteria. Any other non-empty line (free text, a numbered legacy
    requirement, a stray sub-heading) is carried with ``parsable=False`` so
    consumers report it as manual-review instead of silently dropping it;
    it is never a criterion and can never be satisfied as one.
    """

    index: int  # 1-based position among the section's non-empty lines
    text: str  # checkbox text, or the exact stripped line for unparsable lines
    identity: str  # position + digest of the exact text
    parsable: bool


def parse_criteria_section(
    issue_body: str,
) -> tuple[CriterionSectionEntry, ...] | None:
    """Walk the acceptance-criteria section of an issue body, once.

    This is the one section walk shared by this module and
    ``criterion_satisfaction``: both enumerate the same entries, at the
    same positions, with the same identities. Returns None when the body
    has no recognized acceptance-criteria heading (fail-closed: callers
    must treat a missing section as missing evidence, never as an empty
    criterion set). The section runs from the recognized heading to the
    next level-2 heading or the end of the body.
    """
    body = issue_body or ""
    heading = _CRITERIA_HEADING_RE.search(body)
    if heading is None:
        return None
    section = body[heading.end() :]
    following = _NEXT_HEADING_RE.search(section)
    if following is not None:
        section = section[: following.start()]
    entries: list[CriterionSectionEntry] = []
    for line in section.splitlines():
        if not line.strip():
            continue
        match = _CHECKBOX_RE.match(line)
        index = len(entries) + 1
        if match is not None:
            text = match.group(1)
            entries.append(
                CriterionSectionEntry(
                    index=index,
                    text=text,
                    identity=_criterion_identity(index, text),
                    parsable=True,
                )
            )
        else:
            text = line.strip()
            entries.append(
                CriterionSectionEntry(
                    index=index,
                    text=text,
                    identity=_criterion_identity(index, text),
                    parsable=False,
                )
            )
    return tuple(entries)


def parse_acceptance_criteria(issue_body: str) -> tuple[AcceptanceCriterion, ...]:
    """Parse the checkbox criteria of the acceptance-criteria section.

    Derived from the shared section walk (``parse_criteria_section``):
    the criteria are exactly the walk's parsable entries, each keeping
    its section position as its index, so a criterion's identity agrees
    with the identity the satisfaction projection assigns to the same
    line even when unparsable lines sit between criteria. A body without
    the section, or a section without checkbox lines, yields an empty
    tuple (fail-closed: callers must not treat that as preservation of a
    non-empty criterion set).
    """
    entries = parse_criteria_section(issue_body)
    if entries is None:
        return ()
    return tuple(
        AcceptanceCriterion(index=e.index, text=e.text, identity=e.identity)
        for e in entries
        if e.parsable
    )


def build_criterion_packet(issue_body: str) -> dict[str, object]:
    """Build the handoff packet output for one canonical issue body.

    The packet reports every criterion parsed from the body, each with its
    identity preserved, so a downstream handoff or PR can carry the set
    without restating it in fresh prose. Unparsable section lines are not
    dropped: they are reported under ``manual_review_entries`` at their
    section positions, and ``section_entry_count`` counts every entry the
    shared section walk enumerates, so the packet's total always agrees
    with the number of criteria the satisfaction projection dispositions
    for the same body.
    """
    criteria = parse_acceptance_criteria(issue_body)
    entries = parse_criteria_section(issue_body) or ()
    return {
        "schema": CRITERION_PACKET_SCHEMA_NAME,
        "schema_version": CRITERION_PACKET_SCHEMA_VERSION,
        "criterion_count": len(criteria),
        "section_entry_count": len(entries),
        "criteria": [
            {"index": c.index, "identity": c.identity, "text": c.text}
            for c in criteria
        ],
        "manual_review_entries": [
            {
                "index": e.index,
                "identity": e.identity,
                "text": e.text,
                "status": "manual-review",
                "reason_code": "criterion-unparsable",
            }
            for e in entries
            if not e.parsable
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
