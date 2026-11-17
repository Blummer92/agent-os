"""Fixture/mock candidate providers for #3337 (AN-MR2).

Only fixture/mock providers exist. There is no live provider adapter in this
package and there must never be one: ``LiveModelProvider.run`` raises
``LiveCallRefusedError`` unconditionally, and the runner refuses any provider
that is not a ``MockModelProvider`` before any execution attempt.

Mock transcripts come from two deterministic fixture sources, both loaded
from ``fixtures/mock_transcripts.json``:

- scripted policies: per-candidate per-family competence tiers (0-100) that
  drive a seeded transcript generator. Identical (candidate, packet) inputs
  always produce identical transcripts, so runs are reproducible without
  any provider invocation.
- hand-authored overrides: literal transcripts for specific
  (candidate, packet) pairs, including the negative fixtures
  (authority-bearing output, contaminated run).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .task_packets import TaskPacket

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_TRANSCRIPTS_PATH = _FIXTURES_DIR / "mock_transcripts.json"
TRANSCRIPT_SEED_DOMAIN = "mock-transcript:v1"


class LiveCallRefusedError(RuntimeError):
    """A live provider call was attempted or configured. Fails closed."""


class ProviderError(ValueError):
    """A provider fixture or identity is malformed."""


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    """A candidate model x reasoning-setting identity.

    Names are requested benchmark candidates from #3337, not assertions of
    current availability, provider mapping, supported settings, or relative
    strength. ``capabilities_unknown`` marks identities (Muse) whose
    capabilities are explicitly unqualified until canonical provider /
    runtime / model / tool evidence exists.
    """

    identity_id: str
    model_name: str
    reasoning_setting: str
    provider: str
    availability: str
    capabilities_unknown: bool


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """One deterministic mock transcript for one packet."""

    packet_id: str
    identity_id: str
    output_fields: Mapping[str, str]
    claims: tuple[str, ...]
    latency_ms_fixture: int
    tokens_fixture: int
    contaminated: bool
    transcript_digest: str


def _roll(*parts: str, modulus: int = 100) -> int:
    digest = hashlib.sha256(
        (f"{TRANSCRIPT_SEED_DOMAIN}\0" + "|".join(parts)).encode("utf-8")
    ).hexdigest()
    return int(digest, 16) % modulus


def _transcript_digest(identity_id: str, packet_id: str, output_fields: Mapping[str, str]) -> str:
    material = json.dumps(
        {"identity_id": identity_id, "packet_id": packet_id, "output_fields": dict(output_fields)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(f"{TRANSCRIPT_SEED_DOMAIN}\0{material}".encode("utf-8")).hexdigest()
    return f"mock-transcript:{digest}"


def _expected_text(field_kind: str, expected: Any) -> str:
    if field_kind == "keyset":
        return " ".join(str(item) for item in expected)
    return str(expected)


def _wrong_text(field_kind: str, expected: Any, packet_id: str, field_name: str) -> str:
    """Deterministic wrong answer: drops one keyword (keyset) or a marker (exact)."""
    if field_kind == "keyset":
        keywords = [str(item) for item in expected]
        drop = _roll(packet_id, field_name, "drop", modulus=len(keywords))
        kept = [keyword for index, keyword in enumerate(keywords) if index != drop]
        return " ".join(kept) if kept else "no-answer"
    return "WRONG_ANSWER"


def scripted_transcript(
    identity_id: str, competence: int, packet: TaskPacket
) -> ProviderObservation:
    """Deterministically generate a mock transcript from a competence tier."""
    output_fields: dict[str, str] = {}
    claims: list[str] = []
    for field in packet.scored_fields:
        roll = _roll(identity_id, packet.packet_id, field.name)
        if roll < competence:
            text = _expected_text(field.kind, field.expected)
        else:
            text = _wrong_text(field.kind, field.expected, packet.packet_id, field.name)
        output_fields[field.name] = text
        claims.extend(text.split())
    latency_ms = 150 + _roll(identity_id, packet.packet_id, "latency", modulus=2850)
    tokens = 50 + _roll(identity_id, packet.packet_id, "tokens", modulus=3950)
    return ProviderObservation(
        packet_id=packet.packet_id,
        identity_id=identity_id,
        output_fields=output_fields,
        claims=tuple(claims),
        latency_ms_fixture=latency_ms,
        tokens_fixture=tokens,
        contaminated=False,
        transcript_digest=_transcript_digest(identity_id, packet.packet_id, output_fields),
    )


@dataclass(frozen=True, slots=True)
class ScriptedTranscriptPolicy:
    """Per-candidate scripted transcript policy loaded from fixtures."""

    identity_id: str
    family_competence: Mapping[str, int]
    unsupported_settings: tuple[str, ...]
    overrides: Mapping[str, dict[str, Any]]

    def competence_for(self, family: str) -> int:
        try:
            return self.family_competence[family]
        except KeyError:
            raise ProviderError(
                f"policy for {self.identity_id} has no competence tier for family {family}"
            ) from None

    def transcript(self, identity: CandidateIdentity, packet: TaskPacket) -> ProviderObservation:
        override_key = f"{identity.identity_id}|{packet.packet_id}"
        override = self.overrides.get(override_key)
        if override is not None:
            output_fields = {name: str(value) for name, value in override["output_fields"].items()}
            claims: list[str] = []
            for text in output_fields.values():
                claims.extend(text.split())
            return ProviderObservation(
                packet_id=packet.packet_id,
                identity_id=identity.identity_id,
                output_fields=output_fields,
                claims=tuple(claims),
                latency_ms_fixture=int(override.get("latency_ms_fixture", 500)),
                tokens_fixture=int(override.get("tokens_fixture", 300)),
                contaminated=bool(override.get("contaminated", False)),
                transcript_digest=_transcript_digest(
                    identity.identity_id, packet.packet_id, output_fields
                ),
            )
        return scripted_transcript(
            identity.identity_id, self.competence_for(packet.family.value), packet
        )


class MockModelProvider:
    """Fixture-only provider: replays deterministic mock transcripts.

    ``run`` performs zero network I/O. Wall-clock latency measured around it
    is pure local execution time.
    """

    def __init__(self, identity: CandidateIdentity, policy: ScriptedTranscriptPolicy) -> None:
        if identity.identity_id != policy.identity_id:
            raise ProviderError("identity and policy identity_id do not match")
        self._identity = identity
        self._policy = policy

    @property
    def identity(self) -> CandidateIdentity:
        return self._identity

    def run(self, packet: TaskPacket) -> ProviderObservation:
        if type(packet) is not TaskPacket:
            raise TypeError("packet must be a TaskPacket")
        return self._policy.transcript(self._identity, packet)


class LiveModelProvider:
    """Placeholder that fails closed: live execution is never permitted."""

    def __init__(self, identity: CandidateIdentity) -> None:
        self._identity = identity

    @property
    def identity(self) -> CandidateIdentity:
        return self._identity

    def run(self, packet: TaskPacket) -> ProviderObservation:
        raise LiveCallRefusedError(
            f"live provider execution refused for {self._identity.identity_id}: "
            "the #3337 harness is offline-only and holds no credentials"
        )


def _load_transcript_fixtures(path: str | Path = _TRANSCRIPTS_PATH) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"cannot load transcript fixtures: {exc}") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ProviderError("transcript schema_version must be '1.0'")
    return raw


def load_candidates(path: str | Path = _TRANSCRIPTS_PATH) -> dict[str, CandidateIdentity]:
    """Load the requested #3337 candidate identities (fixture metadata only)."""
    raw = _load_transcript_fixtures(path)
    candidates: dict[str, CandidateIdentity] = {}
    for item in raw.get("candidates", ()):
        identity = CandidateIdentity(
            identity_id=item["identity_id"],
            model_name=item["model_name"],
            reasoning_setting=item["reasoning_setting"],
            provider=item["provider"],
            availability=item.get("availability", "unknown"),
            capabilities_unknown=bool(item.get("capabilities_unknown", False)),
        )
        if identity.identity_id in candidates:
            raise ProviderError(f"duplicate candidate {identity.identity_id}")
        candidates[identity.identity_id] = identity
    if not candidates:
        raise ProviderError("candidate list is empty")
    return candidates


