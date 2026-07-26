"""Summary helpers for Agent Memory handoff packets.

Renders a validated Handoff Packet (schema owned by ``handoff_packet.py`` /
``packet_validation.py``, merged in #265) into a deterministic, safety-complete
text summary plus an explicit rendering-evidence and trust-classification
contract. This module does not redefine packet nullability, compute-limit
vocabulary, cache identity, or Scheduler behavior, and it never touches the
clock, Git, the filesystem, the network, or process/environment state.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .packet_validation import assert_valid_handoff_packet

DEFAULT_SUMMARY_LIST_LIMIT = 3

# Identity constants for this renderer's supported contract. These are
# compared against caller-supplied evidence; they are never inferred from
# the environment, Git, or the packet itself.
SUPPORTED_PACKET_SCHEMA_VERSION = "handoff-packet-v2"
RENDERER_VERSION = "packet-summary-h2"

TRUST_CURRENT = "current"
TRUST_STALE = "stale"
TRUST_UNSUPPORTED = "unsupported"
TRUST_UNVERIFIABLE = "unverifiable"

TRUST_STATES: tuple[str, ...] = (
    TRUST_CURRENT,
    TRUST_STALE,
    TRUST_UNSUPPORTED,
    TRUST_UNVERIFIABLE,
)

# Bounded, stable reason codes. Never derived from exception text or object
# representations, so a reason never leaks arbitrary runtime detail.
REASON_PRODUCER_INVALID = "producer_identity_missing_or_invalid"
REASON_SCHEMA_VERSION_INVALID = "packet_schema_version_missing_or_invalid"
REASON_RENDERER_VERSION_INVALID = "renderer_version_missing_or_invalid"
REASON_PROVENANCE_STATUS_INVALID = "provenance_status_missing_or_invalid"
REASON_PROVENANCE_MISSING = "provenance_evidence_missing"
REASON_PROVENANCE_MALFORMED = "provenance_evidence_malformed"
REASON_PROVENANCE_CONTRADICTORY = "provenance_evidence_contradictory"
REASON_PROVENANCE_DETACHED = "provenance_evidence_detached"
REASON_SCHEMA_VERSION_UNSUPPORTED = "packet_schema_version_unsupported"
REASON_RENDERER_VERSION_UNSUPPORTED = "renderer_version_unsupported"
REASON_SOURCE_FINGERPRINT_MISSING = "source_fingerprint_missing"
REASON_SOURCE_FINGERPRINT_MISMATCH = "source_fingerprint_mismatch"

# Provenance statuses a caller may supply. "supplied" is the only status that
# can ever lead to `current`; every other status fails closed.
_SUPPLIED_PROVENANCE_STATUS = "supplied"
_ALLOWED_PROVENANCE_STATUSES: tuple[str, ...] = (
    _SUPPLIED_PROVENANCE_STATUS,
    "missing",
    "malformed",
    "contradictory",
    "detached",
)
_PROVENANCE_FAIL_REASONS: dict[str, str] = {
    "missing": REASON_PROVENANCE_MISSING,
    "malformed": REASON_PROVENANCE_MALFORMED,
    "contradictory": REASON_PROVENANCE_CONTRADICTORY,
    "detached": REASON_PROVENANCE_DETACHED,
}

NON_AUTHORIZATION_NOTICE = (
    "This summary is context evidence only. It is not implementation "
    "authorization, execution authorization, or merge authorization. It is "
    "not proof that the packet is current unless trust status is 'current'. "
    "It is not a substitute for the canonical GitHub issue, approval "
    "record, or repository state."
)


@dataclass(frozen=True)
class RenderingEvidence:
    """Caller-supplied evidence used to classify summary trust.

    All fields are supplied by the caller; none are derived from the clock,
    Git, the filesystem, the network, or process/environment state.
    """

    producer: str
    packet_schema_version: str
    renderer_version: str
    provenance_status: str
    source_fingerprint: str | None = None

    @classmethod
    def unsupplied(cls) -> "RenderingEvidence":
        """Return the safe default when no evidence is supplied.

        Fails closed to `unverifiable` rather than guessing evidence.
        """
        return cls(
            producer="",
            packet_schema_version="",
            renderer_version="",
            provenance_status="missing",
            source_fingerprint=None,
        )


@dataclass(frozen=True)
class RenderedHandoffSummary:
    """Immutable rendering-evidence result contract for a summary."""

    text: str
    producer: str
    packet_schema_version: str
    renderer_version: str
    source_fingerprint: str
    summary_fingerprint: str
    provenance_status: str
    trust_status: str
    trust_reason: str | None

    def __str__(self) -> str:
        return self.text


def summarize_handoff_packet(
    packet: Mapping[str, Any],
    *,
    list_limit: int = DEFAULT_SUMMARY_LIST_LIMIT,
    evidence: RenderingEvidence | None = None,
) -> RenderedHandoffSummary:
    """Return a deterministic, safety-complete summary for a handoff packet.

    Reuses the merged #265 validator as the sole packet-validity authority.
    """
    assert_valid_handoff_packet(packet)

    if evidence is None:
        evidence = RenderingEvidence.unsupplied()

    limit = max(0, list_limit)
    lines = [
        f"Objective: {packet['objective']}",
        f"Current phase: {packet['current_phase']}",
        f"Branch: {packet['branch']}",
        f"PR number: {packet['pr_number']}",
    ]

    _append_list_section(lines, "Changed files", packet["changed_files"], limit)
    _append_list_section(
        lines,
        "Allowed inspect first",
        packet["allowed_inspect_first"],
        limit,
    )
    _append_list_section(
        lines,
        "Forbidden unless needed",
        packet["forbidden_unless_needed"],
        limit,
    )
    _append_list_section(lines, "Known facts", packet["known_facts"], limit)
    _append_list_section(lines, "Prior decisions", packet["prior_decisions"], limit)
    _append_list_section(
        lines,
        "Acceptance criteria",
        packet["acceptance_criteria"],
        limit,
    )
    _append_list_section(
        lines,
        "Validation commands",
        packet["validation_commands"],
        limit,
    )

    lines.append("Compute limits:")
    for key, value in packet["compute_limits"].items():
        lines.append(f"- {key}: {value}")

    _append_list_section(lines, "Stop conditions", packet["stop_conditions"], limit)

    core_text = "\n".join(lines)

    source_fingerprint = _fingerprint_value(packet)
    summary_fingerprint = _fingerprint_text(core_text)
    trust_status, trust_reason = _classify_trust(evidence, source_fingerprint)

    evidence_lines = [
        "",
        "Rendering evidence:",
        f"- Producer: {_safe_str(evidence.producer)}",
        f"- Packet schema version: {_safe_str(evidence.packet_schema_version)}",
        f"- Renderer version: {_safe_str(evidence.renderer_version)}",
        f"- Source fingerprint: {source_fingerprint}",
        f"- Summary fingerprint: {summary_fingerprint}",
        f"- Provenance status: {evidence.provenance_status}",
        f"- Trust status: {trust_status}",
        f"- Trust reason: {trust_reason if trust_reason is not None else 'none'}",
        "",
        NON_AUTHORIZATION_NOTICE,
    ]

    full_text = core_text + "\n" + "\n".join(evidence_lines)

    return RenderedHandoffSummary(
        text=full_text,
        producer=evidence.producer,
        packet_schema_version=evidence.packet_schema_version,
        renderer_version=evidence.renderer_version,
        source_fingerprint=source_fingerprint,
        summary_fingerprint=summary_fingerprint,
        provenance_status=evidence.provenance_status,
        trust_status=trust_status,
        trust_reason=trust_reason,
    )


def _append_list_section(
    lines: list[str],
    title: str,
    values: Sequence[Any],
    limit: int,
) -> None:
    lines.append(f"{title}:")
    displayed_values = list(values[:limit])
    for value in displayed_values:
        lines.append(f"- {value}")

    remaining = len(values) - len(displayed_values)
    if remaining > 0:
        lines.append(f"...and {remaining} more")


def _classify_trust(
    evidence: RenderingEvidence,
    actual_source_fingerprint: str,
) -> tuple[str, str | None]:
    """Classify trust from supplied evidence alone. Fails closed."""
    if not isinstance(evidence.producer, str) or not evidence.producer.strip():
        return TRUST_UNVERIFIABLE, REASON_PRODUCER_INVALID

    if (
        not isinstance(evidence.packet_schema_version, str)
        or not evidence.packet_schema_version.strip()
    ):
        return TRUST_UNVERIFIABLE, REASON_SCHEMA_VERSION_INVALID

    if (
        not isinstance(evidence.renderer_version, str)
        or not evidence.renderer_version.strip()
    ):
        return TRUST_UNVERIFIABLE, REASON_RENDERER_VERSION_INVALID

    if evidence.provenance_status not in _ALLOWED_PROVENANCE_STATUSES:
        return TRUST_UNVERIFIABLE, REASON_PROVENANCE_STATUS_INVALID

    if evidence.provenance_status != _SUPPLIED_PROVENANCE_STATUS:
        return TRUST_UNVERIFIABLE, _PROVENANCE_FAIL_REASONS[evidence.provenance_status]

    if evidence.packet_schema_version != SUPPORTED_PACKET_SCHEMA_VERSION:
        return TRUST_UNSUPPORTED, REASON_SCHEMA_VERSION_UNSUPPORTED

    if evidence.renderer_version != RENDERER_VERSION:
        return TRUST_UNSUPPORTED, REASON_RENDERER_VERSION_UNSUPPORTED

    if (
        not isinstance(evidence.source_fingerprint, str)
        or not evidence.source_fingerprint.strip()
    ):
        return TRUST_UNVERIFIABLE, REASON_SOURCE_FINGERPRINT_MISSING

    if evidence.source_fingerprint != actual_source_fingerprint:
        return TRUST_STALE, REASON_SOURCE_FINGERPRINT_MISMATCH

    return TRUST_CURRENT, None


def _safe_str(value: Any) -> str:
    """Render a bounded string for evidence display without invoking an
    untrusted `__str__`/`__repr__` on non-string evidence values."""
    return value if isinstance(value, str) else "<invalid>"


def _to_plain(value: Any) -> Any:
    """Recursively convert Mapping/Sequence values into plain JSON types."""
    if isinstance(value, Mapping):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    return value


def _fingerprint_value(value: Any) -> str:
    """Deterministic canonical-UTF-8 SHA-256 fingerprint of a JSON value."""
    canonical = json.dumps(
        _to_plain(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fingerprint_text(text: str) -> str:
    """Deterministic canonical-UTF-8 SHA-256 fingerprint of rendered text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
