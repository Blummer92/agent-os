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
MAX_SUMMARY_LIST_LIMIT = 25
MAX_DISPLAY_VALUE_CHARS = 256
MAX_COMPUTE_LIMIT_ENTRIES = 25

# Authorized renderer resource-limit contract.
MAX_LIST_ENTRIES_PER_FIELD = 500
MAX_TOTAL_LIST_ENTRIES = 2_000
MAX_DICT_ENTRIES_PER_FIELD = 300
MAX_TOTAL_DICT_ENTRIES = 1_500
MAX_STRING_CHARS = 10_000
MAX_TOTAL_STRING_BYTES = 50_000
MAX_CANONICAL_NODES = 5_000
MAX_CANONICAL_DEPTH = 20
MAX_INTEGER_BITS = 1_024
MAX_CANONICAL_SERIALIZED_BYTES = 100_000
MAX_FINGERPRINT_INPUT_BYTES = 100_000
MAX_TOTAL_NODES = 10_000

# Backward-compatible private-policy alias retained for existing callers/tests.
MAX_SAFE_INTEGER_BITS = MAX_INTEGER_BITS

SUPPORTED_PACKET_SCHEMA_VERSION = "handoff-packet-v2"
RENDERER_VERSION = "packet-summary-h2"
SOURCE_FINGERPRINT_VERSION = "handoff-packet-source-h2-v3"
SUMMARY_FINGERPRINT_VERSION = "rendered-handoff-summary-h2-v4"
NON_AUTHORIZATION_NOTICE_VERSION = "non-authorization-v2"

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

REASON_EVIDENCE_INVALID = "rendering_evidence_missing_or_invalid"
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
REASON_SOURCE_FINGERPRINT_INVALID = "source_fingerprint_invalid"
REASON_SOURCE_FINGERPRINT_MISMATCH = "source_fingerprint_mismatch"
REASON_PACKET_CONTENT_UNSAFE = "packet_content_unsafe_for_rendering"
REASON_PACKET_RESOURCE_LIMIT_EXCEEDED = "packet_resource_limit_exceeded"
REASON_RENDERING_OPTIONS_INVALID = "rendering_options_invalid"
REASON_RENDERING_FAILURE = "rendering_failure"

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

_INVALID_DISPLAY = "<invalid>"
_SUMMARY_FINGERPRINT_PLACEHOLDER = "<summary-fingerprint>"
_RESOURCE_FAILURE_STATUS = "packet-resource-limit-exceeded"
_UNSAFE_FAILURE_STATUS = "unsafe-rendering-input"
_STREAM_TEXT_CHARS = 128

_LIST_PACKET_FIELDS: tuple[str, ...] = (
    "changed_files",
    "allowed_inspect_first",
    "forbidden_unless_needed",
    "known_facts",
    "prior_decisions",
    "acceptance_criteria",
    "validation_commands",
    "stop_conditions",
)

NON_AUTHORIZATION_NOTICE = (
    "This summary is context evidence only. It does not authorize "
    "implementation, execution, readiness or status changes, external writes, "
    "governed-field changes, merge, deployment, or production action. It does "
    "not independently verify provenance and is not proof that the packet is "
    "current unless trust status is 'current'. It is not a substitute for the "
    "canonical GitHub issue, approval record, or repository state."
)


@dataclass(frozen=True)
class RenderingEvidence:
    """Caller-supplied evidence used to classify summary trust."""

    producer: str
    packet_schema_version: str
    renderer_version: str
    provenance_status: str
    source_fingerprint: str | None = None

    @classmethod
    def unsupplied(cls) -> "RenderingEvidence":
        """Return the safe default when no evidence is supplied."""
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
    supplied_source_fingerprint: str | None
    summary_fingerprint: str
    provenance_status: str
    trust_status: str
    trust_reason: str | None

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class _NormalizedEvidence:
    producer: str | None
    packet_schema_version: str | None
    renderer_version: str | None
    provenance_status: str | None
    source_fingerprint: str | None
    source_fingerprint_invalid: bool = False
    invalid_reason: str | None = None


