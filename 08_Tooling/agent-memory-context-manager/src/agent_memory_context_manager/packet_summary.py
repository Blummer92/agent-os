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
MAX_CANONICAL_DEPTH = 24
MAX_SAFE_INTEGER_BITS = 4096

SUPPORTED_PACKET_SCHEMA_VERSION = "handoff-packet-v2"
RENDERER_VERSION = "packet-summary-h2"
SOURCE_FINGERPRINT_VERSION = "handoff-packet-source-h2-v2"
SUMMARY_FINGERPRINT_VERSION = "rendered-handoff-summary-h2-v2"
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


def summarize_handoff_packet(
    packet: Mapping[str, Any],
    *,
    list_limit: int = DEFAULT_SUMMARY_LIST_LIMIT,
    evidence: RenderingEvidence | None = None,
) -> RenderedHandoffSummary:
    """Return a deterministic, safety-complete summary for a handoff packet.

    The merged #265 validator remains the sole packet-validity authority. After
    validation, this renderer applies a separate fail-closed display boundary so
    hostile values cannot become trusted output or leak through formatting.
    """
    normalized_evidence = _normalize_evidence(evidence)
    effective_limit, options_safe = _normalize_list_limit(list_limit)

    try:
        assert_valid_handoff_packet(packet)
    except ValueError:
        raise
    except Exception:
        return _build_failed_summary(
            evidence=normalized_evidence,
            effective_list_limit=effective_limit,
            trust_reason=REASON_PACKET_CONTENT_UNSAFE,
        )

    try:
        core = _render_core(packet, effective_limit)
        source_fingerprint, fingerprint_safe = _fingerprint_value_with_safety(
            packet,
            version=SOURCE_FINGERPRINT_VERSION,
        )
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
        )
    except Exception:
        return _build_failed_summary(
            evidence=normalized_evidence,
            effective_list_limit=effective_limit,
            trust_reason=REASON_RENDERING_FAILURE,
        )


def _build_failed_summary(
    *,
    evidence: _NormalizedEvidence,
    effective_list_limit: int,
    trust_reason: str,
) -> RenderedHandoffSummary:
    core = _render_failed_core()
    source_fingerprint = _fingerprint_value(
        {"status": "unsafe-rendering-input"},
        version=SOURCE_FINGERPRINT_VERSION,
    )
    return _assemble_result(
        core_text=core.text,
        effective_list_limit=effective_list_limit,
        evidence=evidence,
        actual_source_fingerprint=source_fingerprint,
        trust_status=TRUST_UNVERIFIABLE,
        trust_reason=trust_reason,
    )


def _assemble_result(
    *,
    core_text: str,
    effective_list_limit: int,
    evidence: _NormalizedEvidence,
    actual_source_fingerprint: str,
    trust_status: str,
    trust_reason: str | None,
) -> RenderedHandoffSummary:
    summary_fingerprint = _build_summary_fingerprint(
        core_text=core_text,
        effective_list_limit=effective_list_limit,
        evidence=evidence,
        actual_source_fingerprint=actual_source_fingerprint,
        trust_status=trust_status,
        trust_reason=trust_reason,
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


def _render_core(packet: Mapping[str, Any], limit: int) -> _RenderedCore:
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
        rendered, value_safe = _render_scalar(dict.__getitem__(packet, key))
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
        ) and safe

    safe = _append_compute_limits(
        lines,
        dict.__getitem__(packet, "compute_limits"),
    ) and safe
    safe = _append_list_section(
        lines,
        "Stop conditions",
        dict.__getitem__(packet, "stop_conditions"),
        limit,
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
) -> bool:
    lines.append(f"{title}:")
    if type(values) is not list:
        lines.append(f"- {_INVALID_DISPLAY}")
        return False

    safe = True
    count = list.__len__(values)
    displayed_count = min(limit, count)
    for index in range(displayed_count):
        rendered, value_safe = _render_scalar(list.__getitem__(values, index))
        lines.append(f"- {rendered}")
        safe = safe and value_safe

    remaining = count - displayed_count
    if remaining > 0:
        lines.append(f"...and {remaining} more")
    return safe


