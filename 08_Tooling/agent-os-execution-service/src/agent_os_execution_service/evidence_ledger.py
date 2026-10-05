"""Finite-mission evidence ledger for AI navigation decisions (Phase 1 B5).

Append-only, hash-chained record of navigation decisions: selection,
execution, and completion evidence bound to one finite mission_id.

Mandated persisted fields per navigation decision (global-engineering
finite-mission evidence-ledger standard):

| field            | meaning                                                      |
|------------------|--------------------------------------------------------------|
| schema_name      | ``"agent-os-evidence-ledger-entry"``                          |
| schema_version   | ``"1.0"``                                                    |
| mission_id       | the finite mission this decision belongs to                  |
| decision_type    | ``"selection"`` \\| ``"execution"`` \\| ``"completion"``      |
| decision_label   | the seam that produced the decision (e.g. ``"shadow-selection"``) |
| inputs_digest    | sha256 over the canonical JSON of the decision inputs        |
| reason_codes     | deterministic reason codes recorded by the deciding seam    |
| provenance_refs  | references to the provenance the decision rests on           |
| recorded_at      | UTC timestamp the entry was recorded                         |
| actor            | who/what recorded the entry                                  |
| previous_digest  | entry_digest of the previous entry (None for the genesis)    |
| entry_digest     | content address of this entry, binding previous_digest       |

Chaining rule: ``entry_digest = sha256("agent-os-evidence-ledger-entry:v1\\0"
+ canonical_json(all fields except entry_digest, with previous_digest or ""))``.
Every entry therefore binds the full history before it; tampering with any
field breaks that entry's digest and every later entry's chain link.

Mission binding: one ledger holds one mission. ``EvidenceLedger.append``
rejects an entry whose mission_id differs from the ledger's mission, so
selection, execution, and completion evidence for one mission always share
one chain.

The ledger records observed decisions. It never manufactures operational
state, authorization, routing semantics, source-of-truth state, currentness,
or execution permission: those remain owned by the canonical seams that
produced the decisions.

mission_id policy: the caller supplies it (for example
``scripts/agent-os-shadow-run.py --mission-id``); when the caller does not
supply one, it is derived deterministically at the call site as
``shadow-run:{campaign_id}:{retrieved_at}``. The ledger itself accepts any
exact-text mission_id.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

EVIDENCE_LEDGER_SCHEMA_NAME = "agent-os-evidence-ledger-entry"
EVIDENCE_LEDGER_SCHEMA_VERSION = "1.0"

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class NavigationDecisionType(str, Enum):
    SELECTION = "selection"
    EXECUTION = "execution"
    COMPLETION = "completion"


def _exact_text(value: object, name: str, maximum: int) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be a built-in string")
    if not value or len(value.encode("utf-8")) > maximum or _CONTROL_RE.search(value):
        raise ValueError(f"{name} is outside bounds")
    return value


def _exact_timestamp(value: object, name: str) -> str:
    if type(value) is not str or not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{name} must use YYYY-MM-DDTHH:MM:SSZ form")
    return value


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_decision_inputs(inputs: Mapping[str, object]) -> str:
    """Return the sha256 inputs digest over canonical JSON of decision inputs."""
    if not isinstance(inputs, Mapping):
        raise TypeError("decision inputs must be a mapping")
    material = b"agent-os-evidence-ledger-inputs:v1\0" + _canonical_json(
        dict(inputs)
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _entry_digest(payload: dict[str, object]) -> str:
    material = b"agent-os-evidence-ledger-entry:v1\0" + _canonical_json(payload).encode(
        "utf-8"
    )
    return hashlib.sha256(material).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEntry:
    """One immutable, hash-chained navigation decision record."""

    schema_name: str
    schema_version: str
    mission_id: str
    decision_type: NavigationDecisionType
    decision_label: str | None
    inputs_digest: str
    reason_codes: tuple[str, ...]
    provenance_refs: tuple[str, ...]
    recorded_at: str
    actor: str
    previous_digest: str | None
    entry_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_name != EVIDENCE_LEDGER_SCHEMA_NAME:
            raise ValueError("unsupported evidence ledger entry schema name")
        if self.schema_version != EVIDENCE_LEDGER_SCHEMA_VERSION:
            raise ValueError("unsupported evidence ledger entry schema version")
        _exact_text(self.mission_id, "mission_id", 256)
        if not isinstance(self.decision_type, NavigationDecisionType):
            raise TypeError("decision_type must be NavigationDecisionType")
        if self.decision_label is not None:
            _exact_text(self.decision_label, "decision_label", 256)
        if type(self.inputs_digest) is not str or not _HEX64_RE.fullmatch(self.inputs_digest):
            raise ValueError("inputs_digest must be a lowercase 64-character sha256 hex")
        reasons = tuple(self.reason_codes)
        if type(self.reason_codes) is not tuple or not reasons:
            raise TypeError("reason_codes must be a non-empty exact tuple")
        checked_reasons = tuple(_exact_text(code, "reason_codes", 128) for code in reasons)
        if tuple(sorted(set(checked_reasons))) != checked_reasons:
            raise ValueError("reason_codes must be sorted and unique")
        object.__setattr__(self, "reason_codes", checked_reasons)
        refs = tuple(self.provenance_refs)
        if type(self.provenance_refs) is not tuple or not refs:
            raise TypeError("provenance_refs must be a non-empty exact tuple")
        checked_refs = tuple(_exact_text(ref, "provenance_refs", 512) for ref in refs)
        if tuple(sorted(set(checked_refs))) != checked_refs:
            raise ValueError("provenance_refs must be sorted and unique")
        object.__setattr__(self, "provenance_refs", checked_refs)
        _exact_timestamp(self.recorded_at, "recorded_at")
        _exact_text(self.actor, "actor", 256)
        if self.previous_digest is not None and (
            type(self.previous_digest) is not str
            or not _HEX64_RE.fullmatch(self.previous_digest)
        ):
            raise ValueError("previous_digest must be a lowercase 64-character sha256 hex or None")

        expected = _entry_digest(self._digest_payload())
        if self.entry_digest and self.entry_digest != expected:
            raise ValueError("entry_digest does not match evidence ledger entry content")
        object.__setattr__(self, "entry_digest", expected)

    def _digest_payload(self) -> dict[str, object]:
        return {
            "schema_name": self.schema_name,
            "schema_version": self.schema_version,
            "mission_id": self.mission_id,
            "decision_type": self.decision_type.value,
            "decision_label": self.decision_label,
            "inputs_digest": self.inputs_digest,
            "reason_codes": list(self.reason_codes),
            "provenance_refs": list(self.provenance_refs),
            "recorded_at": self.recorded_at,
            "actor": self.actor,
            "previous_digest": self.previous_digest if self.previous_digest is not None else "",
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_payload(), "entry_digest": self.entry_digest}

    @classmethod
    def from_dict(cls, payload: object) -> EvidenceLedgerEntry:
        if type(payload) is not dict:
            raise TypeError("evidence ledger entry must be an exact JSON object")
        expected = frozenset(
            {
                "schema_name",
                "schema_version",
                "mission_id",
                "decision_type",
                "decision_label",
                "inputs_digest",
                "reason_codes",
                "provenance_refs",
                "recorded_at",
                "actor",
                "previous_digest",
                "entry_digest",
            }
        )
        unknown = set(payload) - expected
        missing = expected - set(payload)
        if unknown:
            raise ValueError(
                f"evidence ledger entry contains unknown fields: {sorted(unknown)}"
            )
        if missing:
            raise ValueError(
                f"evidence ledger entry is missing fields: {sorted(missing)}"
            )
        try:
            decision_type = NavigationDecisionType(payload["decision_type"])
        except (TypeError, ValueError) as exc:
            raise ValueError("evidence ledger entry decision_type is unsupported") from exc
        for key in ("reason_codes", "provenance_refs"):
            if type(payload[key]) is not list:
                raise TypeError(f"evidence ledger entry {key} must be an exact JSON array")
        return cls(
            schema_name=payload["schema_name"],
            schema_version=payload["schema_version"],
            mission_id=payload["mission_id"],
            decision_type=decision_type,
            decision_label=payload["decision_label"],
            inputs_digest=payload["inputs_digest"],
            reason_codes=tuple(payload["reason_codes"]),
            provenance_refs=tuple(payload["provenance_refs"]),
            recorded_at=payload["recorded_at"],
            actor=payload["actor"],
            previous_digest=payload["previous_digest"] or None,
            entry_digest=payload["entry_digest"],
        )


class EvidenceLedger:
    """One mission's append-only evidence chain. Immutable: append returns a new ledger."""

    def __init__(self, entries: tuple[EvidenceLedgerEntry, ...] = ()) -> None:
        if type(entries) is not tuple or any(
            type(entry) is not EvidenceLedgerEntry for entry in entries
        ):
            raise TypeError("entries must be an exact tuple of EvidenceLedgerEntry")
        self._entries = entries
        self.verify()

    @property
    def entries(self) -> tuple[EvidenceLedgerEntry, ...]:
        return self._entries

    @property
    def mission_id(self) -> str | None:
        return self._entries[0].mission_id if self._entries else None

    def append(
        self,
        *,
        mission_id: str,
        decision_type: NavigationDecisionType,
        inputs_digest: str,
        reason_codes: tuple[str, ...],
        provenance_refs: tuple[str, ...],
        recorded_at: str,
        actor: str,
        decision_label: str | None = None,
    ) -> EvidenceLedger:
        """Append one decision entry, binding the previous entry's digest.

        Raises when mission_id differs from the ledger's mission: one ledger
        holds one mission's selection, execution, and completion evidence.
        """
        if self._entries and mission_id != self._entries[0].mission_id:
            raise ValueError(
                "evidence ledger is mission-bound: cannot append an entry "
                "for a different mission_id"
            )
        entry = EvidenceLedgerEntry(
            schema_name=EVIDENCE_LEDGER_SCHEMA_NAME,
            schema_version=EVIDENCE_LEDGER_SCHEMA_VERSION,
            mission_id=mission_id,
            decision_type=decision_type,
            decision_label=decision_label,
            inputs_digest=inputs_digest,
            reason_codes=reason_codes,
            provenance_refs=provenance_refs,
            recorded_at=recorded_at,
            actor=actor,
            previous_digest=self._entries[-1].entry_digest if self._entries else None,
        )
        return EvidenceLedger(self._entries + (entry,))

    def verify(self) -> None:
        """Raise on any broken chain link or digest mismatch."""
        previous: str | None = None
        for index, entry in enumerate(self._entries):
            if entry.previous_digest != previous:
                raise ValueError(
                    f"evidence ledger chain is broken at entry {index}: "
                    "previous_digest does not bind the prior entry"
                )
            expected = _entry_digest(entry._digest_payload())
            if entry.entry_digest != expected:
                raise ValueError(
                    f"evidence ledger entry {index} digest mismatch: entry was altered"
                )
            previous = entry.entry_digest

    def to_jsonl(self) -> str:
        return "".join(_canonical_json(entry.to_dict()) + "\n" for entry in self._entries)

    @classmethod
    def from_jsonl(cls, text: object) -> EvidenceLedger:
        if type(text) is not str:
            raise TypeError("jsonl ledger must be built-in text")
        entries: list[EvidenceLedgerEntry] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"evidence ledger line {line_number} is not valid JSON"
                ) from exc
            entries.append(EvidenceLedgerEntry.from_dict(payload))
        return cls(tuple(entries))
