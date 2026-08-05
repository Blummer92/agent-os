from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_remote_validation import (
    EvidenceApplicabilityProjection,
    ExpectedEvidenceIdentity,
    NormalizedRemoteValidationEvidence,
    ProvenanceInputError,
    ProvenanceVerificationResult,
    evidence_applicability_id,
    project_evidence_applicability,
    provenance_verification_id,
    serialize_evidence_applicability,
    serialize_provenance_verification,
    verify_remote_validation_provenance,
)
from scripts.agent_os_remote_validation import provenance as provenance_module

HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40
DIGEST = "c" * 64
PLAN_ID = "validation-plan:" + "1" * 64
DECISION_ID = "validation-dispatch-decision:" + "2" * 64
ROOT = "github-oidc:blummer92/agent-os"
VERIFIER = "cloud-build-verifier:v1"
EVALUATED_AT = "2026-07-27T18:00:00Z"


def _evidence(**overrides: object) -> NormalizedRemoteValidationEvidence:
    values = {
        "schema_name": "agent-os-remote-validation-evidence",
        "schema_version": "1.0",
        "evidence_id": "evidence:build-666-1",
        "source_type": "provider-api",
        "repository": "Blummer92/agent-os",
        "pull_request": 666,
        "head_sha": HEAD_SHA,
        "profile": "focused",
        "selector_version": "1.0.0",
        "command_set_digest": DIGEST,
        "plan_id": PLAN_ID,
        "dispatch_decision_id": DECISION_ID,
        "build_id": "build-666-1",
        "provider": "google-cloud-build",
        "producer_identity": "service-account:validation-verifier",
        "trigger_identity": "trigger:agent-os-pr-validation",
        "terminal_status": "succeeded",
        "retrieved_at": "2026-07-27T17:05:00Z",
        "expires_at": "2026-07-27T19:00:00Z",
        "verifier_id": VERIFIER,
        "trust_root_id": ROOT,
        "proof_verified": True,
        "proof_digest": "d" * 64,
    }
    values.update(overrides)
    return NormalizedRemoteValidationEvidence(**values)


def _expected(**overrides: object) -> ExpectedEvidenceIdentity:
    values = {
        "repository": "Blummer92/agent-os",
        "pull_request": 666,
        "head_sha": HEAD_SHA,
        "plan_id": PLAN_ID,
        "dispatch_decision_id": DECISION_ID,
        "provider": "google-cloud-build",
        "producer_identity": "service-account:validation-verifier",
        "trigger_identity": "trigger:agent-os-pr-validation",
    }
    values.update(overrides)
    return ExpectedEvidenceIdentity(**values)


def _verify(evidence: tuple[NormalizedRemoteValidationEvidence, ...] | None = None, **overrides: object):
    values = {
        "evidence": (_evidence(),) if evidence is None else evidence,
        "expected_identity": _expected(),
        "approved_trust_roots": (ROOT,),
        "approved_verifiers": (VERIFIER,),
        "evaluation_time": EVALUATED_AT,
        "seen_evidence_ids": (),
    }
    values.update(overrides)
    return verify_remote_validation_provenance(**values)


def _applicability(evidence: tuple[NormalizedRemoteValidationEvidence, ...] | None = None, **overrides: object):
    values = {
        "evidence": (_evidence(),) if evidence is None else evidence,
        "expected_identity": _expected(),
        "evaluation_time": EVALUATED_AT,
        "seen_evidence_ids": (),
    }
    values.update(overrides)
    return project_evidence_applicability(**values)


# --- exact verified identity and fresh-and-applicable evidence ---


def test_verified_receipt_is_go_and_fresh_and_applicable():
    result = _verify()
    assert result.disposition == "GO"
    assert result.trust == "verified"
    assert result.reason_codes == ("evidence-verified",)
    projection = _applicability()
    assert projection.applicability == "fresh-and-applicable"
    assert projection.reason_codes == ("evidence-fresh-and-applicable",)
    assert projection.authorizes_check_skip is False


def test_verification_id_and_applicability_id_are_stable_and_serializer_agrees():
    result = _verify()
    assert provenance_verification_id(result) == result.verification_id
    assert serialize_provenance_verification(result)["disposition"] == "GO"
    projection = _applicability()
    assert evidence_applicability_id(projection) == projection.applicability_id
    assert serialize_evidence_applicability(projection)["applicability"] == "fresh-and-applicable"


# --- ordinary metadata remaining unverified ---


