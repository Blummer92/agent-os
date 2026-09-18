from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest
import yaml

from instructional_workflow_contracts import ValidationStatus, validate_request_interpretation
from instructional_workflow_contracts.request_interpretation import RequestInterpretation, evaluate_ppux_mission_constraint
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


def test_terminal_fast_lane_is_structured_constraint_not_authority():
    result = validate_request_interpretation(
        payload(
            raw_input_digest=sha256_hex("work on #844 in fast lane"),
            constraints=[{"name": "operating-mode", "value": "release"}],
        )
    )
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    data = result.record.to_dict()
    assert data["target"]["resource_id"] == "844"
    assert data["constraints"] == [{"name": "operating-mode", "value": "release"}]
    assert data["authorization_created"] is False
    assert result.authority.execution_authorized is False
    assert result.authority.external_write_authorized is False


def test_ordinary_work_on_has_no_terminal_fast_lane_constraint():
    data = record(payload(raw_input_digest=sha256_hex("work on #844")))
    assert data["constraints"] == []
    assert data["authorization_created"] is False


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


def ppux_interpretation(*, continuation="new", constraints=None):
    result = validate_request_interpretation(
        payload(
            continuation_mode=continuation,
            constraints=constraints or [],
        )
    )
    assert result.status is ValidationStatus.VALID
    assert result.record is not None
    return RequestInterpretation(record=result.record)


@pytest.mark.parametrize("state", ["pending", "blocked", "execution-unavailable", "source-unresolved", "manual-review"])
def test_ppux_runner_authority_survives_ordinary_followup_pressure(state):
    previous = ppux_interpretation(
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-result-state", "value": state},
            {"name": "ppux-tutorial-id", "value": "tutorial-0"},
        ]
    )
    current = ppux_interpretation(continuation="continue")
    decision = evaluate_ppux_mission_constraint(previous, current)
    assert decision.runner_authoritative is True
    assert decision.result_state == state
    assert decision.generic_prompt_authoring_allowed is False
    assert decision.authorization_created is False
    assert decision.authority.execution_authorized is False
    assert decision.authority.external_write_authorized is False


def test_ppux_blocked_cards_cannot_be_reconstructed_by_continuation():
    previous = ppux_interpretation(
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-result-state", "value": "blocked"},
            {"name": "ppux-tutorial-id", "value": "tutorial-0"},
        ]
    )
    decision = evaluate_ppux_mission_constraint(previous, ppux_interpretation(continuation="continue"))
    assert decision.generic_prompt_authoring_allowed is False
    assert decision.manual_alternative_requested is False


def test_ppux_explicit_manual_provenance_change_is_the_escape_hatch():
    previous = ppux_interpretation(
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-result-state", "value": "execution-unavailable"},
            {"name": "ppux-tutorial-id", "value": "tutorial-0"},
        ]
    )
    current = ppux_interpretation(
        continuation="continue",
        constraints=[{"name": "ppux-provenance-change", "value": "manual"}],
    )
    decision = evaluate_ppux_mission_constraint(previous, current)
    assert decision.runner_authoritative is False
    assert decision.manual_alternative_requested is True
    assert decision.generic_prompt_authoring_allowed is True
    assert decision.authorization_created is False


def test_ppux_tutorial_identity_change_requires_fresh_resolution():
    previous = ppux_interpretation(
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-result-state", "value": "ready"},
            {"name": "ppux-tutorial-id", "value": "tutorial-0"},
        ]
    )
    current = ppux_interpretation(
        continuation="continue",
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-tutorial-id", "value": "tutorial-1"},
        ],
    )
    decision = evaluate_ppux_mission_constraint(previous, current)
    assert decision.requires_fresh_tutorial_resolution is True
    assert decision.runner_authoritative is False
    assert decision.result_state is None
    assert decision.generic_prompt_authoring_allowed is False


def test_ppux_provider_constraint_does_not_clear_runner_authority():
    previous = ppux_interpretation(
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-result-state", "value": "pending"},
            {"name": "ppux-tutorial-id", "value": "tutorial-0"},
        ]
    )
    current = ppux_interpretation(
        continuation="continue",
        constraints=[{"name": "provider", "value": "canva"}],
    )
    decision = evaluate_ppux_mission_constraint(previous, current)
    assert decision.runner_authoritative is True
    assert decision.tutorial_id == "tutorial-0"
    assert decision.generic_prompt_authoring_allowed is False


def test_unrelated_generic_image_request_has_no_ppux_authority():
    decision = evaluate_ppux_mission_constraint(None, ppux_interpretation())
    assert decision.runner_authoritative is False
    assert decision.tutorial_id is None
    assert decision.result_state is None
    assert decision.generic_prompt_authoring_allowed is True
    assert decision.side_effects_performed is False


def test_ppux_ready_result_still_forbids_generic_replacement_authoring():
    previous = ppux_interpretation(
        constraints=[
            {"name": "ppux-authority", "value": "runner"},
            {"name": "ppux-result-state", "value": "ready"},
            {"name": "ppux-tutorial-id", "value": "tutorial-0"},
        ]
    )
    decision = evaluate_ppux_mission_constraint(previous, ppux_interpretation(continuation="continue"))
    assert decision.runner_authoritative is True
    assert decision.result_state == "ready"
    assert decision.generic_prompt_authoring_allowed is False


def test_ppux_guard_rejects_unstructured_provenance_change_values():
    previous = ppux_interpretation(
        constraints=[{"name": "ppux-authority", "value": "runner"}]
    )
    current = ppux_interpretation(
        continuation="continue",
        constraints=[{"name": "ppux-provenance-change", "value": "just-do-it"}],
    )
    with pytest.raises(ValueError, match="ppux-provenance-change"):
        evaluate_ppux_mission_constraint(previous, current)
