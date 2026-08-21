from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
INSTALLER = ROOT / "08_Tooling/agent-os-execution-service/scripts/install-host-runtime"


def test_host_runtime_route_is_exact_owner_bound_and_main_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '[ "$GITHUB_RUN_ATTEMPT" = "1" ]' in text
    assert '[ "$EVENT_NAME" = "issue_comment" ]' in text
    assert '[ "$REPOSITORY_ID" = "1289370915" ]' in text
    assert '[ "$COMMENT_USER_ID" = "32861845" ]' in text
    assert '[ "$ISSUE_NUMBER" = "1238" ]' in text
    assert '[ "$REF_NAME" = "refs/heads/main" ]' in text
    assert (
        "Blummer92/agent-os/.github/workflows/agent-os-governed-invocation.yml@refs/heads/main"
        in text
    )
    assert '[ "$COMMENT_BODY" = "/agent-os install-host-runtime" ]' in text
    assert "workflow_dispatch" not in text


def test_host_runtime_route_preserves_least_privilege_and_fixed_target() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "id-token: write" in permissions
    assert "issues:" not in permissions
    assert "contents: write" not in permissions
    assert "actions: write" not in permissions
    assert "secrets." not in text
    assert 'project="agent-os-502614"' in text
    assert 'zone="us-central1-a"' in text
    assert 'instance="agent-os-test"' in text
    assert "compute instances stop" not in text
    assert '"scheduler_invoked": False' in text
    assert '"execution_authorized": False' in text


def test_host_runtime_route_pins_source_and_installer_integrity() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    source = re.search(r"HOST_RUNTIME_SOURCE_SHA: ([0-9a-f]{40})", text)
    installer = re.search(r"HOST_INSTALL_SCRIPT_SHA256: ([0-9a-f]{64})", text)
    assert source is not None
    assert installer is not None
    assert "sha256sum -c -" in text
    assert "gcloud compute scp" not in text
    assert 'installer="\\$root/08_Tooling/agent-os-execution-service/scripts/install-host-runtime"' in text
    assert 'git -C "\\$root" checkout --quiet -B main $HOST_RUNTIME_SOURCE_SHA' in text
    assert "COMMENT_BODY" not in text.split("remote_command=$(cat <<EOF_REMOTE", 1)[1]


def test_host_runtime_installer_is_bounded_and_never_dispatches() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "TARGET=/usr/local/libexec/agent-os-governed-resume" in text
    assert "EXPECTED_SHA must be a lowercase 40-hex commit" in text
    assert "checkout must be on main" in text
    assert "qualified host must be Debian 12" in text
    assert "sudo -n true" in text
    assert "apt-get install -y build-essential python3-dev" in text
    for package in (
        "./08_Tooling/reusable-capability-registry",
        "./08_Tooling/agent-memory-context-manager",
        "./08_Tooling/workflow-scheduler",
        "./08_Tooling/agent-os-execution-service",
    ):
        assert package in text
    assert "--break-system-packages --force-reinstall" in text
    assert "agent_os_execution_service.handoff_discovery_entrypoint" in text
    assert "agent_os_execution_service.governed_resume_entrypoint" in text
    assert "workflow_scheduler.execution._clone3_cgroup" in text
    assert text.count("scripts/install-governed-resume") == 2
    assert '[ "$metadata" = "root:root:755" ]' in text
    assert '"scheduler_invoked": False' in text
    assert "gcloud" not in text
    assert "compute instances" not in text
    assert "eval " not in text
