"""Focused canonical reconstruction tests for Issue #1935."""
from __future__ import annotations

import json

import pytest

from scripts.agent_os_remote_validation.evidence_bundle import (
    reconstruct_validation_evidence_bundle,
    serialize_validation_evidence_bundle,
)
from tests.agent_os_remote_validation.test_evidence_bundle import _build


def test_canonical_bundle_reconstructs_exactly() -> None:
    bundle = _build()
    payload = serialize_validation_evidence_bundle(bundle)
    rebuilt = reconstruct_validation_evidence_bundle(payload)
    assert rebuilt == bundle
    assert serialize_validation_evidence_bundle(rebuilt) == payload


def test_bundle_reconstruction_rejects_unknown_fields_and_authority() -> None:
    payload = serialize_validation_evidence_bundle(_build())

    unknown = json.loads(json.dumps(payload))
    unknown["surprise"] = "nope"
    with pytest.raises(ValueError, match="fields drifted"):
        reconstruct_validation_evidence_bundle(unknown)

    authority = json.loads(json.dumps(payload))
    authority["execution_authorized"] = True
    with pytest.raises(ValueError, match="must remain false"):
        reconstruct_validation_evidence_bundle(authority)


def test_bundle_reconstruction_rejects_nested_identity_tamper() -> None:
    payload = serialize_validation_evidence_bundle(_build())

    result_tamper = json.loads(json.dumps(payload))
    result_tamper["command_results"][0]["result_id"] = "command-result:" + "0" * 64
    with pytest.raises(ValueError, match="command_result identity mismatch"):
        reconstruct_validation_evidence_bundle(result_tamper)

    bundle_tamper = json.loads(json.dumps(payload))
    bundle_tamper["bundle_id"] = "validation-evidence-bundle:" + "0" * 64
    with pytest.raises(ValueError, match="bundle ID mismatch"):
        reconstruct_validation_evidence_bundle(bundle_tamper)


def test_bundle_reconstruction_rejects_noncanonical_nested_plan() -> None:
    payload = serialize_validation_evidence_bundle(_build())
    malformed = json.loads(json.dumps(payload))
    malformed["validation_plan"]["commands"].append("python -m pytest unexpected")
    with pytest.raises(ValueError):
        reconstruct_validation_evidence_bundle(malformed)
