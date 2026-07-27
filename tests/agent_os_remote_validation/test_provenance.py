from __future__ import annotations

import ast
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from scripts.agent_os_remote_validation import (
    DispatchEvidence,
    ExpectedProvenanceIdentity,
    NormalizedVerificationReceipt,
    ProvenanceVerificationResult,
    build_compute_evidence_summary,
    compute_command_set_digest,
    evaluate_dispatch_decision,
    provenance_verification_id,
    serialize_provenance_verification,
    to_supplied_compute_record,
    validation_plan_id,
    verify_remote_validation_provenance,
)
from scripts.agent_os_remote_validation import provenance as provenance_module
from scripts.agent_os_remote_validation.models import ValidationPlan

HEAD_SHA = "a" * 40
OTHER_SHA = "b" * 40
COMMANDS = ("python -m pytest -q tests/agent_os_remote_validation",)
SELECTOR_VERSION = "1.0.0"
DIGEST = compute_command_set_digest(SELECTOR_VERSION, COMMANDS)
ROOT = "github-oidc:blummer92/agent-os"
EVALUATED_AT = "2026-07-27T18:00:00Z"


def _plan(**overrides: object) -> ValidationPlan:
    values = {
        "selector_version": SELECTOR_VERSION,
        "repository": "Blummer92/agent-os",
        "pull_request": 666,
        "base_sha": "c" * 40,
        "head_sha": HEAD_SHA,
        "profile": "focused",
        "commands": COMMANDS,
        "command_set_digest": DIGEST,
        "reason_codes": ("profile.focused-package",),
        "remote_build_required": True,
    }
    values.update(overrides)
    return ValidationPlan(**values)


def _decision(plan: ValidationPlan | None = None):
    plan = plan or _plan()
    return evaluate_dispatch_decision(
        plan,
        (),
        current_pr_head_sha=plan.head_sha,
    )


def _expected_provenance() -> ExpectedProvenanceIdentity:
    return ExpectedProvenanceIdentity(
        evidence_source="cloud-build:builds.get",
        producer_identity="service-account:validation-verifier",
        provider="google-cloud-build",
        provider_account="project:agent-os-validation",
        provider_location="global",
        trigger_identity="trigger:agent-os-pr-validation",
    )


def _receipt(**overrides: object) -> NormalizedVerificationReceipt:
    plan = _plan()
    decision = _decision(plan)
    values = {
        "schema_name": "agent-os-validation-provenance-receipt",
        "schema_version": "1.0",
        "receipt_id": "receipt:build-666-1",
        "proof_type": "provider-api",
        "proof_verified": True,
        "proof_digest": "d" * 64,
        "trust_root_id": ROOT,
        "verifier_id": "cloud-build-verifier:v1",
        "evidence_source": "cloud-build:builds.get",
        "producer_identity": "service-account:validation-verifier",
        "provider": "google-cloud-build",
        "provider_account": "project:agent-os-validation",
        "provider_location": "global",
        "repository": plan.repository,
        "pull_request": plan.pull_request,
        "tested_sha": plan.head_sha,
        "profile": plan.profile,
        "selector_version": plan.selector_version,
        "command_set_digest": plan.command_set_digest,
        "plan_id": validation_plan_id(plan),
        "dispatch_decision_id": decision.decision_id,
        "build_id": "build-666-1",
        "trigger_identity": "trigger:agent-os-pr-validation",
        "terminal_status": "succeeded",
        "evidence_created_at": "2026-07-27T17:00:00Z",
        "retrieved_at": "2026-07-27T17:05:00Z",
        "expires_at": "2026-07-27T19:00:00Z",
        "replay_id": "delivery:build-666-1",
        "machine_type": "e2-standard-2",
        "elapsed_seconds": 91,
    }
    values.update(overrides)
    return NormalizedVerificationReceipt(**values)


def _verify(
    receipt: NormalizedVerificationReceipt | None = None,
    **overrides: object,
) -> ProvenanceVerificationResult:
    values = {
        "validation_plan": _plan(),
        "dispatch_decision": _decision(),
        "supplied_receipts": (() if receipt is None else (receipt,)),
        "current_head_sha": HEAD_SHA,
        "expected_provenance_identity": _expected_provenance(),
        "approved_trust_roots": (ROOT,),
        "approved_verifiers": ("cloud-build-verifier:v1",),
        "seen_replay_ids": (),
        "evaluation_time": EVALUATED_AT,
    }
    values.update(overrides)
    return verify_remote_validation_provenance(**values)


