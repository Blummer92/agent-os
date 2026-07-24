from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace

import pytest

from scripts.agent_os_remote_validation import (
    AdvisoryEvidenceResult,
    AdvisoryRenderResult,
    advisory_render_result_id,
    observe_advisory_evidence_shadow,
    render_advisory_evidence,
    serialize_advisory_render_result,
)
from scripts.agent_os_remote_validation import advisory_render as render_module


def _advisory(status: str = "passed", result_id: str = "advisory-evidence:" + "a" * 64) -> AdvisoryEvidenceResult:
    return AdvisoryEvidenceResult(
        schema_name="agent-os-advisory-pre-pr-evidence",
        schema_version="1.0",
        status=status,
        result_id=result_id,
        repository_identity=None,
        pull_request=574,
        base_branch="main",
        base_sha="b" * 40,
        source_head_sha="c" * 40,
        tested_sha="d" * 40,
        repository_evidence_type=None,
        projection_id="projection:" + "1" * 64,
        proposal_id="proposal:" + "2" * 64,
        approval_id="approval:" + "3" * 64,
        repository_state_evidence_id="repository-state:" + "4" * 64,
        implementation_contract_fingerprint="5" * 64,
        selector_version="1.0.0",
        profile="focused",
        command_set_digest="6" * 64,
        plan_id="validation-plan:" + "7" * 64,
        bundle_id="validation-evidence-bundle:" + "8" * 64,
        runner_id="runner",
        invocation_id="invocation",
        command_result_ids=("command-result:" + "9" * 64,),
        command_result_statuses=("passed",),
        reason_codes=(f"status.{status}",),
        details=("caf\u00e9",),
    )


def _serialized(result: AdvisoryEvidenceResult) -> dict[str, object]:
    return {
        "result_id": result.result_id,
        "status": result.status,
        "repository_identity": None,
        "pull_request": result.pull_request,
        "base_branch": result.base_branch,
        "base_sha": result.base_sha,
        "source_head_sha": result.source_head_sha,
        "tested_sha": result.tested_sha,
        "plan_id": result.plan_id,
        "bundle_id": result.bundle_id,
        "runner_id": result.runner_id,
        "invocation_id": result.invocation_id,
        "command_result_ids": list(result.command_result_ids),
        "command_result_statuses": list(result.command_result_statuses),
        "reason_codes": list(result.reason_codes),
        "details": list(result.details),
    }


@pytest.fixture(autouse=True)
def _patch_gex3_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_module, "serialize_advisory_evidence_result", _serialized)
    monkeypatch.setattr(render_module, "advisory_evidence_result_id", lambda result: result.result_id)


@pytest.mark.parametrize(
    "status",
    ["passed", "failed", "incomplete", "stale", "invalid", "needs-decision"],
)
def test_renders_all_canonical_statuses(status: str) -> None:
    result = render_advisory_evidence(_advisory(status))
    assert result.status == status
    assert result.authoritative is False
    assert result.execution_authorized is False
    assert result.merge_authorized is False
    assert result.attestation_verified is False
    assert result.side_effects_performed is False
    assert f'status="{status}"' in result.lines


def test_preserves_three_sha_roles_and_ordered_results() -> None:
    result = render_advisory_evidence(_advisory())
    assert 'base_sha="' + "b" * 40 + '"' in result.lines
    assert 'source_head_sha="' + "c" * 40 + '"' in result.lines
    assert 'tested_sha="' + "d" * 40 + '"' in result.lines
    assert any(line.startswith("command_result_ids=") for line in result.lines)
    assert any(line.startswith("command_result_statuses=") for line in result.lines)


def test_render_is_deterministic_unicode_preserving_and_tamper_evident() -> None:
    first = render_advisory_evidence(_advisory())
    second = render_advisory_evidence(_advisory())
    assert serialize_advisory_render_result(first) == serialize_advisory_render_result(second)
    assert "caf\u00e9" in "\n".join(first.lines)
    assert advisory_render_result_id(first) == first.render_id
    with pytest.raises(ValueError, match="render ID mismatch"):
        serialize_advisory_render_result(
            replace(first, render_id="advisory-render:" + "0" * 64)
        )


def test_rejects_wrong_types_duplicate_shadow_inputs_and_identity_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TypeError):
        render_advisory_evidence({})
    with pytest.raises(TypeError):
        observe_advisory_evidence_shadow([])
    with pytest.raises(ValueError, match="duplicate"):
        observe_advisory_evidence_shadow((_advisory(), _advisory()))
    monkeypatch.setattr(render_module, "advisory_evidence_result_id", lambda result: "other")
    with pytest.raises(ValueError, match="identity mismatch"):
        render_advisory_evidence(_advisory())


def test_output_contains_only_bounded_advisory_fields_and_notices() -> None:
    result = render_advisory_evidence(_advisory())
    text = "\n".join(result.lines).lower()
    for marker in (
        "advisory_only=true",
        "authoritative=false",
        "execution_authorized=false",
        "merge_authorized=false",
        "attestation_verified=false",
        "freshness_proven=false",
        "provenance_verified=false",
        "side_effects_performed=false",
    ):
        assert marker in text
    for forbidden in ("stdout", "stderr", "token=", "authorization:", "environment="):
        assert forbidden not in text


def test_render_result_is_immutable() -> None:
    result = render_advisory_evidence(_advisory())
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


def test_module_has_no_io_execution_clock_or_publication_imports() -> None:
    tree = ast.parse(inspect.getsource(render_module))
    banned = {
        "os", "pathlib", "socket", "subprocess", "requests", "urllib",
        "time", "datetime", "github", "google", "boto3",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(banned)


def test_serializer_rejects_wrong_type_and_size_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(TypeError):
        serialize_advisory_render_result({})  # type: ignore[arg-type]
    result = render_advisory_evidence(_advisory())
    monkeypatch.setattr(render_module, "MAX_RENDER_SERIALIZED_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        serialize_advisory_render_result(result)


def test_shadow_observation_is_in_memory_and_ordered() -> None:
    results = tuple(_advisory(status, "advisory-evidence:" + str(index) * 64) for index, status in enumerate(("passed", "failed", "stale"), 1))
    observed = observe_advisory_evidence_shadow(results)
    assert tuple(item.status for item in observed) == ("passed", "failed", "stale")
    assert all(isinstance(item, AdvisoryRenderResult) for item in observed)
