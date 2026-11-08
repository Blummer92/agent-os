"""Canonical frozen task packets for #3337 (AN-MR2).

A task packet is the unit of comparison: identical packet digests across
candidate runs are what make two runs comparable. Task/reasoning semantics
(task class and reasoning effort) are reused from the AN-MR1 provider-neutral
contract (#3336, merged #3375) -- packets describe what reasoning a task
*requires*, never which model should execute it or which setting was used.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:  # pragma: no cover - exercised when the root test conftest already set the path
    from agent_os_execution_service.reasoning_profile import ReasoningEffort, TaskClass
except ImportError:  # pragma: no cover - standalone use without the test conftest
    _SERVICE_SRC = (
        Path(__file__).resolve().parents[2]
        / "08_Tooling"
        / "agent-os-execution-service"
        / "src"
    )
    sys.path.insert(0, str(_SERVICE_SRC))
    from agent_os_execution_service.reasoning_profile import (  # noqa: E402
        ReasoningEffort,
        TaskClass,
    )

PACKETS_SCHEMA_VERSION = "1.0"
_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_PACKETS_PATH = _FIXTURES_DIR / "task_packets.json"


class TaskFamily(str, Enum):
    """The seven required #3337 task families."""

    T1 = "T1"  # extraction
    T2 = "T2"  # classification/triage
    T3 = "T3"  # ordinary implementation reasoning
    T4 = "T4"  # debugging
    T5 = "T5"  # architecture
    T6 = "T6"  # adversarial review
    T7 = "T7"  # decision support / manual-review calibration


FAMILY_TASK_CLASS: dict[TaskFamily, tuple[TaskClass, ...]] = {
    TaskFamily.T1: (TaskClass.EXTRACT,),
    TaskFamily.T2: (TaskClass.CLASSIFY, TaskClass.TRIAGE),
    TaskFamily.T3: (TaskClass.IMPLEMENT,),
    TaskFamily.T4: (TaskClass.DEBUG,),
    TaskFamily.T5: (TaskClass.ARCHITECTURE,),
    TaskFamily.T6: (TaskClass.ADVERSARIAL_REVIEW,),
    TaskFamily.T7: (TaskClass.DECISION_SUPPORT,),
}


class PacketError(ValueError):
    """A task packet fixture is malformed."""


@dataclass(frozen=True, slots=True)
class ScoredField:
    """One scored output field of a packet.

    kind "exact": provided value must equal expected (string comparison).
    kind "keyset": provided value must contain every expected keyword
    (case-insensitive substring match); score is the fraction present.
    """

    name: str
    kind: str
    expected: Any


@dataclass(frozen=True, slots=True)
class TaskPacket:
    """One frozen canonical task packet."""

    packet_id: str
    family: TaskFamily
    task_class: TaskClass
    reasoning_effort: ReasoningEffort
    prompt: str
    scored_fields: tuple[ScoredField, ...]
    packet_digest: str


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def packet_content_digest(payload: dict[str, Any]) -> str:
    """Deterministic digest over the scored content of a packet fixture."""
    try:
        material = {"packet_id": payload["packet_id"], "scored_fields": payload["scored_fields"]}
    except (KeyError, TypeError) as exc:
        raise PacketError(f"cannot digest malformed packet payload: {exc}") from None
    digest = hashlib.sha256(
        f"task-packet:v1\0{_canonical_json(material)}".encode("utf-8")
    ).hexdigest()
    return f"task-packet:{digest}"


def _parse_field(raw: dict[str, Any], packet_id: str) -> ScoredField:
    try:
        name = raw["name"]
        kind = raw["kind"]
        expected = raw["expected"]
    except (KeyError, TypeError) as exc:
        raise PacketError(f"packet {packet_id}: malformed scored field: {exc}") from None
    if not isinstance(name, str) or not name:
        raise PacketError(f"packet {packet_id}: scored field needs a name")
    if kind not in ("exact", "keyset"):
        raise PacketError(f"packet {packet_id}: field {name} has unknown kind {kind!r}")
    return ScoredField(name=name, kind=kind, expected=expected)


def _parse_packet(raw: dict[str, Any]) -> TaskPacket:
    try:
        packet_id = raw["packet_id"]
        family = TaskFamily(raw["family"])
        task_class = TaskClass(raw["task_class"])
        effort = ReasoningEffort(raw["reasoning_effort"])
        prompt = raw["prompt"]
        raw_fields = raw["scored_fields"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PacketError(f"malformed packet fixture: {exc}") from None
    if task_class not in FAMILY_TASK_CLASS[family]:
        raise PacketError(
            f"packet {packet_id}: task_class {task_class.value} is not in family {family.value}"
        )
    if not isinstance(prompt, str) or not prompt:
        raise PacketError(f"packet {packet_id}: prompt must be a non-empty string")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise PacketError(f"packet {packet_id}: scored_fields must be a non-empty list")
    fields = tuple(_parse_field(item, packet_id) for item in raw_fields)
    names = [field.name for field in fields]
    if len(set(names)) != len(names):
        raise PacketError(f"packet {packet_id}: duplicate scored field names")
    digest = packet_content_digest(raw)
    return TaskPacket(
        packet_id=packet_id,
        family=family,
        task_class=task_class,
        reasoning_effort=effort,
        prompt=prompt,
        scored_fields=fields,
        packet_digest=digest,
    )


def load_packets(path: str | Path = _PACKETS_PATH) -> tuple[TaskPacket, ...]:
    """Load and validate the canonical task packet fixtures."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot load packets: {exc}") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != PACKETS_SCHEMA_VERSION:
        raise PacketError("packet schema_version must be '1.0'")
    packets = tuple(_parse_packet(item) for item in raw.get("packets", ()))
    if not packets:
        raise PacketError("packet corpus is empty")
    ids = [packet.packet_id for packet in packets]
    if len(set(ids)) != len(ids):
        raise PacketError("duplicate packet_id in corpus")
    return packets


def verify_packets_frozen(packets: tuple[TaskPacket, ...]) -> dict[str, str]:
    """Return packet_id -> digest; a changed digest marks a non-comparable packet."""
    return {packet.packet_id: packet.packet_digest for packet in packets}
