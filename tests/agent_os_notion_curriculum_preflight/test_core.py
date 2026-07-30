from __future__ import annotations

import ast
import copy
import importlib
import json
import os
import socket
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.agent_os_notion_curriculum_preflight import (
    FINDING_CODES,
    NotionAuthorizationEvidence,
    NotionCurriculumPreflightEvidence,
    PreflightStatus,
    evaluate_notion_curriculum_preflight,
    parse_preflight_evidence,
    serialize_preflight_report,
)
from scripts.agent_os_notion_curriculum_preflight import core as preflight_core

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "agent_os_notion_curriculum_preflight"
    / "valid_preflight.json"
)
EVALUATED_AT = "2026-07-30T17:30:00Z"


def valid_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def evaluate(payload: object, *, evaluated_at: str = EVALUATED_AT):
    return evaluate_notion_curriculum_preflight(payload, evaluated_at=evaluated_at)


def test_valid_compatible_target_is_ready_and_non_authorizing():
    report = evaluate(valid_payload())
    assert report.status is PreflightStatus.READY_FOR_LOCAL_DRAFT_IMPLEMENTATION
    assert not report.reason_codes
    assert not report.blockers
    assert len(report.compatible_mappings) == 4
    assert report.live_access_performed is False
    assert report.side_effects_performed is False
    assert report.write_authorized is False
    assert report.production_authorized is False
    assert report.publication_authorized is False


def test_parse_reconstructs_frozen_slotted_records_without_mutating_input():
    payload = valid_payload()
    before = copy.deepcopy(payload)
    evidence = parse_preflight_evidence(payload)
    assert isinstance(evidence, NotionCurriculumPreflightEvidence)
    assert payload == before
    with pytest.raises(FrozenInstanceError):
        evidence.evidence_id = "changed"
    with pytest.raises(FrozenInstanceError):
        evidence.properties[0].display_name = "changed"


def test_input_order_independence_and_byte_for_byte_serialization():
    first = valid_payload()
    second = valid_payload()
    second["properties"].reverse()
    second["relations"].reverse()
    second["views"].reverse()
    second["contract_mappings"].reverse()
    report_a = evaluate(first)
    report_b = evaluate(second)
    assert report_a.evidence_fingerprint == report_b.evidence_fingerprint
    assert serialize_preflight_report(report_a) == serialize_preflight_report(report_b)
    assert serialize_preflight_report(report_a).encode("utf-8") == serialize_preflight_report(
        report_a
    ).encode("utf-8")


def test_missing_database_identity_blocks_instead_of_using_display_names():
    payload = valid_payload()
    payload["database_id"] = None
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-target-unverified" in report.blockers


def test_database_and_data_source_identity_must_remain_distinct():
    payload = valid_payload()
    payload["data_source_id"] = payload["database_id"]
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-database-data-source-mismatch" in report.blockers


def test_api_version_mismatch_blocks():
    payload = valid_payload()
    payload["notion_api_version"] = "2025-09-03"
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-api-version-mismatch" in report.blockers


def test_contract_version_mismatch_blocks():
    payload = valid_payload()
    payload["contract_version"] = "2.0"
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-contract-version-incompatible" in report.blockers


def test_expired_evidence_requires_manual_review_and_marks_schema_and_view_stale():
    report = evaluate(valid_payload(), evaluated_at="2026-08-01T17:30:00Z")
    assert report.status is PreflightStatus.MANUAL_REVIEW_REQUIRED
    assert "notion-evidence-expired" in report.reason_codes
    assert "notion-schema-stale" in report.reason_codes
    assert "notion-view-stale" in report.view_findings


def test_evaluation_time_before_verification_is_invalid():
    report = evaluate(valid_payload(), evaluated_at="2026-07-30T16:59:59Z")
    assert report.status is PreflightStatus.INVALID
    assert report.reason_codes == ("notion-target-unverified",)


def test_display_name_only_property_identity_blocks():
    payload = valid_payload()
    payload["properties"][1]["property_id"] = None
    payload["contract_mappings"][1]["target_property_id"] = None
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-property-id-missing" in report.blockers


def test_duplicate_property_identity_is_invalid():
    payload = valid_payload()
    payload["properties"][1]["property_id"] = payload["properties"][0]["property_id"]
    report = evaluate(payload)
    assert report.status is PreflightStatus.INVALID
    assert report.reason_codes == ("notion-property-conflict",)


def test_duplicate_display_name_with_different_ids_requires_manual_review():
    payload = valid_payload()
    payload["properties"][1]["display_name"] = payload["properties"][0]["display_name"]
    report = evaluate(payload)
    assert report.status is PreflightStatus.MANUAL_REVIEW_REQUIRED
    assert "notion-property-conflict" in report.reason_codes