def load_policies(path: str | Path = _TRANSCRIPTS_PATH) -> dict[str, ScriptedTranscriptPolicy]:
    """Load scripted transcript policies for every candidate."""
    raw = _load_transcript_fixtures(path)
    overrides: dict[str, dict[str, Any]] = raw.get("overrides", {})
    policies: dict[str, ScriptedTranscriptPolicy] = {}
    for identity_id, entry in raw.get("scripted_policies", {}).items():
        policies[identity_id] = ScriptedTranscriptPolicy(
            identity_id=identity_id,
            family_competence={
                key: int(value)
                for key, value in entry.items()
                if key != "unsupported_settings"
            },
            unsupported_settings=tuple(entry.get("unsupported_settings", ())),
            overrides={
                key: value for key, value in overrides.items() if key.startswith(identity_id + "|")
            },
        )
    return policies


def provider_for(
    identity_id: str,
    candidates: dict[str, CandidateIdentity] | None = None,
    policies: dict[str, ScriptedTranscriptPolicy] | None = None,
) -> MockModelProvider:
    """Build the fixture-only provider for a candidate identity."""
    candidates = candidates if candidates is not None else load_candidates()
    policies = policies if policies is not None else load_policies()
    try:
        identity = candidates[identity_id]
        policy = policies[identity_id]
    except KeyError:
        raise ProviderError(f"unknown candidate identity {identity_id}") from None
    return MockModelProvider(identity, policy)