def test_ordinary_supplied_metadata_cannot_exceed_unverified():
    ordinary = _evidence(
        source_type="supplied-metadata",
        verifier_id=None,
        trust_root_id=None,
        proof_verified=None,
        proof_digest=None,
    )
    result = _verify((ordinary,))
    assert result.trust == "unverified"
    assert result.disposition == "NEEDS-DECISION"
    assert "producer-unverified" in result.reason_codes

    projection = _applicability((ordinary,))
    assert projection.applicability == "incomplete"
    assert "evidence-incomplete" in projection.reason_codes


def test_unverified_proof_flag_is_needs_decision_not_identity_mismatch():
    result = _verify((_evidence(proof_verified=False),))
    assert result.trust == "unverified"
    assert result.disposition == "NEEDS-DECISION"
    assert result.reason_codes == ("signature-unverified",)


# --- missing identity dimensions (empty evidence) ---


def test_empty_evidence_is_unverified_and_incomplete():
    result = _verify(())
    assert result.trust == "unverified"
    assert result.disposition == "NEEDS-DECISION"
    assert result.reason_codes == ("evidence-empty",)
    projection = _applicability(())
    assert projection.applicability == "incomplete"
    assert projection.reason_codes == ("evidence-empty",)


# --- wrong repository, PR, head, plan, dispatch, build, provider, trigger, signer ---


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("repository", "other/repo", "repository-mismatch"),
        ("pull_request", 667, "pull-request-mismatch"),
        ("plan_id", "validation-plan:" + "9" * 64, "plan-mismatch"),
        ("dispatch_decision_id", "validation-dispatch-decision:" + "8" * 64, "dispatch-mismatch"),
        ("provider", "other-provider", "provider-mismatch"),
        ("producer_identity", "service-account:other", "signer-mismatch"),
        ("trigger_identity", "trigger:other", "trigger-mismatch"),
    ],
)
def test_exact_identity_mismatches_fail_closed(field: str, value: object, reason: str):
    result = _verify((_evidence(**{field: value}),))
    assert result.disposition == "NO-GO"
    assert result.trust == "identity-mismatch"
    assert reason in result.reason_codes
    projection = _applicability((_evidence(**{field: value}),))
    assert projection.applicability == "identity-mismatch"
    assert reason in projection.reason_codes


def test_head_sha_mismatch_is_identity_mismatch_when_other_identity_binds():
    result = _verify((_evidence(head_sha=OTHER_SHA),), expected_identity=_expected(head_sha=HEAD_SHA))
    assert result.disposition == "NO-GO"
    assert result.trust == "identity-mismatch"
    assert result.reason_codes == ("head-sha-mismatch",)


def test_build_id_mismatch_against_expected_build_id_fails_closed():
    expected = _expected(build_id="build-666-1")
    result = _verify((_evidence(build_id="build-666-9"),), expected_identity=expected)
    assert result.disposition == "NO-GO"
    assert result.trust == "identity-mismatch"
    assert result.reason_codes == ("build-mismatch",)


# --- stale, incomplete, and expired evidence ---


def test_expired_evidence_is_no_go_and_expired():
    result = _verify((_evidence(expires_at="2026-07-27T17:30:00Z"),))
    assert result.disposition == "NO-GO"
    assert result.trust == "stale"
    assert result.reason_codes == ("evidence-expired",)
    projection = _applicability((_evidence(expires_at="2026-07-27T17:30:00Z"),))
    assert projection.applicability == "expired"


def test_evaluation_before_retrieval_is_stale():
    result = _verify(evaluation_time="2026-07-27T17:00:00Z")
    assert result.disposition == "NO-GO"
    assert result.trust == "stale"
    assert result.reason_codes == ("evidence-stale",)
    projection = _applicability(evaluation_time="2026-07-27T17:00:00Z")
    assert projection.applicability == "stale"


# --- replayed evidence ---


def test_replayed_evidence_id_is_no_go_manual_review():
    evidence = _evidence()
    result = _verify((evidence,), seen_evidence_ids=(evidence.evidence_id,))
    assert result.disposition == "NO-GO"
    assert result.trust == "manual-review"
    assert result.reason_codes == ("evidence-replayed",)
    projection = _applicability((evidence,), seen_evidence_ids=(evidence.evidence_id,))
    assert projection.applicability == "manual-review"


# --- signature or attestation presence without verification ---


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"trust_root_id": "unapproved-root"}, "producer-unverified"),
        ({"verifier_id": "unapproved-verifier:v1"}, "producer-unverified"),
    ],
)
def test_unapproved_trust_root_or_verifier_is_producer_unverified(overrides, reason):
    result = _verify((_evidence(**overrides),))
    assert result.disposition == "NEEDS-DECISION"
    assert result.trust == "unverified"
    assert reason in result.reason_codes


# --- contradictory or mixed evidence; duplicate evidence IDs ---