def test_property_type_mismatch_blocks_mapping():
    payload = valid_payload()
    payload["contract_mappings"][1]["type_compatible"] = False
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-property-type-mismatch" in report.blockers
    assert report.unsupported_mappings


def test_readiness_owner_conflict_blocks_mapping():
    payload = valid_payload()
    payload["contract_mappings"][0]["owner_compatible"] = False
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-readiness-owner-conflict" in report.blockers
    assert "notion-readiness-owner-conflict" in report.authority_findings


def test_unshared_relation_target_blocks():
    payload = valid_payload()
    payload["relations"][0]["target_shared_with_connection"] = False
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-relation-target-unshared" in report.relation_findings


def test_ambiguous_404_or_access_evidence_requires_manual_review():
    payload = valid_payload()
    payload["relations"][0]["access_state"] = "transient-error"
    payload["relations"][0]["ambiguity_state"] = "unknown"
    report = evaluate(payload)
    assert report.status is PreflightStatus.MANUAL_REVIEW_REQUIRED
    assert "notion-relation-ambiguous" in report.relation_findings


def test_incomplete_pagination_blocks():
    payload = valid_payload()
    payload["limits"]["pagination_complete"] = False
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-pagination-incomplete" in report.limit_findings


def test_unknown_rate_limit_behavior_requires_manual_review():
    payload = valid_payload()
    payload["limits"]["rate_limit_policy_known"] = False
    payload["limits"]["retry_after_supported"] = False
    report = evaluate(payload)
    assert report.status is PreflightStatus.MANUAL_REVIEW_REQUIRED
    assert "notion-rate-limit-policy-unknown" in report.limit_findings


def test_property_value_limit_overflow_blocks():
    payload = valid_payload()
    payload["limits"]["property_value_limit"] = 100
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-value-limit-exceeded" in report.limit_findings


def test_collection_limit_overflow_blocks():
    payload = valid_payload()
    payload["limits"]["collection_limit"] = 1
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-value-limit-exceeded" in report.limit_findings


def test_payload_limit_overflow_blocks():
    payload = valid_payload()
    payload["limits"]["payload_limit"] = 1
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-value-limit-exceeded" in report.limit_findings


def test_unsupported_view_capability_requires_manual_review():
    payload = valid_payload()
    payload["views"][0]["capability_state"] = "unsupported"
    report = evaluate(payload)
    assert report.status is PreflightStatus.MANUAL_REVIEW_REQUIRED
    assert "notion-view-capability-unsupported" in report.view_findings


def test_ambiguous_view_target_requires_manual_review():
    payload = valid_payload()
    payload["views"][0]["view_id"] = None
    report = evaluate(payload)
    assert report.status is PreflightStatus.MANUAL_REVIEW_REQUIRED
    assert "notion-view-target-ambiguous" in report.view_findings


def test_append_only_or_canonical_write_mode_is_not_authorized():
    payload = valid_payload()
    payload["properties"][1]["current_write_mode"] = "append-only"
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-write-mode-not-authorized" in report.authority_findings


def test_governed_field_write_proposal_blocks():
    payload = valid_payload()
    payload["contract_mappings"][0]["projection_mode"] = "owner-governed"
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-governed-field-write-proposed" in report.authority_findings


def test_contradictory_authority_true_is_invalid():
    payload = valid_payload()
    payload["authorization"]["write_authorized"] = True
    report = evaluate(payload)
    assert report.status is PreflightStatus.INVALID
    assert report.reason_codes == ("notion-write-mode-not-authorized",)
    with pytest.raises(Exception):
        NotionAuthorizationEvidence(write_authorized=True)


def test_missing_mapping_target_blocks():
    payload = valid_payload()
    payload["contract_mappings"][1]["target_property_id"] = "missing-property"
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-property-id-missing" in report.blockers
    assert report.missing_mappings


def test_unbounded_projection_blocks():
    payload = valid_payload()
    payload["contract_mappings"][1]["bounded"] = False
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-projection-unbounded" in report.blockers


def test_missing_contract_mapping_blocks_complete_target_claim():
    payload = valid_payload()
    payload["contract_mappings"].pop()
    report = evaluate(payload)
    assert report.status is PreflightStatus.BLOCKED
    assert "notion-target-unverified" in report.blockers
    assert any(item.endswith(":missing") for item in report.missing_mappings)


def test_secret_like_keys_are_rejected_without_echoing_value():
    payload = valid_payload()
    payload["api_key"] = "TOP-SECRET-VALUE"
    report = evaluate(payload)
    rendered = serialize_preflight_report(report)
    assert report.status is PreflightStatus.INVALID
    assert "TOP-SECRET-VALUE" not in rendered
    assert "api_key" not in rendered


def test_control_characters_and_executable_patterns_are_rejected():
    payload = valid_payload()
    payload["properties"][0]["display_name"] = "bad\u0000name"
    assert evaluate(payload).status is PreflightStatus.INVALID
    payload = valid_payload()
    payload["properties"][0]["display_name"] = "${{ secrets.TOKEN }}"
    assert evaluate(payload).status is PreflightStatus.INVALID


