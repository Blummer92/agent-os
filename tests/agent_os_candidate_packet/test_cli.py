"""Focused AOS-AUTO1G tests for the `prepare-candidate-packet` operator CLI (#1105)."""

from __future__ import annotations

import json

from scripts.agent_os_candidate_packet.cli import main
from tests.agent_os_candidate_packet.test_end_to_end import (
    _EVALUATOR_SHA,
    _ISSUE_ITEM,
    _ISSUE_NUMBER,
    _REPOSITORY,
    _SHA,
)


def _repository_identity_dict() -> dict[str, object]:
    return dict(host="github.com", owner="Blummer92", repository="agent-os", default_branch="main")


def _repository_observation_dict(contract_fingerprint: str) -> dict[str, object]:
    return dict(
        producer_adapter="cli-fixture",
        producer_adapter_version="1.0",
        correlation_id=f"issue-{_ISSUE_NUMBER}",
        repository_identity=_repository_identity_dict(),
        base_ref="main",
        base_sha="c" * 40,
        head_ref="agent/1105-cli-fixture",
        head_sha=_SHA,
        requested_ref="agent/1105-cli-fixture",
        requested_sha=_SHA,
        observed_sha=_SHA,
        tested_sha=_SHA,
        evidence_type="branch-head",
        contract_fingerprint=contract_fingerprint,
        worktree_state="clean",
        observed_at="2026-08-14T00:05:00Z",
        freshness_boundary="main@cli-fixture",
    )


def _candidate_context_dict() -> dict[str, object]:
    return dict(
        approval_kind="implementation",
        authorizer_id="candidate-preparer",
        decision_id=f"candidate-{_ISSUE_NUMBER}-cli",
        decision_at="2026-08-14T00:06:00Z",
    )


def _approval_decision_dict() -> dict[str, object]:
    return dict(
        state="approved",
        decision_id=f"human-approved-{_ISSUE_NUMBER}-cli",
        authorizer_id="repository-owner",
        decision_at="2026-08-14T00:07:00Z",
    )


def _base_fixture(**overrides) -> dict[str, object]:
    fixture = dict(
        repository=_REPOSITORY,
        issue_number=_ISSUE_NUMBER,
        issue=dict(_ISSUE_ITEM),
        observed_at="2026-08-14T00:05:00Z",
        base_branch="main",
        evaluated_repository_sha=_SHA,
        invocation_id="candidate-packet-cli-fixture-1105",
        evaluator_sha=_EVALUATOR_SHA,
        dependency_identity_evidence={
            "status": "absent",
            "provenance": ["cli-fixture:no-dependencies"],
        },
        dependency_evidence={"status": "resolved-clear"},
        validation_evidence={"status": "resolved-clear"},
    )
    fixture.update(overrides)
    return fixture


def _write_fixture(tmp_path, fixture: dict[str, object]):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def test_cli_planning_only_exits_nonzero_with_text_summary(tmp_path, capsys) -> None:
    path = _write_fixture(tmp_path, _base_fixture())

    exit_code = main(["--request", str(path)])

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "stage reached: planning" in output
    assert "execution_authorized=false" in output


def test_cli_approval_ready_json_output_contains_packet(tmp_path, capsys) -> None:
    fixture = _base_fixture()
    path = _write_fixture(tmp_path, fixture)
    from scripts.agent_os_candidate_packet.cli import _prepare_from_fixture

    precheck = _prepare_from_fixture(json.loads(path.read_text()))
    fingerprint = precheck.implementation_contract_fingerprint

    fixture = _base_fixture(
        repository_observation=_repository_observation_dict(fingerprint),
        candidate_context=_candidate_context_dict(),
    )
    path = _write_fixture(tmp_path, fixture)

    exit_code = main(["--request", str(path), "--format", "json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["packet_phase"] == "approval-ready"
    assert payload["packet"] is not None
    assert payload["execution_authorized"] is False
    assert payload["side_effects_performed"] is False


def test_cli_rejects_a_missing_fixture_file(tmp_path) -> None:
    missing = tmp_path / "does-not-exist.json"

    exit_code = main(["--request", str(missing)])

    assert exit_code == 2


def test_cli_rejects_malformed_json(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")

    exit_code = main(["--request", str(path)])

    assert exit_code == 2


def test_cli_rejects_a_fixture_missing_required_keys(tmp_path) -> None:
    fixture = _base_fixture()
    del fixture["evaluator_sha"]
    path = _write_fixture(tmp_path, fixture)

    exit_code = main(["--request", str(path)])

    assert exit_code == 2


def test_cli_execution_candidate_requires_runtime_inputs(tmp_path, capsys) -> None:
    from scripts.agent_os_candidate_packet.cli import _prepare_from_fixture

    path = _write_fixture(tmp_path, _base_fixture())
    precheck = _prepare_from_fixture(json.loads(path.read_text()))
    fingerprint = precheck.implementation_contract_fingerprint

    fixture = _base_fixture(
        repository_observation=_repository_observation_dict(fingerprint),
        candidate_context=_candidate_context_dict(),
        approval_decision=_approval_decision_dict(),
        requested_phase="execution-candidate",
    )
    path = _write_fixture(tmp_path, fixture)

    exit_code = main(["--request", str(path), "--format", "json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["approval_status"] == "complete"
    assert payload["failure_reason_code"] == "execution-packet.missing"
    assert payload["execution_authorized"] is False


def test_cli_never_prompts_itself_into_authorization(tmp_path, capsys) -> None:
    """No fixture combination can make the CLI report an authorized outcome."""
    for fixture in (
        _base_fixture(),
        _base_fixture(requested_phase="execution-candidate"),
    ):
        path = _write_fixture(tmp_path, fixture)
        main(["--request", str(path), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["execution_authorized"] is False
        assert payload["merge_authorized"] is False
        assert payload["automatic_retry"] is False
        assert payload["side_effects_performed"] is False
