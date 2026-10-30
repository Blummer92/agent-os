"""CR-7 (#3725, parent #3690): canonical JSON encoder consolidation regressions.

The four duplicate ``_canonical_bytes`` implementations and the duplicate
cost-evidence ``_semantic_digest`` were deleted; the modules now reuse the
existing canonical owners directly. Expected values below are computed
independently from stdlib ``json``/``hashlib`` — never from the consolidated
functions themselves — so a regression in the owner is caught, not mirrored.

Preserved policies (do not merge):
- Ordinary encoder: ``sort_keys, separators=(",", ":"), ensure_ascii=False``,
  UTF-8, default ``allow_nan`` (NaN/Infinity serialize).
- Strict encoder: same, plus ``allow_nan=False`` (NaN/Infinity raise ValueError).
- Distinct strictness elsewhere is intentionally NOT consolidated:
  ``advisory_gate._semantic_digest`` (strict bytes) vs
  ``evidence_bundle._semantic_digest`` (ordinary bytes) still differ on NaN.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts.agent_os_remote_validation import (
    advisory_gate,
    advisory_render,
    cost_evidence,
    dispatch_guard,
    evidence_bundle,
    selector,
)

CORPUS: list[dict[str, object]] = [
    {"b": 1, "a": [1, 2, {"z": "üñïçødé ☃"}]},
    {"x": {"nested": {"deep": [True, None, 3.5, -0.0]}}},
    {},
    {"empty_str": "", "empty_list": [], "empty_dict": {}},
    {"float": 1e300, "neg": -2.5, "int": 10**30},
    {"emoji": "🚀", "cjk": "日本語", "key": "välue"},
]

ORDINARY_MODULES = (
    selector,
    dispatch_guard,
    evidence_bundle,
    cost_evidence,
)


def ordinary_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def strict_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@pytest.mark.parametrize("payload", CORPUS)
def test_ordinary_encoders_match_independent_oracle(payload: dict[str, object]) -> None:
    expected = ordinary_bytes(payload)
    for module in ORDINARY_MODULES:
        assert module._canonical_bytes(payload) == expected


def test_ordinary_encoders_are_the_selector_owner() -> None:
    for module in (dispatch_guard, evidence_bundle, cost_evidence):
        assert module._canonical_bytes is selector._canonical_bytes
        assert module._canonical_bytes.__module__.endswith(".selector")


@pytest.mark.parametrize("payload", CORPUS)
def test_strict_encoders_match_independent_oracle(payload: dict[str, object]) -> None:
    expected = strict_bytes(payload)
    assert advisory_gate._canonical_bytes(payload) == expected
    assert advisory_render._canonical_bytes(payload) == expected


def test_strict_encoders_are_the_advisory_gate_owner() -> None:
    assert advisory_render._canonical_bytes is advisory_gate._canonical_bytes
    assert advisory_render._canonical_bytes.__module__.endswith(".advisory_gate")


@pytest.mark.parametrize("bad", [{"v": float("nan")}, {"v": float("inf")}, {"v": float("-inf")}])
def test_strict_encoders_reject_non_finite(bad: dict[str, object]) -> None:
    for module in (advisory_gate, advisory_render):
        with pytest.raises(ValueError, match="not JSON compliant"):
            module._canonical_bytes(bad)


@pytest.mark.parametrize("bad", [{"v": float("nan")}, {"v": float("inf")}, {"v": float("-inf")}])
def test_ordinary_encoder_policy_unchanged_on_non_finite(bad: dict[str, object]) -> None:
    # Ordinary policy intentionally still serializes (default allow_nan).
    for module in ORDINARY_MODULES:
        assert module._canonical_bytes(bad) == ordinary_bytes(bad)


def test_cost_semantic_digest_is_the_dispatch_guard_owner() -> None:
    assert cost_evidence._semantic_digest is dispatch_guard._semantic_digest
    assert cost_evidence._semantic_digest.__module__.endswith(".dispatch_guard")


@pytest.mark.parametrize("payload", CORPUS[:3])
def test_semantic_digest_matches_independent_oracle(payload: dict[str, object]) -> None:
    domain = "agent-os-test-domain:v1"
    expected = hashlib.sha256(
        domain.encode("ascii") + b"\0" + ordinary_bytes(payload)
    ).hexdigest()
    assert dispatch_guard._semantic_digest(domain, payload) == expected
    assert cost_evidence._semantic_digest(domain, payload) == expected


def test_kept_semantic_digests_still_differ_on_non_finite() -> None:
    # Guard for the deliberately NOT-consolidated pair: advisory_gate uses strict
    # bytes, evidence_bundle uses ordinary bytes. Finite inputs agree; NaN does not.
    payload = {"v": float("nan")}
    assert evidence_bundle._semantic_digest("agent-os-test:v1", payload) == (
        hashlib.sha256(
            b"agent-os-test:v1\0" + ordinary_bytes(payload)
        ).hexdigest()
    )
    with pytest.raises(ValueError, match="not JSON compliant"):
        advisory_gate._semantic_digest("agent-os-test:v1", payload)


def test_size_limit_boundary_uses_consolidated_bytes() -> None:
    # Canonical length of {"v": "x"*n} is exactly n + 8 bytes. The size checks
    # reject only when length EXCEEDS the module maximum, so n = MAX - 8 is
    # allowed and n = MAX - 7 is over. This pins the encoder/limit pairing.
    cases = (
        (advisory_render, advisory_render.MAX_RENDER_SERIALIZED_BYTES),
        (dispatch_guard, dispatch_guard.MAX_DISPATCH_SERIALIZED_BYTES),
        (evidence_bundle, evidence_bundle.MAX_BUNDLE_SERIALIZED_BYTES),
        (cost_evidence, cost_evidence.MAX_COMPUTE_SERIALIZED_BYTES),
    )
    for module, maximum in cases:
        at_limit = {"v": "x" * (maximum - 8)}
        over_limit = {"v": "x" * (maximum - 7)}
        assert len(module._canonical_bytes(at_limit)) == maximum
        assert len(module._canonical_bytes(over_limit)) == maximum + 1
