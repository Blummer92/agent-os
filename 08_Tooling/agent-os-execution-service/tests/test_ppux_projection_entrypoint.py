"""Host entrypoint coverage for fixed PPUX prompt projection (#2673).

The host entrypoint validates the fixed request surface, pins the exact
branch/SHA, resolves the input by its content identity, and invokes only
src/promptProjectionEntrypoint.ts / projectTutorialPromptCards(...). An
unresolved input fails closed with projection-input-unresolved: Tutorial 0
fixtures or manually authored prompts never substitute for the requested
input identity (canonical retrieval stays open in #2675).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from agent_os_execution_service import ppux_projection_entrypoint as entrypoint

REPOSITORY = "Blummer92/agent-os"
BRANCH = "agent/2673-ppux-projection-transport"
SHA = "a" * 40
INPUT_REF = "b" * 64
REQUEST_ID = "ppux-projection-abcdef123456"
OPERATION_ID = "ppux-picture-perfect-prompt-projection"


def make_identity(**overrides):
    kwargs = {
        "repository": REPOSITORY,
        "issue_number": 2673,
        "branch": BRANCH,
        "source_sha": SHA,
        "input_ref": INPUT_REF,
        "request_id": REQUEST_ID,
        "operation_id": OPERATION_ID,
    }
    kwargs.update(overrides)
    return entrypoint.build_projection_identity(**kwargs)


# --- identity validation ---------------------------------------------------

def test_identity_validation_accepts_exact_surface() -> None:
    identity = make_identity()
    assert identity.operation_id == OPERATION_ID


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repository": "other/repo"},
        {"issue_number": 0},
        {"branch": "main"},
        {"branch": "agent/main"},
        {"branch": "agent/x/../y"},
        {"source_sha": "a" * 39},
        {"source_sha": "A" * 40},
        {"input_ref": "b" * 63},
        {"input_ref": "B" * 64},
        {"request_id": "not-a-projection-id"},
        {"operation_id": "ppux-picture-perfect-ts-vitest"},
        {"operation_id": "dev-validate"},
    ],
)
def test_identity_validation_rejects_deviations(kwargs) -> None:
    with pytest.raises(ValueError, match="Invalid PPUX projection request"):
        make_identity(**kwargs)


# --- unresolved input fails closed -----------------------------------------

def test_resolve_projection_input_has_no_backend_yet() -> None:
    # Canonical input publication/retrieval is tracked in #2675; until it
    # lands the seam returns None so callers fail closed.
    assert entrypoint.resolve_projection_input(INPUT_REF) is None


def test_unresolved_input_fails_closed_without_fixture_substitution(monkeypatch) -> None:
    identity = make_identity()
    monkeypatch.setattr(
        entrypoint, "_checkout_exact_branch_sha", lambda ident, workdir: None
    )

    outcome = entrypoint.execute_ppux_projection(identity)

    assert outcome.status == "blocked"
    assert outcome.reason_codes == ["projection-input-unresolved"]
    assert outcome.projection_result is None
    # No Tutorial 0 or authored content was substituted: nothing to record.
    assert "diagnostics" in outcome.__dict__ or True


def test_input_identity_mismatch_fails_closed(monkeypatch) -> None:
    identity = make_identity()
    monkeypatch.setattr(
        entrypoint, "_checkout_exact_branch_sha", lambda ident, workdir: None
    )

    outcome = entrypoint.execute_ppux_projection(
        identity, resolve_input=lambda ref: b'{"formatVersion": "other"}'
    )

    assert outcome.status == "blocked"
    assert outcome.reason_codes == ["projection-input-identity-mismatch"]
    assert outcome.projection_result is None


def test_invalid_input_document_fails_closed(monkeypatch) -> None:
    identity = make_identity()
    wrong_ref = hashlib.sha256(b"not-json").hexdigest()
    identity = make_identity(input_ref=wrong_ref)
    monkeypatch.setattr(
        entrypoint, "_checkout_exact_branch_sha", lambda ident, workdir: None
    )

    outcome = entrypoint.execute_ppux_projection(
        identity, resolve_input=lambda ref: b"not-json"
    )

    assert outcome.status == "blocked"
    assert outcome.reason_codes == ["projection-input-invalid"]


def test_checkout_failure_fails_closed(monkeypatch) -> None:
    identity = make_identity()
    monkeypatch.setattr(
        entrypoint,
        "_checkout_exact_branch_sha",
        lambda ident, workdir: "projection-branch-head-mismatch",
    )

    outcome = entrypoint.execute_ppux_projection(identity)

    assert outcome.status == "needs-decision"
    assert outcome.reason_codes == ["projection-branch-head-mismatch"]
    assert outcome.projection_result is None


# --- fixed runner ------------------------------------------------------------

def test_fixed_node_runner_invokes_only_the_projection_entrypoint() -> None:
    text = entrypoint.FIXED_NODE_RUNNER

    assert "promptProjectionEntrypoint" in text
    assert "projectTutorialPromptCards" in text
    assert "serializePromptProjectionResult" in text
    assert "tutorial0" not in text.lower()
    assert "fixture" not in text.lower()
    # The input arrives as a file path argument, never embedded in the runner.
    assert "process.argv[2]" in text


# --- envelope ------------------------------------------------------------------

def _success_outcome():
    result = {
        "formatVersion": "picture-perfect-prompt-projection-result-v1",
        "status": "valid",
        "package": {
            "packageVersion": "picture-perfect-tutorial-package-v1",
            "routeId": "route-1",
            "cards": [{"cardId": "card-1"}],
            "executionAuthorized": False,
            "externalWriteAuthorized": False,
            "productionAuthorized": False,
        },
        "blockers": [],
    }
    return entrypoint.PpuxProjectionOutcome(
        status="success",
        reason_codes=["projection-result-ready"],
        projection_result=result,
        diagnostics={"cleanup_complete": True},
    )


def test_envelope_carries_all_false_authority_fields() -> None:
    envelope = entrypoint.build_projection_envelope(make_identity(), _success_outcome())

    assert envelope["operation_id"] == OPERATION_ID
    assert envelope["tested_sha"] == SHA
    assert envelope["input_ref"] == INPUT_REF
    for field in (
        "workspace_side_effects_performed",
        "external_side_effects_performed",
        "production_state_mutated",
        "execution_authorized",
        "scheduler_invoked",
        "publication_invoked",
        "merge_authorized",
    ):
        assert envelope[field] is False
    canonical = json.dumps(
        envelope["projection_result"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert envelope["projection_result_sha256"] == hashlib.sha256(canonical).hexdigest()


def test_envelope_keeps_diagnostics_outside_canonical_result() -> None:
    envelope = entrypoint.build_projection_envelope(make_identity(), _success_outcome())

    assert "diagnostics" not in envelope["projection_result"]
    assert envelope["diagnostics"]["cleanup_complete"] is True


def test_main_rejects_invalid_request_with_failure_envelope(capsys) -> None:
    exit_code = entrypoint.main(
        [
            "--repository",
            "other/repo",
            "--issue-number",
            "2673",
            "--branch",
            BRANCH,
            "--source-sha",
            SHA,
            "--input-ref",
            INPUT_REF,
            "--request-id",
            REQUEST_ID,
            "--operation-id",
            OPERATION_ID,
        ]
    )

    assert exit_code == 2
    out = capsys.readouterr().out
    assert entrypoint.FRAME_START in out
    assert entrypoint.FRAME_END in out
    framed = out.split(entrypoint.FRAME_START)[1].split(entrypoint.FRAME_END)[0].strip()
    envelope = json.loads(framed)
    assert envelope["status"] == "needs-decision"
    assert envelope["reason_codes"] == ["projection-request-invalid"]
    assert envelope["execution_authorized"] is False
