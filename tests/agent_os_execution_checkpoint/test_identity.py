"""Focused tests for scripts/agent_os_execution_checkpoint/identity.py."""
from __future__ import annotations

import hashlib
import json

from scripts.agent_os_execution_checkpoint.identity import (
    CHECKPOINT_ID_DOMAIN,
    REUSE_KEY_DOMAIN,
    RESUME_PLAN_ID_DOMAIN,
    canonical_json_bytes,
    compute_checkpoint_id,
    compute_resume_plan_id,
    compute_reuse_key,
    domain_digest,
)


def test_canonical_json_bytes_is_sorted_compact_and_not_ascii_escaped() -> None:
    payload = {"b": 1, "a": "café", "c": None, "d": True}
    encoded = canonical_json_bytes(payload)
    assert encoded == b'{"a":"caf\xc3\xa9","b":1,"c":null,"d":true}'


def test_canonical_json_bytes_has_no_trailing_newline_or_indent() -> None:
    encoded = canonical_json_bytes({"x": 1})
    assert not encoded.endswith(b"\n")
    assert b" " not in encoded


def test_canonical_json_bytes_matches_exact_adr_0002_call_shape() -> None:
    payload = {"z": 1, "a": 2}
    expected = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert canonical_json_bytes(payload) == expected


def test_domain_digest_is_deterministic() -> None:
    payload = {"a": 1}
    assert domain_digest("agent-os.example", payload) == domain_digest(
        "agent-os.example", payload
    )


def test_domain_digest_differs_across_distinct_domains_for_identical_payload() -> None:
    payload = {"a": 1}
    a = domain_digest(CHECKPOINT_ID_DOMAIN, payload)
    b = domain_digest(REUSE_KEY_DOMAIN, payload)
    c = domain_digest(RESUME_PLAN_ID_DOMAIN, payload)
    assert len({a, b, c}) == 3


def test_domain_digest_has_domain_prefix_and_sixty_four_hex_suffix() -> None:
    value = domain_digest("agent-os.example", {"a": 1})
    domain, _, hex_part = value.partition(":")
    assert domain == "agent-os.example"
    assert len(hex_part) == 64
    int(hex_part, 16)  # raises if not valid hex


def test_compute_checkpoint_id_uses_checkpoint_domain() -> None:
    value = compute_checkpoint_id({"a": 1})
    assert value.startswith(f"{CHECKPOINT_ID_DOMAIN}:")


def test_compute_reuse_key_uses_reuse_key_domain() -> None:
    value = compute_reuse_key({"a": 1})
    assert value.startswith(f"{REUSE_KEY_DOMAIN}:")


def test_compute_resume_plan_id_uses_resume_plan_domain() -> None:
    value = compute_resume_plan_id({"a": 1})
    assert value.startswith(f"{RESUME_PLAN_ID_DOMAIN}:")


def test_domain_digest_changes_for_different_payload_content() -> None:
    a = domain_digest("agent-os.example", {"a": 1})
    b = domain_digest("agent-os.example", {"a": 2})
    assert a != b


def test_collection_ordering_does_not_affect_digest() -> None:
    payload_a = {"items": [1, 2, 3], "name": "x"}
    payload_b = {"name": "x", "items": [1, 2, 3]}
    assert domain_digest("agent-os.example", payload_a) == domain_digest(
        "agent-os.example", payload_b
    )


def test_array_element_order_is_semantic_and_changes_the_digest() -> None:
    a = domain_digest("agent-os.example", {"items": [1, 2, 3]})
    b = domain_digest("agent-os.example", {"items": [3, 2, 1]})
    assert a != b


def test_digest_is_sha256_of_the_documented_material_shape() -> None:
    payload = {"a": 1}
    domain = "agent-os.example"
    expected_material = domain.encode("utf-8") + b":v1\0" + canonical_json_bytes(payload)
    expected = f"{domain}:{hashlib.sha256(expected_material).hexdigest()}"
    assert domain_digest(domain, payload) == expected