def test_verified_receipt_is_canonical_and_projects_into_unchanged_compute_contract():
    plan = _plan()
    decision = _decision(plan)
    receipt = _receipt()
    result = verify_remote_validation_provenance(
        plan,
        decision,
        (receipt,),
        current_head_sha=HEAD_SHA,
        expected_provenance_identity=_expected_provenance(),
        approved_trust_roots=(ROOT,),
        approved_verifiers=("cloud-build-verifier:v1",),
        seen_replay_ids=(),
        evaluation_time=EVALUATED_AT,
    )

    assert result.state == "verified"
    assert result.reason_codes == ("proof.verified",)
    assert provenance_verification_id(result) == result.verification_id
    assert serialize_provenance_verification(result)["state"] == "verified"

    compute_record = to_supplied_compute_record(result, decision)
    summary = build_compute_evidence_summary(plan, (compute_record,))
    assert summary.status == "within-policy"
    assert summary.remote_builds_triggered == 1
    assert summary.build_ids == (receipt.build_id,)
    assert summary.elapsed_seconds == 91


def test_missing_receipt_is_visibly_unverified():
    result = _verify()
    assert result.state == "unverified"
    assert result.reason_codes == ("receipt.missing",)


def test_false_proof_flag_is_unverified_not_presence_triggered_manual_review():
    result = _verify(_receipt(proof_verified=False))
    assert result.state == "unverified"
    assert result.reason_codes == ("proof.not-verified",)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("repository", "other/repo", "identity.repository"),
        ("pull_request", 667, "identity.pull-request"),
        ("tested_sha", OTHER_SHA, "identity.tested-sha"),
        ("profile", "aggregate", "identity.profile"),
        ("selector_version", "2.0.0", "identity.selector-version"),
        ("command_set_digest", "e" * 64, "identity.command-set-digest"),
        ("plan_id", "validation-plan:" + "f" * 64, "identity.plan-id"),
        (
            "dispatch_decision_id",
            "validation-dispatch-decision:" + "1" * 64,
            "identity.dispatch-decision-id",
        ),
    ],
)
def test_exact_identity_mismatches_fail_closed(field: str, value: object, reason: str):
    result = _verify(_receipt(**{field: value}))
    assert result.state == "identity-mismatch"
    assert reason in result.reason_codes


def test_moved_current_head_and_expired_receipt_are_stale():
    moved = _verify(_receipt(), current_head_sha=OTHER_SHA)
    expired = _verify(
        _receipt(expires_at="2026-07-27T17:30:00Z"),
        evaluation_time=EVALUATED_AT,
    )
    assert moved.state == "stale"
    assert moved.reason_codes == ("head.stale",)
    assert expired.state == "stale"
    assert expired.reason_codes == ("receipt.expired",)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"proof_type": "unknown-proof"}, "proof.type"),
        ({"trust_root_id": "unknown-root"}, "proof.trust-root"),
        ({"verifier_id": "unknown-verifier:v1"}, "proof.verifier"),
    ],
)
def test_unknown_proof_or_trust_root_is_unsupported(overrides: dict[str, object], reason: str):
    result = _verify(_receipt(**overrides))
    assert result.state == "unsupported"
    assert result.reason_codes == (reason,)


def test_replay_identifier_in_caller_supplied_seen_set_requires_manual_review():
    receipt = _receipt()
    result = _verify(receipt, seen_replay_ids=(receipt.replay_id,))
    assert result.state == "manual-review"
    assert result.reason_codes == ("receipt.replay-detected",)


def test_provider_identity_mismatch_fails_closed():
    expected = replace(_expected_provenance(), provider_account="project:other")
    result = _verify(_receipt(), expected_provenance_identity=expected)
    assert result.state == "identity-mismatch"
    assert result.reason_codes == ("identity.provider-account",)