def _append_compute_limits(lines: list[str], values: Mapping[str, Any]) -> bool:
    lines.append("Compute limits:")
    if type(values) is not dict:
        lines.append(f"- {_INVALID_DISPLAY}")
        return False

    items = list(dict.items(values))
    safe = True
    for key, value in items[:MAX_COMPUTE_LIMIT_ENTRIES]:
        rendered_key, key_safe = _render_text_value(key)
        rendered_value, value_safe = _render_scalar(value)
        lines.append(f"- {rendered_key}: {rendered_value}")
        safe = safe and key_safe and value_safe

    remaining = len(items) - min(len(items), MAX_COMPUTE_LIMIT_ENTRIES)
    if remaining > 0:
        lines.append(f"...and {remaining} more compute limits")
    return safe


def _render_scalar(value: Any) -> tuple[str, bool]:
    if value is None:
        return "None", True
    if type(value) is str:
        return _bounded_text(value), True
    if type(value) is bool:
        return "True" if value else "False", True
    if type(value) is int and value.bit_length() <= MAX_SAFE_INTEGER_BITS:
        return str(value), True
    return _INVALID_DISPLAY, False


def _render_text_value(value: Any) -> tuple[str, bool]:
    if type(value) is str:
        return _bounded_text(value), True
    return _INVALID_DISPLAY, False


def _bounded_text(value: str) -> str:
    output: list[str] = []
    used = 0
    consumed = 0
    for char in value:
        if char == "\n":
            fragment = "\\n"
        elif char == "\r":
            fragment = "\\r"
        elif char == "\t":
            fragment = "\\t"
        elif ord(char) < 32 or ord(char) == 127:
            fragment = f"\\u{ord(char):04x}"
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
    return _fingerprint_value(payload, version=SUMMARY_FINGERPRINT_VERSION)


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


def _fingerprint_value(value: Any, *, version: str = SOURCE_FINGERPRINT_VERSION) -> str:
    digest, _ = _fingerprint_value_with_safety(value, version=version)
    return digest


def _fingerprint_value_with_safety(value: Any, *, version: str) -> tuple[str, bool]:
    canonical, safe = _to_canonical(value, seen=set(), depth=0)
    encoded = json.dumps(
        {"version": version, "value": canonical},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), safe


def _to_canonical(
    value: Any,
    *,
    seen: set[int],
    depth: int,
) -> tuple[Any, bool]:
    if depth > MAX_CANONICAL_DEPTH:
        return {"kind": "invalid-depth"}, False
    if value is None:
        return {"kind": "none"}, True
    if type(value) is bool:
        return {"kind": "bool", "value": value}, True
    if type(value) is int:
        if value.bit_length() > MAX_SAFE_INTEGER_BITS:
            return {"kind": "invalid-integer", "bits": value.bit_length()}, False
        return {"kind": "int", "value": str(value)}, True
    if type(value) is str:
        return {
            "kind": "str",
            "length": len(value),
            "sha256": _hash_exact_text(value),
        }, True

    if type(value) in (list, tuple):
        identity = id(value)
        if identity in seen:
            return {"kind": "invalid-cycle"}, False
        seen.add(identity)
        safe = True
        items = []
        for item in value:
            canonical_item, item_safe = _to_canonical(
                item,
                seen=seen,
                depth=depth + 1,
            )
            items.append(canonical_item)
            safe = safe and item_safe
        seen.remove(identity)
        return {"kind": "list", "items": items}, safe

    if type(value) is dict:
        identity = id(value)
        if identity in seen:
            return {"kind": "invalid-cycle"}, False
        seen.add(identity)
        safe = True
        sortable_entries = []
        for key, item in dict.items(value):
            canonical_key, key_safe = _to_canonical(
                key,
                seen=seen,
                depth=depth + 1,
            )
            canonical_item, item_safe = _to_canonical(
                item,
                seen=seen,
                depth=depth + 1,
            )
            sort_key = json.dumps(
                [canonical_key, canonical_item],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            sortable_entries.append((sort_key, canonical_key, canonical_item))
            safe = safe and key_safe and item_safe
        seen.remove(identity)
        sortable_entries.sort(key=lambda entry: entry[0])
        return {
            "kind": "dict",
            "entries": [
                [canonical_key, canonical_item]
                for _, canonical_key, canonical_item in sortable_entries
            ],
        }, safe

    return {"kind": "invalid-value"}, False


def _hash_exact_text(value: str) -> str:
    digest = hashlib.sha256()
    for start in range(0, len(value), 4096):
        digest.update(value[start : start + 4096].encode("utf-8"))
    return digest.hexdigest()
