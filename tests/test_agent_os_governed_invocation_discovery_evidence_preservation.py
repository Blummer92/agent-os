"""The independent discovery receipt stays available after fallback retirement.

Actual workflow conditions, shell handoffs, failure retention, and provider call
bounds are exercised in test_ordinary_codespaces_no_gce_fallback.py.
"""

from __future__ import annotations

from pathlib import Path

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
    # The payload is copied to an independent path for evidence consumers.
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
        "the explicit GCE step must not touch the preserved Codespaces payload"
    )


def test_gce_step_keeps_writing_live_result_json() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    gce_block = _step_block(text, GCE_STEP, SUMMARY_STEP)
    # Explicit GCE requests retain their own result contract.
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


def test_discovery_routing_condition_requires_its_own_envelope() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(text, DISCOVERY_STEP, "Authenticate bounded Agent OS transport")
    assert "steps.transport.outputs.is_discovery == 'true'" in block
    assert "steps.route.outputs.preferred == 'codespaces'" in block
    assert "steps.transport.outputs.accepted == 'true'" in block
    assert "steps.codespaces.outputs.selected != 'true'" in block
