from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest
import yaml

from instructional_workflow_contracts import ValidationStatus, validate_request_interpretation
from instructional_workflow_contracts.common import sha256_hex

MODULE = Path("src/instructional_workflow_contracts/request_interpretation.py")
CATALOG = Path("04_Registry/request-interpretation-reason-code-catalog.yaml")


def payload(**overrides):
    value = {
        "schema_name": "request-interpretation",
        "contract_version": "request-interpretation-v1",
        "record_revision": 1,
        "observed_at": "2026-08-09T00:00:00Z",
        "interpreter_id": "chatgpt-orchestrator",
        "raw_input_digest": sha256_hex("Implement issue 844."),
        "instruction_origin": "direct-user",
        "action": "implement",
        "requested_effect": "mutate",
        "continuation_mode": "new",
        "target": {"system": "github", "resource_kind": "issue", "repository": "Blummer92/agent-os", "resource_id": "844"},
        "requested_outputs": ["implementation"],
        "constraints": [],
        "reason_codes": [],
        "evidence_references": [],
    }
    value.update(overrides)
    return value


def record(value):
    result = validate_request_interpretation(value)
    assert result.record is not None
    return result.record.to_dict()


def test_valid_record_is_deterministic_authority_false_and_input_immutable():
    value = payload()
    original = copy.deepcopy(value)
    first = validate_request_interpretation(value)
    second = validate_request_interpretation(copy.deepcopy(value))
    assert first.status is ValidationStatus.VALID
    assert first.record.fingerprint == second.record.fingerprint
    assert value == original
    data = first.record.to_dict()
    assert data["side_effects_performed"] is False
    assert data["authorization_created"] is False
    assert first.authority.execution_authorized is False


def test_equivalent_issue_phrases_can_share_one_semantic_record():
    fingerprints = set()
    for phrase in ("Let's work on 844.", "Start issue #844.", "Implement issue 844."):
        value = payload(raw_input_digest=sha256_hex(phrase))
        # Raw evidence differs, while semantic projection excluding the digest is identical.
        data = record(value)
        semantic = dict(data)
        semantic.pop("raw_input_digest")
        fingerprints.add(sha256_hex(semantic))
    assert len(fingerprints) == 1


def test_ambiguous_continuation_fails_closed_to_manual_review():
    value = payload(
        action="unknown",
        requested_effect="read",
        continuation_mode="continue",
        target={"system": "github", "resource_kind": "pull-request", "repository": "Blummer92/agent-os", "resource_id": None},
    )
    result = validate_request_interpretation(value)
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert {"action.ambiguous", "context.missing", "target.missing"} <= set(result.details)


def test_retrieved_mutation_is_untrusted_and_write_surface_unclear():
    result = validate_request_interpretation(payload(instruction_origin="retrieved-content"))
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert {"request.untrusted-source", "request.write-surface-unclear"} <= set(result.details)


def test_system_and_resource_kind_remain_separate():
    data = record(payload(action="generate", requested_effect="propose", target={"system": "google-slides", "resource_kind": "unknown", "repository": None, "resource_id": None}))
    assert data["target"]["system"] == "google-slides"
    assert data["target"]["resource_kind"] == "unknown"


def test_one_command_is_a_constraint_not_an_action():
    data = record(payload(action="inspect", requested_effect="read", constraints=[{"name": "output-count", "value": 1}], requested_outputs=["command"]))
    assert data["action"] == "inspect"
    assert data["constraints"] == [{"name": "output-count", "value": 1}]


def test_schedule_requires_monitoring_surface():
    result = validate_request_interpretation(payload(action="review", requested_effect="schedule"))
    assert result.status is ValidationStatus.MANUAL_REVIEW_REQUIRED
    assert "request.monitoring-surface-required" in result.details


@pytest.mark.parametrize("field", ["action", "requested_effect", "instruction_origin", "continuation_mode"])
def test_unsupported_vocabulary_is_invalid(field):
    result = validate_request_interpretation(payload(**{field: "unsupported"}))
    assert result.status is ValidationStatus.INVALID


def test_unknown_top_level_field_fails_closed():
    value = payload()
    value["surprise"] = True
    result = validate_request_interpretation(value)
    assert result.status is ValidationStatus.INVALID
    assert "handoff-unknown-field" in result.reason_codes


def test_unsupported_contract_version_fails_closed():
    result = validate_request_interpretation(payload(contract_version="request-interpretation-v2"))
    assert result.status is ValidationStatus.INVALID
    assert "handoff-version-unsupported" in result.reason_codes


def test_unsafe_text_and_secret_like_input_fail_closed():
    unsafe = payload(interpreter_id="eval(x)")
    assert validate_request_interpretation(unsafe).status is ValidationStatus.INVALID
    secret = payload(constraints=[{"name": "api-key", "value": "not-a-secret"}])
    assert validate_request_interpretation(secret).status is ValidationStatus.INVALID


def test_bounds_fail_closed():
    result = validate_request_interpretation(payload(requested_outputs=[f"output-{i}" for i in range(9)]))
    assert result.status is ValidationStatus.INVALID
    assert "handoff-oversized" in result.reason_codes


def test_catalog_matches_runtime_codes_and_is_non_authoritative():
    catalog = yaml.safe_load(CATALOG.read_text())
    codes = {entry["code"] for entry in catalog["codes"]}
    tree = ast.parse(MODULE.read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "REASON_CODES" for target in node.targets))
    runtime_codes = set(ast.literal_eval(assignment.value.args[0]))
    assert codes == runtime_codes
    assert catalog["authority_created"] is False


def test_module_has_no_forbidden_io_or_provider_imports():
    tree = ast.parse(MODULE.read_text())
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = ("requests", "httpx", "urllib", "subprocess", "os", "google", "notion", "workflow_scheduler", "navigation_registry")
    assert not any(name.startswith(forbidden) for name in imports)