@dataclass(frozen=True)
class _RenderedCore:
    text: str
    safe: bool


class _ResourceLimitExceeded(Exception):
    """Internal signal for deterministic renderer resource rejection."""


@dataclass
class _ProcessingBudget:
    total_nodes: int = 0
    canonical_nodes: int = 0
    total_list_entries: int = 0
    total_dict_entries: int = 0
    total_string_bytes: int = 0

    def visit(self, *, canonical: bool, count: int = 1) -> None:
        self.total_nodes += count
        if self.total_nodes > MAX_TOTAL_NODES:
            raise _ResourceLimitExceeded
        if canonical:
            self.canonical_nodes += count
            if self.canonical_nodes > MAX_CANONICAL_NODES:
                raise _ResourceLimitExceeded

    def add_list_entries(self, count: int) -> None:
        if count > MAX_LIST_ENTRIES_PER_FIELD:
            raise _ResourceLimitExceeded
        self.total_list_entries += count
        if self.total_list_entries > MAX_TOTAL_LIST_ENTRIES:
            raise _ResourceLimitExceeded

    def add_dict_entries(self, count: int) -> None:
        if count > MAX_DICT_ENTRIES_PER_FIELD:
            raise _ResourceLimitExceeded
        self.total_dict_entries += count
        if self.total_dict_entries > MAX_TOTAL_DICT_ENTRIES:
            raise _ResourceLimitExceeded

    def add_string_bytes(self, count: int) -> None:
        self.total_string_bytes += count
        if self.total_string_bytes > MAX_TOTAL_STRING_BYTES:
            raise _ResourceLimitExceeded


