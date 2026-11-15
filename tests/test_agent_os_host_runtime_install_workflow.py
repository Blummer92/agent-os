"""GCE Wave 1: the governed host-install activation route is retired.

The workflow no longer classifies, authenticates, or runs a bounded #1238
host-runtime installation (owner decision #3333: no GCE reactivation or
reinstallation). The installer scripts themselves are preserved, so the
unprivileged/privileged installer invariant tests below stay and keep
passing against the untouched scripts.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
INSTALLER = ROOT / "08_Tooling/agent-os-execution-service/scripts/install-host-runtime"
PRIVILEGED_INSTALLER = (
    ROOT / "08_Tooling/agent-os-execution-service/scripts/agent-os-host-install"
)


def test_host_runtime_install_activation_is_retired_from_the_workflow() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "host_install" not in text
    assert "install-host-runtime" not in text
    assert "Classify bounded #1238 host-runtime installation" not in text
    assert "Install and verify bounded #1238 host runtime" not in text
    assert "/agent-os install-host-runtime" not in text
    assert "gcloud compute instances start" not in text
    assert "gcloud compute ssh" not in text
    assert "HOST_INSTALL_SCRIPT_SHA256" not in text
    assert "host-runtime-install-failed" not in text
    assert "host-install.stderr" not in text


def test_gcp_auth_has_no_host_install_shortcut() -> None:
    """Only accepted, specifically GCE-routed envelopes may authenticate."""
    text = WORKFLOW.read_text(encoding="utf-8")
    for step_name in (
        "Authenticate bounded Agent OS transport",
        "Install Google Cloud CLI",
    ):
        block = text.split(f"- name: {step_name}", 1)[1]
        condition = block.split("if:", 1)[1].split("\n", 1)[0]
        assert "host_install" not in condition
        assert "steps.route.outputs.preferred == 'gce'" in condition
        assert "steps.transport.outputs.accepted == 'true'" in condition


def test_source_sha_pin_survives_only_as_the_sudo_inspection_anchor() -> None:
    """Exactly one HOST_RUNTIME_SOURCE_SHA literal remains: the expected-SHA
    anchor for the surviving read-only sudo-admission inspection, which fails
    closed without exactly one pin. It sits in the top-level env block; no
    step consumes it for installation."""
    text = WORKFLOW.read_text(encoding="utf-8")
    pins = re.findall(r"HOST_RUNTIME_SOURCE_SHA: ([0-9a-f]{40})", text)
    assert pins == ["36ccd1715b8b11e30f8d92196b8e7f0791c10547"]
    assert "HOST_RUNTIME_SOURCE_SHA" not in text.split("jobs:", 1)[1]


def test_host_runtime_route_preserves_least_privilege_and_fixed_target() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "id-token: write" in permissions
    assert "issues:" not in permissions
    assert "contents: write" not in permissions
    assert "actions: write" not in permissions
    assert "compute instances stop" not in text
    assert '"scheduler_invoked": False' in text
    assert '"execution_authorized": False' in text


def test_host_runtime_installer_is_bounded_and_never_dispatches() -> None:
    """Unprivileged side: preflight and delegation only (hardened by #1341)."""
    text = INSTALLER.read_text(encoding="utf-8")
    assert "EXPECTED_SHA must be a lowercase 40-hex commit" in text
    assert "checkout must be on main" in text
    assert "qualified host must be Debian 12" in text
    assert 'sudo -n -l "$PRIVILEGED_INSTALLER"' in text
    assert "PRIVILEGED_INSTALLER=/usr/local/libexec/agent-os-host-install" in text
    assert "gcloud" not in text
    assert "compute instances" not in text
    assert "eval " not in text


def test_privileged_host_installer_owns_the_bounded_install_and_never_dispatches() -> (
    None
):
    """Privileged side: the moved steps, now sourced only from root-owned staging."""
    text = PRIVILEGED_INSTALLER.read_text(encoding="utf-8")
    assert "TARGET=/usr/local/libexec/agent-os-governed-resume" in text
    assert "STAGING_ROOT=/var/lib/agent-os/host-install-staging" in text
    assert "apt-get install -y build-essential python3-dev" in text
    for package in (
        "./08_Tooling/agent-memory-context-manager",
        "./08_Tooling/workflow-scheduler",
        "./08_Tooling/agent-os-execution-service",
    ):
        assert package in text
    assert "./08_Tooling/reusable-capability-registry" not in text
    # Flags now sit one per line so --no-index/--no-deps could be added
    # legibly; check each token rather than an exact adjacent substring.
    assert "--break-system-packages" in text
    assert "--force-reinstall" in text
    assert "--no-index" in text
    assert "--no-deps" in text
    # #3101/PR #3234 retired handoff_discovery_entrypoint: the installer must
    # no longer require the deleted module.
    assert "agent_os_execution_service.handoff_discovery_entrypoint" not in text
    assert "agent_os_execution_service.governed_resume_entrypoint" in text
    # #3311 retired clone3_cgroup_launcher/_clone3_cgroup: the installer must
    # no longer require the deleted native extension.
    assert "workflow_scheduler.execution._clone3_cgroup" not in text
    assert text.count("scripts/install-governed-resume") == 1
    assert text.count('sh "$entrypoint_installer"') == 2
    assert '[ "$metadata" = "root:root:755" ]' in text
    assert '"scheduler_invoked": False' in text
    assert "gcloud" not in text
    assert "compute instances" not in text
    assert "eval " not in text
    # Every path the privileged side reads is derived from STAGING_ROOT, never
    # from a caller-supplied value.
    assert "/tmp/" not in text