def test_boolean_as_integer_is_rejected():
    payload = valid_payload()
    payload["limits"]["page_size_limit"] = True
    report = evaluate(payload)
    assert report.status is PreflightStatus.INVALID


def test_custom_objects_and_malicious_subclasses_are_rejected_without_callbacks():
    class HostileMapping(dict):
        called = False

        def keys(self):
            self.called = True
            raise AssertionError("custom mapping callback invoked")

    class HostileString(str):
        pass

    hostile = HostileMapping(valid_payload())
    report = evaluate(hostile)
    assert report.status is PreflightStatus.INVALID
    assert hostile.called is False

    payload = valid_payload()
    payload["evidence_source"] = HostileString("synthetic")
    report = evaluate(payload)
    assert report.status is PreflightStatus.INVALID


def test_oversized_collection_is_invalid_and_bounded():
    payload = valid_payload()
    template = payload["properties"][0]
    payload["properties"] = []
    for index in range(257):
        item = copy.deepcopy(template)
        item["property_id"] = f"prop-{index}"
        item["display_name"] = f"Property {index}"
        payload["properties"].append(item)
    report = evaluate(payload)
    assert report.status is PreflightStatus.INVALID
    assert report.reason_codes == ("notion-value-limit-exceeded",)


def test_unknown_fields_fail_closed():
    payload = valid_payload()
    payload["unexpected"] = "value"
    report = evaluate(payload)
    assert report.status is PreflightStatus.INVALID


def test_finding_taxonomy_and_statuses_are_finite():
    assert len(FINDING_CODES) == 23
    assert {item.value for item in PreflightStatus} == {
        "ready-for-local-draft-implementation",
        "blocked",
        "manual-review-required",
        "invalid",
    }
    assert all(code.startswith("notion-") for code in FINDING_CODES)


def test_shared_core_normalization_and_fingerprinting_are_used(monkeypatch):
    normalize_calls = 0
    fingerprint_calls = 0
    original_normalize = preflight_core.validate_and_normalize_json
    original_fingerprint = preflight_core.sha256_hex

    def normalizing_spy(*args, **kwargs):
        nonlocal normalize_calls
        normalize_calls += 1
        return original_normalize(*args, **kwargs)

    def fingerprint_spy(*args, **kwargs):
        nonlocal fingerprint_calls
        fingerprint_calls += 1
        return original_fingerprint(*args, **kwargs)

    monkeypatch.setattr(preflight_core, "validate_and_normalize_json", normalizing_spy)
    monkeypatch.setattr(preflight_core, "sha256_hex", fingerprint_spy)
    report = evaluate(valid_payload())
    assert report.status is PreflightStatus.READY_FOR_LOCAL_DRAFT_IMPLEMENTATION
    assert normalize_calls == 1
    assert fingerprint_calls == 1


def test_source_has_no_duplicate_generic_infrastructure_or_forbidden_imports():
    package = Path(preflight_core.__file__).resolve().parent
    forbidden = {
        "hashlib",
        "jsonschema",
        "pydantic",
        "requests",
        "httpx",
        "urllib.request",
        "subprocess",
        "importlib",
        "navigation_registry",
        "notion_client",
        "notion",
        "google",
        "workflow_scheduler",
    }
    forbidden_function_names = {
        "canonical_json_bytes",
        "sha256_hex",
        "validate_and_normalize_json",
        "validate_reason_code",
        "validate_stable_id",
        "validate_version",
    }
    imported_common = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden
                    assert not any(alias.name.startswith(prefix + ".") for prefix in forbidden)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module not in forbidden
                assert not any(module.startswith(prefix + ".") for prefix in forbidden)
                if module == "instructional_workflow_contracts.common":
                    imported_common.update(alias.name for alias in node.names)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                assert node.name not in forbidden_function_names
    assert {
        "canonical_json_bytes",
        "sha256_hex",
        "validate_and_normalize_json",
        "validate_stable_id",
        "validate_version",
    }.issubset(imported_common)


def test_import_performs_no_external_or_runtime_side_effect(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden external or runtime action")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    models = importlib.import_module("scripts.agent_os_notion_curriculum_preflight.models")
    assert models.NotionCurriculumPreflightEvidence.__module__.endswith(".models")


def test_serialized_report_contains_only_bounded_non_authorizing_evidence():
    report = evaluate(valid_payload())
    payload = json.loads(serialize_preflight_report(report))
    assert payload["live_access_performed"] is False
    assert payload["side_effects_performed"] is False
    assert payload["write_authorized"] is False
    assert payload["production_authorized"] is False
    assert payload["publication_authorized"] is False
    assert len(serialize_preflight_report(report).encode("utf-8")) <= 32 * 1024