def test_duplicate_and_multiple_receipts_require_manual_review():
    first = _receipt()
    duplicate = replace(first)
    result = _verify(
        supplied_receipts=(first, duplicate),
    )
    assert result.state == "manual-review"
    assert "receipts.multiple" in result.reason_codes
    assert "receipts.duplicate-receipt-id" in result.reason_codes
    assert "receipts.duplicate-replay-id" in result.reason_codes


def test_malformed_secret_bearing_and_oversized_receipts_require_manual_review():
    malformed = _verify(_receipt(proof_digest="bad"))
    secret = _verify(_receipt(evidence_source="authorization: bearer abcdefghijk"))
    oversized = _verify(_receipt(producer_identity="x" * 5000))
    assert malformed.state == "manual-review"
    assert "receipt.proof-digest" in malformed.reason_codes
    assert secret.state == "manual-review"
    assert "receipt.evidence-source" in secret.reason_codes
    assert oversized.state == "manual-review"
    assert "receipt.producer-identity" in oversized.reason_codes


def test_timestamp_order_and_future_retrieval_require_manual_review():
    reversed_time = _verify(
        _receipt(
            evidence_created_at="2026-07-27T17:10:00Z",
            retrieved_at="2026-07-27T17:05:00Z",
        )
    )
    future = _verify(
        _receipt(retrieved_at="2026-07-27T18:30:00Z", expires_at="2026-07-27T19:00:00Z")
    )
    assert reversed_time.state == "manual-review"
    assert "receipt.timestamp-order" in reversed_time.reason_codes
    assert future.state == "manual-review"
    assert "receipt.retrieval-in-future" in future.reason_codes


def test_tampered_dispatch_contract_requires_manual_review():
    decision = replace(_decision(), repository="other/repo")
    result = _verify(dispatch_decision=decision)
    assert result.state == "manual-review"
    assert "decision.invalid" in result.reason_codes
    assert "decision.repository" in result.reason_codes


def test_trust_root_order_does_not_change_result_or_semantic_id():
    roots_a = (ROOT, "github-attestation:blummer92/agent-os")
    roots_b = tuple(reversed(roots_a))
    first = _verify(_receipt(), approved_trust_roots=roots_a)
    second = _verify(_receipt(), approved_trust_roots=roots_b)
    assert first == second
    assert first.verification_id == second.verification_id


def test_result_is_frozen_non_authorizing_and_serializer_detects_tampering():
    result = _verify(_receipt())
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.side_effects_performed is False
    with pytest.raises(FrozenInstanceError):
        result.state = "manual-review"  # type: ignore[misc]
    with pytest.raises(ValueError, match="ID mismatch"):
        serialize_provenance_verification(replace(result, state="manual-review"))


def test_compute_projection_rejects_unverified_or_mismatched_results():
    unverified = _verify(_receipt(proof_verified=False))
    with pytest.raises(ValueError, match="only verified"):
        to_supplied_compute_record(unverified, _decision())

    verified = _verify(_receipt())
    other_plan = _plan(head_sha=OTHER_SHA)
    other_decision = _decision(other_plan)
    with pytest.raises(ValueError, match="dispatch decision ID mismatch"):
        to_supplied_compute_record(verified, other_decision)


def test_compute_projection_rejects_verified_reuse_as_a_new_build():
    plan = _plan()
    evidence = DispatchEvidence(
        record_id="prior-success",
        validation_plan=plan,
        attempt=0,
        state="succeeded",
    )
    reused = evaluate_dispatch_decision(
        plan,
        (evidence,),
        current_pr_head_sha=plan.head_sha,
    )
    receipt = _receipt(dispatch_decision_id=reused.decision_id)
    verified = _verify(receipt, dispatch_decision=reused)
    assert verified.state == "verified"
    with pytest.raises(ValueError, match="launch-eligible"):
        to_supplied_compute_record(verified, reused)


def test_schema_is_closed_portable_structure_only_and_matches_receipt_contract():
    schema_path = Path(provenance_module.__file__).with_name("provenance_input.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert "errorMessage" not in json.dumps(schema)
    assert schema["properties"]["proof_verified"] == {"type": "boolean"}
    assert set(schema["properties"]["proof_type"]["enum"]) == {
        "provider-api",
        "signed-envelope",
        "attestation",
    }
    assert set(schema["required"]) == set(schema["properties"])


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
