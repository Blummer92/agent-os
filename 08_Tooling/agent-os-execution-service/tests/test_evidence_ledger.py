"""Phase 1 B5: finite-mission evidence ledger.

Covers: the mandated persisted-field schema, append-only hash chaining,
mission-ID binding across selection/execution/completion entries, tamper
detection, JSONL round-trip, and input-digest determinism.
"""

from __future__ import annotations

import pytest

from agent_os_execution_service.evidence_ledger import (
    EVIDENCE_LEDGER_SCHEMA_NAME,
    EVIDENCE_LEDGER_SCHEMA_VERSION,
    EvidenceLedger,
    EvidenceLedgerEntry,
    NavigationDecisionType,
    hash_decision_inputs,
)

MISSION = "shadow-run:campaign-b5:2026-10-05T16:00:00Z"
RECORDED_AT = "2026-10-05T16:00:05Z"


def entry_kwargs(**overrides):
    base = {
        "schema_name": EVIDENCE_LEDGER_SCHEMA_NAME,
        "schema_version": EVIDENCE_LEDGER_SCHEMA_VERSION,
        "mission_id": MISSION,
        "decision_type": NavigationDecisionType.SELECTION,
        "decision_label": "shadow-selection",
        "inputs_digest": hash_decision_inputs({"repository": "Blummer92/agent-os"}),
        "reason_codes": ("shadow-selection.current",),
        "provenance_refs": ("scan-source-query:repo=Blummer92/agent-os state=open",),
        "recorded_at": RECORDED_AT,
        "actor": "agent-os-shadow-run/phase0",
        "previous_digest": None,
    }
    base.update(overrides)
    return base


def append_kwargs(**overrides):
    base = {
        "mission_id": MISSION,
        "decision_type": NavigationDecisionType.SELECTION,
        "inputs_digest": hash_decision_inputs({"repository": "Blummer92/agent-os"}),
        "reason_codes": ("shadow-selection.current",),
        "provenance_refs": ("scan-source-query:repo=Blummer92/agent-os state=open",),
        "recorded_at": RECORDED_AT,
        "actor": "agent-os-shadow-run/phase0",
    }
    base.update(overrides)
    return base


def test_genesis_entry_binds_empty_previous_digest() -> None:
    entry = EvidenceLedgerEntry(**entry_kwargs())
    assert entry.previous_digest is None
    assert len(entry.entry_digest) == 64
    assert entry.to_dict()["previous_digest"] == ""


def test_mandated_fields_are_persisted() -> None:
    persisted = EvidenceLedgerEntry(**entry_kwargs()).to_dict()
    assert set(persisted) == {
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
    assert persisted["decision_type"] == "selection"


def test_append_chains_previous_digest() -> None:
    ledger = EvidenceLedger()
    first = ledger.append(**append_kwargs())
    second = first.append(
        **append_kwargs(
            decision_type=NavigationDecisionType.EXECUTION,
            decision_label="governed-execution",
            reason_codes=("execution.authorized",),
        )
    )
    entries = second.entries
    assert len(entries) == 2
    assert entries[0].previous_digest is None
    assert entries[1].previous_digest == entries[0].entry_digest
    assert entries[1].entry_digest != entries[0].entry_digest
    # The original ledger is unchanged: append is immutable.
    assert ledger.entries == ()
    assert first.entries == entries[:1]
    second.verify()


def test_mission_binding_rejects_foreign_mission() -> None:
    ledger = EvidenceLedger().append(**append_kwargs())
    with pytest.raises(ValueError, match="mission-bound"):
        ledger.append(**append_kwargs(mission_id="other-mission"))


def test_verify_detects_tampered_entry() -> None:
    ledger = EvidenceLedger().append(**append_kwargs())
    payload = ledger.entries[0].to_dict()
    payload["reason_codes"] = ["tampered.reason"]
    with pytest.raises(ValueError, match="does not match"):
        EvidenceLedgerEntry.from_dict(payload)


def test_verify_detects_broken_chain_link() -> None:
    first = EvidenceLedgerEntry(**entry_kwargs())
    second = EvidenceLedgerEntry(
        **entry_kwargs(previous_digest="0" * 64, recorded_at="2026-10-05T16:00:06Z")
    )
    with pytest.raises(ValueError, match="chain is broken"):
        EvidenceLedger((first, second))


def test_jsonl_round_trip_preserves_chain() -> None:
    ledger = (
        EvidenceLedger()
        .append(**append_kwargs())
        .append(
            **append_kwargs(
                decision_type=NavigationDecisionType.COMPLETION,
                decision_label="mission-completion",
                reason_codes=("completion.recorded",),
                recorded_at="2026-10-05T16:01:00Z",
            )
        )
    )
    restored = EvidenceLedger.from_jsonl(ledger.to_jsonl())
    assert [entry.entry_digest for entry in restored.entries] == [
        entry.entry_digest for entry in ledger.entries
    ]
    assert restored.mission_id == MISSION
    restored.verify()


def test_from_jsonl_rejects_malformed_line() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        EvidenceLedger.from_jsonl("{not json}\n")


def test_hash_decision_inputs_is_deterministic() -> None:
    first = hash_decision_inputs({"b": 2, "a": 1})
    second = hash_decision_inputs({"a": 1, "b": 2})
    assert first == second
    assert len(first) == 64
    assert hash_decision_inputs({"a": 2}) != first


def test_rejects_empty_reason_codes_and_refs() -> None:
    with pytest.raises((TypeError, ValueError)):
        EvidenceLedgerEntry(**entry_kwargs(reason_codes=()))
    with pytest.raises((TypeError, ValueError)):
        EvidenceLedgerEntry(**entry_kwargs(provenance_refs=()))
    with pytest.raises((TypeError, ValueError)):
        EvidenceLedgerEntry(**entry_kwargs(reason_codes=["not-a-tuple"]))


def test_rejects_unsupported_decision_type_and_schema() -> None:
    with pytest.raises(ValueError, match="decision_type"):
        EvidenceLedgerEntry.from_dict(
            {**EvidenceLedgerEntry(**entry_kwargs()).to_dict(), "decision_type": "napping"}
        )
    with pytest.raises(ValueError, match="schema"):
        EvidenceLedgerEntry(**entry_kwargs(schema_name="something-else"))


def test_selection_execution_completion_share_one_mission_chain() -> None:
    ledger = EvidenceLedger()
    for decision_type, label in (
        (NavigationDecisionType.SELECTION, "shadow-selection"),
        (NavigationDecisionType.EXECUTION, "governed-execution"),
        (NavigationDecisionType.COMPLETION, "mission-completion"),
    ):
        ledger = ledger.append(
            **append_kwargs(decision_type=decision_type, decision_label=label)
        )
    assert [entry.decision_type for entry in ledger.entries] == [
        NavigationDecisionType.SELECTION,
        NavigationDecisionType.EXECUTION,
        NavigationDecisionType.COMPLETION,
    ]
    assert all(entry.mission_id == MISSION for entry in ledger.entries)
    ledger.verify()
