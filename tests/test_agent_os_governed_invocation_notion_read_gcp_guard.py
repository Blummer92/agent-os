from __future__ import annotations

"""Regression coverage for #2940: notion-read envelopes must never trigger GCP setup.

An accepted `/agent-os notion-read` envelope is a GitHub-hosted read. Before
this fix it fell through generic routing to GCE, so the "Authenticate bounded
Agent OS transport" and "Install Google Cloud CLI" steps ran Workload Identity
authentication and gcloud setup for a cloud-free operation. The workflow now
emits `is_notion_read` from the transport parse step and both GCP steps gate on
it. The low-level GCE refusal in `gce_gcloud_adapter.execute_transport`
(`notion-read-not-gce-routable`) remains as defense in depth.
"""

from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
GCE_ADAPTER = (
    ROOT
    / "08_Tooling/workflow-scheduler/src/workflow_scheduler/governance/gce_gcloud_adapter.py"
)

GCP_STEP_NAMES = (
    "Authenticate bounded Agent OS transport",
    "Install Google Cloud CLI",
)
GUARD = "steps.transport.outputs.is_notion_read != 'true'"


def _step_block(text: str, step_name: str, next_step_name: str) -> str:
    return text.split(f"- name: {step_name}", 1)[1].split(
        f"- name: {next_step_name}", 1
    )[0]


def test_transport_parse_step_emits_is_notion_read() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = _step_block(
        text,
        "Parse low-trust issue comment envelope",
        "Resolve Codespaces-first transport route",
    )
    assert "is_notion_read=" in block
    assert "accepted-notion-read-envelope" in block


def test_gcp_setup_steps_skip_notion_read_envelopes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    auth_block = _step_block(
        text,
        "Authenticate bounded Agent OS transport",
        "Install Google Cloud CLI",
    )
    gcloud_block = _step_block(
        text,
        "Install Google Cloud CLI",
        "Install and verify bounded #1238 host runtime",
    )
    for step_name, block in (
        ("Authenticate bounded Agent OS transport", auth_block),
        ("Install Google Cloud CLI", gcloud_block),
    ):
        assert GUARD in block, f"{step_name} is missing the notion-read guard"
        # The host-install short-circuit must survive: a requested install still
        # authenticates regardless of the envelope kind.
        assert "steps.host_install.outputs.requested == 'true' ||" in block


def test_guard_is_scoped_to_the_two_gcp_setup_steps() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count(GUARD) == len(GCP_STEP_NAMES), (
        "the notion-read guard must appear exactly on the two GCP setup steps; "
        "a wider or narrower spread changes unrelated routing behavior"
    )


def test_gce_control_path_keeps_notion_read_refusal_as_defense_in_depth() -> None:
    adapter = GCE_ADAPTER.read_text(encoding="utf-8")
    assert 'ingress.reason=="accepted-notion-read-envelope"' in adapter
    assert "notion-read-not-gce-routable" in adapter
