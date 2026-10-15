from __future__ import annotations

"""Regression coverage: Codespaces discovery evidence must survive GCE fallback.

The "Attempt Codespaces discovery" step writes the discovery payload
(including the SSH transport evidence: exit codes, framed response, reason
codes) to ``result.json``. The "Invoke exact governed GCE control path" step
then unconditionally overwrites the same ``result.json`` path, destroying the
Codespaces payload whenever the fallback engages. Before this fix, a
``codespaces_capable=false`` outcome left no recoverable SSH transport
evidence in the published artifact, making live SSH acceptance unverifiable.

The workflow now preserves an independent copy at
``codespaces-discovery-result.json`` immediately after the discovery module
runs, and surfaces it in the job summary. Routing, authorization,
permissions, fallback eligibility, and the GCE step's own ``result.json``
contract are unchanged.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCHEDULER_SRC = Path(__file__).parents[1] / "08_Tooling" / "workflow-scheduler" / "src"
if str(SCHEDULER_SRC) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_SRC))

from workflow_scheduler.governance.discovery_codespaces import (
    run_discovery_over_codespaces,
    select_codespaces_discovery,
)
from workflow_scheduler.governance.dev_validation import REPOSITORY
from workflow_scheduler.governance.github_issue_comment_ingress import (
    IssueCommentIngressResult,
)

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"

DISCOVERY_STEP = "Attempt Codespaces discovery"
GCE_STEP = "Invoke exact governed GCE control path"
SUMMARY_STEP = "Publish bounded invocation summary"
ARTIFACT_STEP = "Publish bounded ingress evidence"

PRESERVED = "codespaces-discovery-result.json"
LIVE_RESULT = "result.json"


def _step_block(text: str, step_name: str, next_step_name: str) -> str:
    return text.split(f"- name: {step_name}", 1)[1].split(
        f"- name: {next_step_name}", 1
    )[0]


def test_discovery_step_preserves_payload_independently() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(text, DISCOVERY_STEP, "Authenticate bounded Agent OS transport")
    # The module still writes the live result.json (downstream readers and the
    # capable/not-capable outputs are unchanged).
    assert f'--result-output "$RUNNER_TEMP/agent-os-ingress/{LIVE_RESULT}"' in block
    # The payload is then copied to an independent path before any fallback
    # step can overwrite result.json.
    assert PRESERVED in block
    assert f'cp "$RUNNER_TEMP/agent-os-ingress/{LIVE_RESULT}"' in block
    assert f'"$RUNNER_TEMP/agent-os-ingress/{PRESERVED}"' in block


def test_preservation_is_scoped_to_the_discovery_step() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    # Only the discovery step may produce the preserved file; no other step
    # may write it (which would reintroduce clobbering or confusion).
    assert text.count(PRESERVED) >= 2, "preservation copy + summary read expected"
    gce_block = _step_block(text, GCE_STEP, SUMMARY_STEP)
    assert PRESERVED not in gce_block, (
        "the GCE fallback step must not touch the preserved Codespaces payload"
    )


def test_gce_step_keeps_writing_live_result_json() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    gce_block = _step_block(text, GCE_STEP, SUMMARY_STEP)
    # The fallback's own result contract is unchanged: it still writes the
    # live result.json (overwriting the discovery payload there by design).
    assert f'--output "$RUNNER_TEMP/agent-os-ingress/{LIVE_RESULT}"' in gce_block


def test_artifact_upload_publishes_the_preserved_payload() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(text, ARTIFACT_STEP, "Post Authenticate bounded Agent OS transport")
    # The ingress artifact uploads every JSON in the evidence dir, so the
    # preserved file is published without naming it explicitly.
    assert "agent-os-ingress/*.json" in block


def test_summary_surfaces_the_preserved_payload() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(text, SUMMARY_STEP, "Enforce developer-validation result gate")
    assert PRESERVED in block
    assert "Codespaces discovery payload preserved" in block
    assert "Preserved capable" in block
    assert "Preserved discovery reasons" in block


def test_discovery_routing_condition_is_unchanged() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(text, DISCOVERY_STEP, "Authenticate bounded Agent OS transport")
    # The preservation must not alter dispatch: the exact routing condition
    # that gates the discovery step is preserved verbatim.
    assert "steps.route.outputs.preferred == 'codespaces'" in block
    assert "steps.transport.outputs.accepted == 'true'" in block
    assert "steps.codespaces.outputs.selected != 'true'" in block


# ============================================================================
# Behavioral coverage: the overwrite that caused the defect, exercised offline.
#
# These tests run the real discovery module against faked subprocess results,
# then replay the exact file contract the workflow implements: the module
# writes result.json, the workflow preserves an independent copy, and the GCE
# fallback overwrites result.json. They prove the preserved payload survives
# and still distinguishes an SSH transport failure from a descriptor-store
# failure — the two outcomes the acceptance evidence must tell apart.
# ============================================================================

_BEHAVIORAL_CODESPACE = "fluffy-current-agentos-7x9q"
_FRAME_START = "===AGENT-OS-CODESPACES-DISCOVERY-JSON-BEGIN==="
_FRAME_END = "===AGENT-OS-CODESPACES-DISCOVERY-JSON-END==="
_PRESERVED_NAME = "codespaces-discovery-result.json"
_LIVE_NAME = "result.json"


def _behavioral_ingress() -> IssueCommentIngressResult:
    return IssueCommentIngressResult(
        schema_version="1.0",
        status="accepted",
        reason="accepted-discovery-envelope",
        repository=REPOSITORY,
        issue_number=3617,
        comment_id=6201507223,
        actor="Blummer92",
        handoff_id_or_none=None,
        logical_trigger_id_or_none="issue-comment-trigger:test",
        run_attempt=1,
    )


def _listing_stdout() -> str:
    item = {
        "name": _BEHAVIORAL_CODESPACE,
        "state": "Available",
        "owner": {"login": "Blummer92"},
        "repository": {"full_name": REPOSITORY},
    }
    return json.dumps({"total_count": 1, "codespaces": [item]})


def _store_unavailable_frame() -> str:
    payload = {
        "schema_version": "1.0",
        "status": "needs-decision",
        "reason_codes": ["codespaces-discovery-store-unavailable"],
        "repository": REPOSITORY,
        "issue_number": 3617,
        "matching_descriptor_count": 0,
        "handoff_id": None,
        "result_id": None,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
        "codespaces_profile_id": "agent-os-codespaces-v1",
        "execution_surface_id": f"codespace:{_BEHAVIORAL_CODESPACE}",
    }
    return _FRAME_START + json.dumps(payload, sort_keys=True) + _FRAME_END


def _behavioral_run(*, ssh_succeeds: bool):
    """Fake subprocess run: selection lists one Available codespace; the SSH
    leg either fails fast (transport failure) or returns the remote program's
    framed store-unavailable payload (boundary crossed, store missing)."""
    seen_ssh_argv: list[tuple] = []

    def run(argv, *, timeout):
        if argv[1] == "api":
            return subprocess.CompletedProcess(argv, 0, stdout=_listing_stdout(), stderr="")
        assert argv[1] == "codespace", f"unexpected argv: {argv}"
        seen_ssh_argv.append(tuple(argv))
        if not ssh_succeeds:
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="error: failed to connect: connection refused"
            )
        return subprocess.CompletedProcess(argv, 0, stdout=_store_unavailable_frame(), stderr="")

    run.seen_ssh_argv = seen_ssh_argv
    return run


def _gce_fallback_payload() -> dict:
    # Mirrors gce_gcloud_adapter._discovery_unavailable("discovery-gce-unavailable").
    return {
        "discovery": {
            "schema_version": "1.0",
            "status": "needs-decision",
            "reason_codes": ["discovery-gce-unavailable"],
            "repository": REPOSITORY,
            "issue_number": 3617,
            "matching_descriptor_count": 0,
            "handoff_id": None,
            "result_id": None,
            "execution_authorized": False,
            "scheduler_invoked": False,
            "side_effects_performed": False,
        }
    }


def _run_discovery_to_preserved(tmp_path: Path, *, ssh_succeeds: bool, monkeypatch) -> dict:
    """Exercise the real module, then replay the workflow's file contract:
    module -> result.json, preservation cp -> codespaces-discovery-result.json,
    GCE fallback overwrite -> result.json. Returns the preserved payload."""
    monkeypatch.setenv("GH_TOKEN", "redacted-test-token")
    run = _behavioral_run(ssh_succeeds=ssh_succeeds)
    route, request = select_codespaces_discovery(_behavioral_ingress(), run=run)
    assert route["selected"] is True
    assert route["codespace_name"] == _BEHAVIORAL_CODESPACE
    assert request is not None

    result = run_discovery_over_codespaces(
        request, codespace_name=_BEHAVIORAL_CODESPACE, run=run
    )
    assert result["codespaces_capable"] is False

    # The SSH argv must cross the boundary as one safely quoted command word
    # (the #3617 shlex.join repair), not as split fragments.
    assert len(run.seen_ssh_argv) == 1
    ssh_argv = run.seen_ssh_argv[0]
    assert ssh_argv[:5] == ("gh", "codespace", "ssh", "-c", _BEHAVIORAL_CODESPACE)
    assert ssh_argv[5] == "--"
    assert len(ssh_argv) == 7, "remote command must be a single argv element"

    # Workflow contract, step 1: the module writes the live result.json.
    live_path = tmp_path / _LIVE_NAME
    live_path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")

    # Workflow contract, step 2 (the repair): preserve an independent copy.
    preserved_path = tmp_path / _PRESERVED_NAME
    shutil.copy(live_path, preserved_path)

    # Workflow contract, step 3: the GCE fallback overwrites result.json.
    live_path.write_text(json.dumps(_gce_fallback_payload(), sort_keys=True), encoding="utf-8")

    preserved = json.loads(preserved_path.read_text(encoding="utf-8"))
    live = json.loads(live_path.read_text(encoding="utf-8"))
    assert live["discovery"]["reason_codes"] == ["discovery-gce-unavailable"]
    assert preserved != live, "preserved payload must differ from the GCE overwrite"
    return preserved


def test_preserved_payload_survives_gce_overwrite_on_ssh_failure(tmp_path, monkeypatch) -> None:
    preserved = _run_discovery_to_preserved(tmp_path, ssh_succeeds=False, monkeypatch=monkeypatch)
    discovery = preserved["discovery"]
    assert discovery["reason_codes"] == ["discovery-codespaces-ssh-failed"]
    # The SSH transport evidence is intact in the preserved copy.
    assert discovery["ssh_exit_code"] == 1
    assert "connection refused" in discovery["ssh_stderr_tail"]
    assert discovery["repository"] == REPOSITORY
    assert discovery["issue_number"] == 3617
    assert discovery["execution_authorized"] is False
    assert discovery["scheduler_invoked"] is False
    assert discovery["side_effects_performed"] is False


def test_preserved_payload_survives_gce_overwrite_on_store_failure(tmp_path, monkeypatch) -> None:
    preserved = _run_discovery_to_preserved(tmp_path, ssh_succeeds=True, monkeypatch=monkeypatch)
    discovery = preserved["discovery"]
    assert discovery["reason_codes"] == ["codespaces-discovery-store-unavailable"]
    # The framed remote response was parsed and identity preserved.
    assert discovery["repository"] == REPOSITORY
    assert discovery["issue_number"] == 3617
    assert discovery["status"] == "needs-decision"
    assert discovery["execution_authorized"] is False
    assert discovery["scheduler_invoked"] is False
    assert discovery["side_effects_performed"] is False


def test_preserved_payload_distinguishes_ssh_failure_from_store_failure(tmp_path, monkeypatch) -> None:
    ssh_dir = tmp_path / "ssh"
    store_dir = tmp_path / "store"
    ssh_dir.mkdir()
    store_dir.mkdir()
    ssh_failed = _run_discovery_to_preserved(ssh_dir, ssh_succeeds=False, monkeypatch=monkeypatch)
    store_failed = _run_discovery_to_preserved(store_dir, ssh_succeeds=True, monkeypatch=monkeypatch)
    ssh_reasons = ssh_failed["discovery"]["reason_codes"]
    store_reasons = store_failed["discovery"]["reason_codes"]
    assert ssh_reasons != store_reasons
    assert ssh_reasons == ["discovery-codespaces-ssh-failed"]
    assert store_reasons == ["codespaces-discovery-store-unavailable"]
