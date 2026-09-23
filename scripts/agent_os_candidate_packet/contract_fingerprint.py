"""Deterministic `implementation_contract_fingerprint` derivation (#1105).

The fingerprint is a derived semantic identity, never caller-authored
authority or evidence. It is built only from already-canonical normalized
implementation-contract fields already owned by
``scripts.agent_os_issue_acceptance`` -- the same governed IssuePlan fields
`#751`'s planning stage already treats as implementation-semantic -- and
never from raw issue prose, formatting, comments, labels, or observational
timestamps. Source/body revision keeps its own separate identity role
(`IssueSnapshot.source_revision`, `IssuePlanSourceSnapshot.source_revision`)
and is never replaced by this fingerprint.

This module holds exactly two things: the pure hashing helper, and the one
extraction function that reads already-scanned governed fields into the
mapping that helper expects. Both stay together deliberately -- splitting
them into separate files would not change their behavior, only their file
count.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from scripts.agent_os_issue_acceptance.issueplan_current_state import (
    IssuePlanSourceSnapshot,
)

from .stage_models import canonical_bytes

IMPLEMENTATION_CONTRACT_SCHEMA_NAME = "agent-os-implementation-contract"
IMPLEMENTATION_CONTRACT_SCHEMA_VERSION = "1.0"

# Closed set of governed IssuePlan field names this module ever reads. Every
# other field the scanner recognizes (``owner_agent``, ``source_of_truth``,
# ``profile_version``, ``external_writes``, ``required_docs``,
# ``banned_patterns``, ``manual_review``, ``documentation_expected_change``,
# ``documentation_exemption_reason``) is deliberately excluded: the first two
# already have their own existing semantic binding into the planning-stage
# node (`#751`'s own `_decode_governed_text` reads them directly), and
# duplicating them here would represent the same fact under two identities
# rather than filling a gap. The remainder are administrative, free-text
# justification, or not yet treated as implementation-semantic by any
# existing canonical contract.
_ENTITY_FIELD = "entity_id"
_SCOPE_FIELD = "required_files"
_FORBIDDEN_FIELD = "forbidden_paths"
_TESTS_FIELD = "required_tests"
_DOC_IMPACT_FIELD = "documentation_impact"
_GOVERNED_SOURCE_FIELDS = (
    _ENTITY_FIELD,
    _SCOPE_FIELD,
    _FORBIDDEN_FIELD,
    _TESTS_FIELD,
    _DOC_IMPACT_FIELD,
)

_CANONICAL_CONTRACT_KEYS = frozenset(
    {"entity_id", "allowed_files", "forbidden_paths", "required_tests", "documentation_impact"}
)
_LIST_KEYS = ("allowed_files", "forbidden_paths", "required_tests")
_SCALAR_KEYS = ("entity_id", "documentation_impact")

_MAX_ITEMS = 2_000
_MAX_TEXT_LENGTH = 4_096


class ImplementationContractError(ValueError):
    """Raised when a canonical contract mapping cannot be fingerprinted."""


def _validate_text(value: object, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str):
        raise ImplementationContractError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ImplementationContractError(f"{field_name} must be a non-empty canonical string")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ImplementationContractError(f"{field_name} exceeds the maximum length")
    if any(character < " " or character == "\x7f" for character in value):
        raise ImplementationContractError(f"{field_name} must not contain control characters")
    return value


def _validate_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _validate_text(value, field_name)


def _validate_string_list(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Iterable):
        raise ImplementationContractError(f"{field_name} must be an iterable of strings")
    items = list(value)
    if len(items) > _MAX_ITEMS:
        raise ImplementationContractError(f"{field_name} exceeds the maximum item count")
    validated = tuple(_validate_text(item, field_name) for item in items)
    # Semantic scope/test/path membership is order-independent and duplicate-free;
    # normalize so two logically identical sets never produce different
    # fingerprints purely from caller ordering or repetition.
    return tuple(sorted(set(validated)))


def _canonical_contract_payload(canonical_contract: Mapping[str, object]) -> dict[str, Any]:
    if not isinstance(canonical_contract, Mapping):
        raise ImplementationContractError("canonical_contract must be a mapping")
    supplied = set(canonical_contract)
    missing = sorted(_CANONICAL_CONTRACT_KEYS - supplied)
    if missing:
        raise ImplementationContractError(
            "canonical_contract is missing field(s): " + ", ".join(missing)
        )
    unsupported = sorted(supplied - _CANONICAL_CONTRACT_KEYS)
    if unsupported:
        raise ImplementationContractError(
            "canonical_contract has unsupported field(s): " + ", ".join(unsupported)
        )

    payload: dict[str, Any] = {
        "schema_name": IMPLEMENTATION_CONTRACT_SCHEMA_NAME,
        "schema_version": IMPLEMENTATION_CONTRACT_SCHEMA_VERSION,
    }
    for key in _SCALAR_KEYS:
        payload[key] = _validate_optional_text(canonical_contract[key], key)
    for key in _LIST_KEYS:
        payload[key] = list(_validate_string_list(canonical_contract[key], key))
    return payload


def compute_implementation_contract_fingerprint(
    *, canonical_contract: Mapping[str, object]
) -> str:
    """Deterministically derive one bare hex-64 SHA-256 fingerprint.

    ``canonical_contract`` must supply exactly ``entity_id``,
    ``allowed_files``, ``forbidden_paths``, ``required_tests``, and
    ``documentation_impact`` -- a closed schema, not an arbitrary mapping.
    Malformed, incomplete, contradictory, oversized, unsupported, or
    type-confused input raises ``ImplementationContractError`` (a
    ``ValueError`` subclass) rather than silently coercing or guessing.

    The result never depends on raw issue prose, comments, formatting, or
    observational timestamps -- only on the five normalized fields above,
    encoded as canonical UTF-8 JSON (sorted keys, compact separators) and
    hashed with SHA-256.

    The return value is deliberately a *bare* hex digest, matching every
    existing ``*_fingerprint`` field this codebase already defines
    (``source_snapshot_fingerprint``, ``scanner_result_fingerprint``,
    ``candidate_set_fingerprint``, and -- critically --
    `#917`'s own `IssuePlanningContext.implementation_contract_fingerprint`
    and `#755`'s `CandidatePacketCompilerInput.expected_implementation_contract_fingerprint`,
    which both reject anything but a 64-character lowercase hex string).
    Domain separation lives in the embedded ``schema_name``/``schema_version``
    payload fields, not a string prefix -- the same pattern those sibling
    fingerprints already use. This differs deliberately from this package's
    own ``*_id`` values (``candidate_packet_id``, `#917`'s
    ``issueplan-current-state:`` evidence ID), which *are* domain-prefixed
    because they identify a standalone object rather than fill an existing
    bare-hex field.
    """
    payload = _canonical_contract_payload(canonical_contract)
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def derive_canonical_contract(source_snapshot: IssuePlanSourceSnapshot) -> dict[str, object]:
    """Build the fingerprint's input mapping from already-scanned governed fields.

    ``source_snapshot.governed_fields`` is the exact canonical output of
    `#750`'s `scan_issueplan_source` / `build_issueplan_current_state_evidence`
    pipeline -- this function parses none of the issue body itself. A
    governed field in ``absent``, ``null``, or ``intentionally-omitted``
    state contributes an empty/`None` value, exactly like an ordinary
    optional field; ``ambiguous``, ``malformed``, ``unavailable``,
    ``unsupported``, ``stale``, ``identity-quarantined``, or
    ``unknown-governed-field`` states fail closed rather than guess.
    """
    if not isinstance(source_snapshot, IssuePlanSourceSnapshot):
        raise ImplementationContractError(
            "source_snapshot must be an IssuePlanSourceSnapshot"
        )
    fields_by_name = {name: (state, value) for name, state, value in source_snapshot.governed_fields}

    contract: dict[str, object] = {}
    for field_name in _GOVERNED_SOURCE_FIELDS:
        decoded = _decode_governed_field(fields_by_name.get(field_name), field_name)
        if field_name == _ENTITY_FIELD:
            contract["entity_id"] = decoded
        elif field_name == _SCOPE_FIELD:
            contract["allowed_files"] = decoded if decoded is not None else ()
        elif field_name == _FORBIDDEN_FIELD:
            contract["forbidden_paths"] = decoded if decoded is not None else ()
        elif field_name == _TESTS_FIELD:
            contract["required_tests"] = decoded if decoded is not None else ()
        elif field_name == _DOC_IMPACT_FIELD:
            contract["documentation_impact"] = decoded
    return contract


_OPTIONAL_ABSENT_STATES = frozenset({"absent", "null", "intentionally-omitted"})


def _decode_governed_field(
    entry: tuple[str, str | None] | None, field_name: str
) -> object | None:
    if entry is None:
        return None
    state, canonical_value = entry
    if state in _OPTIONAL_ABSENT_STATES:
        return None
    if state != "present":
        raise ImplementationContractError(
            f"{field_name} governed-field state is not resolvable: {state}"
        )
    if canonical_value is None:
        raise ImplementationContractError(f"{field_name} governed-field value is missing")
    try:
        decoded = json.loads(canonical_value)
    except (json.JSONDecodeError, TypeError) as error:
        raise ImplementationContractError(
            f"{field_name} governed-field value is not canonical JSON"
        ) from error
    return decoded