def test_mixed_evidence_across_items_is_contradictory():
    first = _evidence()
    second = _evidence(evidence_id="evidence:build-666-2", repository="other/repo")
    result = _verify((first, second))
    assert result.disposition == "NO-GO"
    assert result.trust == "manual-review"
    assert result.reason_codes == ("evidence-contradictory",)


def test_duplicate_evidence_ids_within_batch_are_input_invalid():
    first = _evidence()
    duplicate = replace(first)
    result = _verify((first, duplicate))
    assert result.disposition == "NO-GO"
    assert result.reason_codes == ("input-invalid",)


def test_multiple_agreeing_non_contradictory_items_require_manual_review():
    first = _evidence()
    second = _evidence(evidence_id="evidence:build-666-2")
    result = _verify((first, second))
    assert result.disposition == "NEEDS-DECISION"
    assert result.trust == "manual-review"
    assert result.reason_codes == ("manual-review-required",)


# --- empty evidence already covered above; malformed and oversized ---


def test_malformed_and_oversized_construction_is_rejected():
    with pytest.raises(ProvenanceInputError):
        _evidence(head_sha="not-a-sha")
    with pytest.raises(ProvenanceInputError):
        _evidence(producer_identity="x" * 5000)
    with pytest.raises(ProvenanceInputError):
        _evidence(repository="not-owner-slash-name")
    with pytest.raises(ProvenanceInputError):
        _evidence(pull_request=-1)
    with pytest.raises(ProvenanceInputError):
        _evidence(schema_version="9.9")


def test_secret_bearing_value_is_rejected_at_construction():
    with pytest.raises(ProvenanceInputError):
        _evidence(build_id="authorization: bearer abcdefghijklmnop")


def test_partial_envelope_is_rejected_at_construction():
    with pytest.raises(ProvenanceInputError):
        _evidence(trust_root_id=None)


def test_supplied_metadata_with_envelope_is_rejected_at_construction():
    with pytest.raises(ProvenanceInputError):
        _evidence(source_type="supplied-metadata")


def test_proof_type_without_envelope_is_rejected_at_construction():
    with pytest.raises(ProvenanceInputError):
        _evidence(
            source_type="provider-api",
            verifier_id=None,
            trust_root_id=None,
            proof_verified=None,
            proof_digest=None,
        )


def test_unsupported_schema_version_on_verifier_is_needs_decision():
    result = _verify(schema_version="9.9")
    assert result.disposition == "NEEDS-DECISION"
    assert result.trust == "manual-review"
    assert "unsupported-version" in result.reason_codes


# --- input-order independence ---


def test_trust_root_and_verifier_order_does_not_change_result_or_semantic_id():
    roots_a = (ROOT, "github-attestation:blummer92/agent-os")
    roots_b = tuple(reversed(roots_a))
    first = _verify(approved_trust_roots=roots_a)
    second = _verify(approved_trust_roots=roots_b)
    assert first == second
    assert first.verification_id == second.verification_id


# --- deterministic serialization and semantic ID; frozen models ---


def test_result_is_frozen_non_authorizing_and_serializer_detects_tampering():
    result = _verify()
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False
    with pytest.raises(FrozenInstanceError):
        result.trust = "manual-review"  # type: ignore[misc]
    with pytest.raises(ValueError, match="ID mismatch"):
        serialize_provenance_verification(replace(result, trust="manual-review"))


def test_applicability_projection_is_frozen_non_authorizing_and_serializer_detects_tampering():
    projection = _applicability()
    assert projection.authorizes_check_skip is False
    assert projection.execution_authorized is False
    assert projection.side_effects_performed is False
    with pytest.raises(FrozenInstanceError):
        projection.applicability = "manual-review"  # type: ignore[misc]
    with pytest.raises(ValueError, match="ID mismatch"):
        serialize_evidence_applicability(replace(projection, applicability="manual-review"))


def test_evidence_model_is_frozen():
    evidence = _evidence()
    with pytest.raises(FrozenInstanceError):
        evidence.build_id = "other"  # type: ignore[misc]


# --- proof that applicability does not itself authorize execution, merge, or required-check suppression ---


def test_applicability_never_authorizes_execution_merge_or_skip_even_when_fresh():
    projection = _applicability()
    assert projection.applicability == "fresh-and-applicable"
    assert projection.authorizes_check_skip is False
    assert projection.execution_authorized is False
    assert not hasattr(projection, "merge_authorized")


def test_verifier_has_no_network_process_environment_filesystem_or_clock_reads():
    source = inspect.getsource(provenance_module)
    tree = ast.parse(source)
    forbidden_imports = {
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "requests",
        "urllib",
        "http",
        "google",
        "github",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported.isdisjoint(forbidden_imports)
    assert "datetime.now" not in source
    assert "datetime.utcnow" not in source
    assert "open(" not in source