class _BoundedDigestWriter:
    """Incrementally hash a deterministic payload without oversized buffers."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.serialized_bytes = 0
        self.fingerprint_bytes = 0

    def write(self, chunk: bytes) -> None:
        serialized_after = self.serialized_bytes + len(chunk)
        if serialized_after > MAX_CANONICAL_SERIALIZED_BYTES:
            raise _ResourceLimitExceeded
        fingerprint_after = self.fingerprint_bytes + len(chunk)
        if fingerprint_after > MAX_FINGERPRINT_INPUT_BYTES:
            raise _ResourceLimitExceeded
        self._digest.update(chunk)
        self.serialized_bytes = serialized_after
        self.fingerprint_bytes = fingerprint_after

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def summarize_handoff_packet(
    packet: Mapping[str, Any],
    *,
    list_limit: int = DEFAULT_SUMMARY_LIST_LIMIT,
    evidence: RenderingEvidence | None = None,
) -> RenderedHandoffSummary:
    """Return a deterministic, safety-complete summary for a handoff packet.

    The merged #265 validator remains the sole packet-validity authority. After
    validation, this renderer applies a separate fail-closed display and resource
    boundary; that boundary does not redefine packet validity.
    """
    normalized_evidence = _normalize_evidence(evidence)
    effective_limit, options_safe = _normalize_list_limit(list_limit)

    if _validator_requires_containment(packet):
        try:
            assert_valid_handoff_packet(packet)
        except ValueError:
            raise
        except Exception:
            return _build_failed_summary(
                evidence=normalized_evidence,
                effective_list_limit=effective_limit,
                trust_reason=REASON_PACKET_CONTENT_UNSAFE,
                failure_status=_UNSAFE_FAILURE_STATUS,
            )
    else:
        # For an inert exact-built-in packet, validator defects are trusted
        # subsystem defects and must remain visible rather than becoming a
        # caller-input classification.
        assert_valid_handoff_packet(packet)

    budget = _ProcessingBudget()
    try:
        _preflight_top_level_lengths(packet, budget)
        source_fingerprint, fingerprint_safe = _fingerprint_value_with_safety(
            packet,
            version=SOURCE_FINGERPRINT_VERSION,
            budget=budget,
            source_pass=True,
        )
        core = _render_core(packet, effective_limit, budget)
        packet_safe = core.safe and fingerprint_safe
        trust_status, trust_reason = _classify_trust(
            normalized_evidence,
            source_fingerprint,
            packet_safe=packet_safe,
            options_safe=options_safe,
        )
        return _assemble_result(
            core_text=core.text,
            effective_list_limit=effective_limit,
            evidence=normalized_evidence,
            actual_source_fingerprint=source_fingerprint,
            trust_status=trust_status,
            trust_reason=trust_reason,
            budget=budget,
        )
    except _ResourceLimitExceeded:
        return _build_failed_summary(
            evidence=normalized_evidence,
            effective_list_limit=effective_limit,
            trust_reason=REASON_PACKET_RESOURCE_LIMIT_EXCEEDED,
            failure_status=_RESOURCE_FAILURE_STATUS,
        )


def _validator_requires_containment(packet: Any) -> bool:
    """Return whether canonical validation may invoke caller-defined behavior.

    This is an inertness check, not a second packet validator. It inspects only
    exact built-in surfaces that the canonical validator may call directly.
    """
    if type(packet) is not dict:
        return True
    if dict.__len__(packet) > MAX_DICT_ENTRIES_PER_FIELD:
        return True
    for key in dict.keys(packet):
        if type(key) is not str:
            return True

    branch = dict.get(packet, "branch")
    if isinstance(branch, str) and type(branch) is not str:
        return True

    pr_number = dict.get(packet, "pr_number")
    if isinstance(pr_number, int) and type(pr_number) not in (int, bool):
        return True

    compute_limits = dict.get(packet, "compute_limits")
    if isinstance(compute_limits, Mapping):
        if type(compute_limits) is not dict:
            return True
        if dict.__len__(compute_limits) > MAX_DICT_ENTRIES_PER_FIELD:
            return True
        for key in dict.keys(compute_limits):
            if type(key) is not str:
                return True
        max_files = dict.get(compute_limits, "max_files_to_inspect")
        if isinstance(max_files, int) and type(max_files) not in (int, bool):
            return True

    return False


def _preflight_top_level_lengths(
    packet: Mapping[str, Any], budget: _ProcessingBudget
) -> None:
    """Reject oversized direct packet containers before content traversal."""
    budget.visit(canonical=False)
    if type(packet) is not dict:
        return

    direct_list_total = 0
    for field in _LIST_PACKET_FIELDS:
        budget.visit(canonical=False)
        value = dict.__getitem__(packet, field)
        if type(value) is list:
            count = list.__len__(value)
            if count > MAX_LIST_ENTRIES_PER_FIELD:
                raise _ResourceLimitExceeded
            direct_list_total += count
            if direct_list_total > MAX_TOTAL_LIST_ENTRIES:
                raise _ResourceLimitExceeded

    compute_limits = dict.__getitem__(packet, "compute_limits")
    if type(compute_limits) is dict:
        compute_count = dict.__len__(compute_limits)
        if compute_count > MAX_DICT_ENTRIES_PER_FIELD:
            raise _ResourceLimitExceeded
        if dict.__len__(packet) + compute_count > MAX_TOTAL_DICT_ENTRIES:
            raise _ResourceLimitExceeded


def _build_failed_summary(
    *,
    evidence: _NormalizedEvidence,
    effective_list_limit: int,
    trust_reason: str,
    failure_status: str,
) -> RenderedHandoffSummary:
    core = _render_failed_core()
    source_fingerprint = _fixed_failure_fingerprint(failure_status)
    return _assemble_result(
        core_text=core.text,
        effective_list_limit=effective_list_limit,
        evidence=evidence,
        actual_source_fingerprint=source_fingerprint,
        trust_status=TRUST_UNVERIFIABLE,
        trust_reason=trust_reason,
        budget=None,
    )


def _assemble_result(
    *,
    core_text: str,
    effective_list_limit: int,
    evidence: _NormalizedEvidence,
    actual_source_fingerprint: str,
    trust_status: str,
    trust_reason: str | None,
    budget: _ProcessingBudget | None,
) -> RenderedHandoffSummary:
    summary_fingerprint = _build_summary_fingerprint(
        core_text=core_text,
        effective_list_limit=effective_list_limit,
        evidence=evidence,
        actual_source_fingerprint=actual_source_fingerprint,
        trust_status=trust_status,
        trust_reason=trust_reason,
        budget=budget,
    )
    full_text = _build_full_text(
        core_text=core_text,
        evidence=evidence,
        actual_source_fingerprint=actual_source_fingerprint,
        summary_fingerprint=summary_fingerprint,
        trust_status=trust_status,
        trust_reason=trust_reason,
    )
    return RenderedHandoffSummary(
        text=full_text,
        producer=evidence.producer or "",
        packet_schema_version=evidence.packet_schema_version or "",
        renderer_version=evidence.renderer_version or "",
        source_fingerprint=actual_source_fingerprint,
        supplied_source_fingerprint=evidence.source_fingerprint,
        summary_fingerprint=summary_fingerprint,
        provenance_status=evidence.provenance_status or "",
        trust_status=trust_status,
        trust_reason=trust_reason,
    )


def _normalize_evidence(evidence: RenderingEvidence | None) -> _NormalizedEvidence:
    if evidence is None:
        evidence = RenderingEvidence.unsupplied()
    if type(evidence) is not RenderingEvidence:
        return _invalid_normalized_evidence()

    producer = _normalize_identity(evidence.producer, max_chars=128)
    schema = _normalize_identity(evidence.packet_schema_version, max_chars=128)
    renderer = _normalize_identity(evidence.renderer_version, max_chars=128)
    provenance = _normalize_identity(evidence.provenance_status, max_chars=64)

    source_value = evidence.source_fingerprint
    if source_value is None:
        source_fingerprint = None
        source_fingerprint_invalid = False
    elif _is_sha256_hex(source_value):
        source_fingerprint = source_value
        source_fingerprint_invalid = False
    else:
        source_fingerprint = None
        source_fingerprint_invalid = True

    return _NormalizedEvidence(
        producer=producer,
        packet_schema_version=schema,
        renderer_version=renderer,
        provenance_status=provenance,
        source_fingerprint=source_fingerprint,
        source_fingerprint_invalid=source_fingerprint_invalid,
    )


def _invalid_normalized_evidence() -> _NormalizedEvidence:
    return _NormalizedEvidence(
        producer=None,
        packet_schema_version=None,
        renderer_version=None,
        provenance_status=None,
        source_fingerprint=None,
        source_fingerprint_invalid=False,
        invalid_reason=REASON_EVIDENCE_INVALID,
    )


def _normalize_identity(value: Any, *, max_chars: int) -> str | None:
    if type(value) is not str:
        return None
    if not value or len(value) > max_chars or value != value.strip():
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _is_sha256_hex(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _normalize_list_limit(value: Any) -> tuple[int, bool]:
    if type(value) is not int:
        return DEFAULT_SUMMARY_LIST_LIMIT, False
    return min(MAX_SUMMARY_LIST_LIMIT, max(0, value)), True


def _classify_trust(
    evidence: _NormalizedEvidence,
    actual_source_fingerprint: str,
    *,
    packet_safe: bool,
    options_safe: bool,
) -> tuple[str, str | None]:
    if not packet_safe:
        return TRUST_UNVERIFIABLE, REASON_PACKET_CONTENT_UNSAFE
    if not options_safe:
        return TRUST_UNVERIFIABLE, REASON_RENDERING_OPTIONS_INVALID
    if evidence.invalid_reason is not None:
        return TRUST_UNVERIFIABLE, evidence.invalid_reason
    if evidence.producer is None:
        return TRUST_UNVERIFIABLE, REASON_PRODUCER_INVALID
    if evidence.packet_schema_version is None:
        return TRUST_UNVERIFIABLE, REASON_SCHEMA_VERSION_INVALID
    if evidence.renderer_version is None:
        return TRUST_UNVERIFIABLE, REASON_RENDERER_VERSION_INVALID
    if evidence.provenance_status is None:
        return TRUST_UNVERIFIABLE, REASON_PROVENANCE_STATUS_INVALID
    if evidence.provenance_status not in _ALLOWED_PROVENANCE_STATUSES:
        return TRUST_UNVERIFIABLE, REASON_PROVENANCE_STATUS_INVALID
    if evidence.provenance_status != _SUPPLIED_PROVENANCE_STATUS:
        return TRUST_UNVERIFIABLE, _PROVENANCE_FAIL_REASONS[evidence.provenance_status]
    if evidence.packet_schema_version != SUPPORTED_PACKET_SCHEMA_VERSION:
        return TRUST_UNSUPPORTED, REASON_SCHEMA_VERSION_UNSUPPORTED
    if evidence.renderer_version != RENDERER_VERSION:
        return TRUST_UNSUPPORTED, REASON_RENDERER_VERSION_UNSUPPORTED
    if evidence.source_fingerprint_invalid:
        return TRUST_UNVERIFIABLE, REASON_SOURCE_FINGERPRINT_INVALID
    if evidence.source_fingerprint is None:
        return TRUST_UNVERIFIABLE, REASON_SOURCE_FINGERPRINT_MISSING
    if evidence.source_fingerprint != actual_source_fingerprint:
        return TRUST_STALE, REASON_SOURCE_FINGERPRINT_MISMATCH
    return TRUST_CURRENT, None


def _render_core(
    packet: Mapping[str, Any], limit: int, budget: _ProcessingBudget
) -> _RenderedCore:
    if type(packet) is not dict:
        return _render_failed_core()

    lines: list[str] = []
    safe = True

    for label, key in (
        ("Objective", "objective"),
        ("Current phase", "current_phase"),
        ("Branch", "branch"),
        ("PR number", "pr_number"),
    ):
        rendered, value_safe = _render_scalar(dict.__getitem__(packet, key), budget)
        lines.append(f"{label}: {rendered}")
        safe = safe and value_safe

    for label, key in (
        ("Changed files", "changed_files"),
        ("Allowed inspect first", "allowed_inspect_first"),
        ("Forbidden unless needed", "forbidden_unless_needed"),
        ("Known facts", "known_facts"),
        ("Prior decisions", "prior_decisions"),
        ("Acceptance criteria", "acceptance_criteria"),
        ("Validation commands", "validation_commands"),
    ):
        safe = _append_list_section(
            lines,
            label,
            dict.__getitem__(packet, key),
            limit,
            budget,
        ) and safe

    safe = _append_compute_limits(
        lines,
        dict.__getitem__(packet, "compute_limits"),
        budget,
    ) and safe
    safe = _append_list_section(
        lines,
        "Stop conditions",
        dict.__getitem__(packet, "stop_conditions"),
        limit,
        budget,
    ) and safe

    return _RenderedCore(text="\n".join(lines), safe=safe)


def _render_failed_core() -> _RenderedCore:
    lines = [
        "Objective: <invalid>",
        "Current phase: <invalid>",
        "Branch: <invalid>",
        "PR number: <invalid>",
        "Changed files:",
        "- <invalid>",
        "Allowed inspect first:",
        "- <invalid>",
        "Forbidden unless needed:",
        "- <invalid>",
        "Known facts:",
        "- <invalid>",
        "Prior decisions:",
        "- <invalid>",
        "Acceptance criteria:",
        "- <invalid>",
        "Validation commands:",
        "- <invalid>",
        "Compute limits:",
        "- <invalid>",
        "Stop conditions:",
        "- <invalid>",
    ]
    return _RenderedCore(text="\n".join(lines), safe=False)


def _append_list_section(
    lines: list[str],
    title: str,
    values: Sequence[Any],
    limit: int,
    budget: _ProcessingBudget,
) -> bool:
    lines.append(f"{title}:")
    budget.visit(canonical=False)
    if type(values) is not list:
        lines.append(f"- {_INVALID_DISPLAY}")
        return False

    safe = True
    count = list.__len__(values)
    displayed_count = min(limit, count)
    for index in range(displayed_count):
        budget.visit(canonical=False)
        rendered, value_safe = _render_scalar(list.__getitem__(values, index), budget)
        lines.append(f"- {rendered}")
        safe = safe and value_safe

    remaining = count - displayed_count
    if remaining > 0:
        lines.append(f"...and {remaining} more")
    return safe


def _append_compute_limits(
    lines: list[str], values: Mapping[str, Any], budget: _ProcessingBudget
) -> bool:
    lines.append("Compute limits:")
    budget.visit(canonical=False)
    if type(values) is not dict:
        lines.append(f"- {_INVALID_DISPLAY}")
        return False

    count = dict.__len__(values)
    displayed_count = min(count, MAX_COMPUTE_LIMIT_ENTRIES)
    safe = True
    iterator = iter(dict.items(values))
    for _ in range(displayed_count):
        budget.visit(canonical=False)
        key, value = next(iterator)
        rendered_key, key_safe = _render_text_value(key, budget)
        rendered_value, value_safe = _render_scalar(value, budget)
        lines.append(f"- {rendered_key}: {rendered_value}")
        safe = safe and key_safe and value_safe

    remaining = count - displayed_count
    if remaining > 0:
        lines.append(f"...and {remaining} more compute limits")
    return safe


def _render_scalar(value: Any, budget: _ProcessingBudget) -> tuple[str, bool]:
    budget.visit(canonical=False)
    if value is None:
        return "None", True
    if type(value) is str:
        return _bounded_text(value), True
    if type(value) is bool:
        return "True" if value else "False", True
    if type(value) is int and value.bit_length() <= MAX_INTEGER_BITS:
        return str(value), True
    return _INVALID_DISPLAY, False


def _render_text_value(value: Any, budget: _ProcessingBudget) -> tuple[str, bool]:
    budget.visit(canonical=False)
    if type(value) is str:
        return _bounded_text(value), True
    return _INVALID_DISPLAY, False


def _bounded_text(value: str) -> str:
    output: list[str] = []
    used = 0
    consumed = 0
    for char in value:
        codepoint = ord(char)
        if char == "\n":
            fragment = "\\n"
        elif char == "\r":
            fragment = "\\r"
        elif char == "\t":
            fragment = "\\t"
        elif 0xD800 <= codepoint <= 0xDFFF:
            fragment = f"\\u{codepoint:04x}"
        elif codepoint < 32 or codepoint == 127:
            fragment = f"\\u{codepoint:04x}"
        else:
            fragment = char
        if used + len(fragment) > MAX_DISPLAY_VALUE_CHARS:
            break
        output.append(fragment)
        used += len(fragment)
        consumed += 1

    remaining = len(value) - consumed
    if remaining > 0:
        output.append(f"...<truncated {remaining} chars>")
    return "".join(output)


def _build_summary_fingerprint(
    *,
    core_text: str,
    effective_list_limit: int,
    evidence: _NormalizedEvidence,
    actual_source_fingerprint: str,
    trust_status: str,
    trust_reason: str | None,
    budget: _ProcessingBudget | None,
) -> str:
    template = _build_full_text(
        core_text=core_text,
        evidence=evidence,
        actual_source_fingerprint=actual_source_fingerprint,
        summary_fingerprint=_SUMMARY_FINGERPRINT_PLACEHOLDER,
        trust_status=trust_status,
        trust_reason=trust_reason,
    )
    payload = {
        "summary_fingerprint_version": SUMMARY_FINGERPRINT_VERSION,
        "notice_version": NON_AUTHORIZATION_NOTICE_VERSION,
        "effective_list_limit": effective_list_limit,
        "rendered_text_template": template,
    }
    if budget is not None:
        budget.visit(canonical=False, count=9)
    return _fingerprint_internal_payload(
        payload,
        version=SUMMARY_FINGERPRINT_VERSION,
    )


def _build_full_text(
    *,
    core_text: str,
    evidence: _NormalizedEvidence,
    actual_source_fingerprint: str,
    summary_fingerprint: str,
    trust_status: str,
    trust_reason: str | None,
) -> str:
    evidence_lines = [
        "",
        "Rendering evidence:",
        f"- Producer: {_display_normalized(evidence.producer)}",
        f"- Packet schema version: {_display_normalized(evidence.packet_schema_version)}",
        f"- Renderer version: {_display_normalized(evidence.renderer_version)}",
        f"- Supplied source fingerprint: {_display_normalized(evidence.source_fingerprint)}",
        f"- Actual source fingerprint: {actual_source_fingerprint}",
        f"- Summary fingerprint: {summary_fingerprint}",
        f"- Provenance status: {_display_normalized(evidence.provenance_status)}",
        f"- Trust status: {trust_status}",
        f"- Trust reason: {trust_reason if trust_reason is not None else 'none'}",
        "",
        NON_AUTHORIZATION_NOTICE,
    ]
    return core_text + "\n" + "\n".join(evidence_lines)


def _display_normalized(value: str | None) -> str:
    return _bounded_text(value) if value is not None else _INVALID_DISPLAY


def _fingerprint_value(
    value: Any, *, version: str = SOURCE_FINGERPRINT_VERSION
) -> str:
    try:
        digest, _ = _fingerprint_value_with_safety(
            value,
            version=version,
            budget=_ProcessingBudget(),
            source_pass=True,
        )
        return digest
    except _ResourceLimitExceeded:
        return _fixed_failure_fingerprint(_RESOURCE_FAILURE_STATUS)


def _fingerprint_value_with_safety(
    value: Any,
    *,
    version: str,
    budget: _ProcessingBudget,
    source_pass: bool,
) -> tuple[str, bool]:
    canonical, safe = _canonical_bytes(
        value,
        budget=budget,
        seen=set(),
        depth=0,
        source_pass=source_pass,
    )
    version_bytes = version.encode("utf-8")
    framed = _bounded_frame(b"fingerprint", (version_bytes, canonical))
    if len(framed) > MAX_FINGERPRINT_INPUT_BYTES:
        raise _ResourceLimitExceeded
    digest = hashlib.sha256()
    digest.update(framed)
    return digest.hexdigest(), safe


def _canonical_bytes(
    value: Any,
    *,
    budget: _ProcessingBudget,
    seen: set[int],
    depth: int,
    source_pass: bool,
) -> tuple[bytes, bool]:
    if depth > MAX_CANONICAL_DEPTH:
        raise _ResourceLimitExceeded

    budget.visit(canonical=source_pass)

    if value is None:
        return b"none", True
    if type(value) is bool:
        return b"bool:1" if value else b"bool:0", True
    if type(value) is int:
        if value.bit_length() > MAX_INTEGER_BITS:
            raise _ResourceLimitExceeded
        encoded = str(value).encode("ascii")
        return _bounded_frame(b"int", (encoded,)), True
    if type(value) is str:
        if len(value) > MAX_STRING_CHARS:
            raise _ResourceLimitExceeded
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError:
            return b"invalid-string", False
        budget.add_string_bytes(len(encoded))
        char_count = str(len(value)).encode("ascii")
        return _bounded_frame(b"str", (char_count, encoded)), True

    if type(value) is list:
        count = list.__len__(value)
        budget.add_list_entries(count)
        identity = id(value)
        if identity in seen:
            return b"invalid-cycle", False
        seen.add(identity)
        safe = True
        parts: list[bytes] = [str(count).encode("ascii")]
        try:
            for index in range(count):
                budget.visit(canonical=source_pass)
                item_bytes, item_safe = _canonical_bytes(
                    list.__getitem__(value, index),
                    budget=budget,
                    seen=seen,
                    depth=depth + 1,
                    source_pass=source_pass,
                )
                parts.append(item_bytes)
                safe = safe and item_safe
        finally:
            seen.remove(identity)
        return _bounded_frame(b"list", tuple(parts)), safe

    if type(value) is dict:
        count = dict.__len__(value)
        budget.add_dict_entries(count)
        identity = id(value)
        if identity in seen:
            return b"invalid-cycle", False
        seen.add(identity)
        safe = True
        entries: list[bytes] = []
        try:
            for key, item in dict.items(value):
                budget.visit(canonical=source_pass)
                key_bytes, key_safe = _canonical_bytes(
                    key,
                    budget=budget,
                    seen=seen,
                    depth=depth + 1,
                    source_pass=source_pass,
                )
                item_bytes, item_safe = _canonical_bytes(
                    item,
                    budget=budget,
                    seen=seen,
                    depth=depth + 1,
                    source_pass=source_pass,
                )
                entries.append(_bounded_frame(b"entry", (key_bytes, item_bytes)))
                safe = safe and key_safe and item_safe
        finally:
            seen.remove(identity)
        entries.sort()
        return _bounded_frame(
            b"dict",
            (str(count).encode("ascii"), *entries),
        ), safe

    return b"invalid-value", False


def _bounded_frame(tag: bytes, parts: tuple[bytes, ...]) -> bytes:
    output = bytearray()

    def append(chunk: bytes) -> None:
        if len(output) + len(chunk) > MAX_CANONICAL_SERIALIZED_BYTES:
            raise _ResourceLimitExceeded
        output.extend(chunk)

    append(tag)
    append(b"[")
    for part in parts:
        length = str(len(part)).encode("ascii")
        append(length)
        append(b":")
        append(part)
    append(b"]")
    return bytes(output)


def _fingerprint_internal_payload(payload: dict[str, Any], *, version: str) -> str:
    writer = _BoundedDigestWriter()
    writer.write(b"internal-fingerprint[")
    _write_stream_value(writer, version)
    _write_stream_value(writer, payload)
    writer.write(b"]")
    return writer.hexdigest()


def _write_stream_value(writer: _BoundedDigestWriter, value: Any) -> None:
    if value is None:
        writer.write(b"none;")
        return
    if type(value) is bool:
        writer.write(b"bool:1;" if value else b"bool:0;")
        return
    if type(value) is int:
        writer.write(b"int:")
        writer.write(str(value).encode("ascii"))
        writer.write(b";")
        return
    if type(value) is str:
        writer.write(b"str[")
        for start in range(0, len(value), _STREAM_TEXT_CHARS):
            encoded = value[start : start + _STREAM_TEXT_CHARS].encode(
                "utf-8", errors="strict"
            )
            writer.write(str(len(encoded)).encode("ascii"))
            writer.write(b":")
            writer.write(encoded)
        writer.write(b"]")
        return
    if type(value) is list:
        writer.write(b"list[")
        for item in value:
            _write_stream_value(writer, item)
        writer.write(b"]")
        return
    if type(value) is dict:
        writer.write(b"dict[")
        keys = dict.keys(value)
        if any(type(key) is not str for key in keys):
            raise TypeError("internal fingerprint payload keys must be strings")
        for key in sorted(keys):
            _write_stream_value(writer, key)
            _write_stream_value(writer, dict.__getitem__(value, key))
        writer.write(b"]")
        return
    raise TypeError("unsupported internal fingerprint payload type")


def _fixed_failure_fingerprint(status: str) -> str:
    payload = {
        "source_fingerprint_version": SOURCE_FINGERPRINT_VERSION,
        "status": status,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
