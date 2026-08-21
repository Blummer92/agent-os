"""Hook-surface coverage for the #1237 pre-tool governed-route seam.

The product-level regression is `Work on #1259` with local `gh` unavailable:
the interface must reach handoff discovery and the existing immutable governed
resume ingress instead of a generic publish path gated on a local CLI.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
)
from scripts.agent_os_execution_interface import hook_adapter
from scripts.agent_os_execution_interface.governed_route_preflight import (
    GOVERNED_CHECKOUT_MARKERS,
)

REPOSITORY = "Blummer92/agent-os"


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{hashlib.sha256(label.encode('utf-8')).hexdigest()}"


def _descriptor(label: str = "one", issue_number: int = 1259) -> GovernedInvocationDescriptor:
    return GovernedInvocationDescriptor(
        schema_name=INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        schema_version=INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        repository=REPOSITORY,
        issue_number=issue_number,
        issue_or_handoff_identity=f"issue:{issue_number}",
        handoff_id=_id("executor-handoff", f"handoff-{label}"),
        route_decision_id=_id("executor-route-decision", f"route-{label}"),
        execution_service_request_fingerprint=_id("execution-request", f"request-{label}"),
        authorization_id=_id("authorization", f"authorization-{label}"),
        source_ref="refs/heads/agent/1259-governed-route",
        source_sha="a" * 40,
        checkpoint_id=_id("agent-os.execution-checkpoint", f"checkpoint-{label}"),
        resume_plan_id=_id("agent-os.execution-checkpoint.resume-plan", f"resume-{label}"),
        environment_profile_id=_id("environment-profile", f"profile-{label}"),
        environment_health_evidence_id=_id("environment-health", f"health-{label}"),
        required_environment_id=_id("required-environment", f"required-{label}"),
        dependency_readiness_evidence_id=_id("dependency-readiness", f"readiness-{label}"),
        execution_surface_id="execution-surface:gce-agent-os-test",
        workspace_identity=_id("pilot-workspace", f"workspace-{label}"),
        workflow_runtime_identity=_id("workflow-runtime", f"runtime-{label}"),
        candidate_packet_id=_id("candidate-packet", f"packet-{label}"),
        runtime_configuration_fingerprint=_id("concrete-adapters", f"configuration-{label}"),
        execution_id=f"execution-{issue_number}-{label}",
        invocation_id=f"invocation-{issue_number}-{label}",
    )


@pytest.fixture
def governed_checkout(tmp_path):
    root = tmp_path / "checkout"
    for marker in GOVERNED_CHECKOUT_MARKERS:
        path = root / marker
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("marker\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        '[core]\n\trepositoryformatversion = 0\n'
        '[remote "origin"]\n'
        "\turl = https://github.com/Blummer92/agent-os.git\n"
        "\tfetch = +refs/heads/*:refs/remotes/origin/*\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def configured_env(monkeypatch, tmp_path):
    store_root = tmp_path / "store"
    monkeypatch.setenv(hook_adapter.STORE_ROOT_ENV, str(store_root))
    monkeypatch.delenv(hook_adapter.REPOSITORY_ENV, raising=False)
    return store_root


# --- issue-key extraction is a lookup key, never authority ------------------


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("Work on #1259", (1259,)),
        ("work 1259", ()),
        ("see #1259 and #1239", (1259, 1239)),
        ("#1259 again #1259", (1259,)),
        ("#0 is not a real issue", ()),
        ("colors #abc123 are not issues", ()),
        ("", ()),
        (None, ()),
    ],
)
def test_extract_issue_numbers(prompt, expected):
    assert hook_adapter.extract_issue_numbers(prompt) == expected


def test_repository_identity_resolves_from_git_remote(governed_checkout, monkeypatch):
    monkeypatch.delenv(hook_adapter.REPOSITORY_ENV, raising=False)
    assert hook_adapter.resolve_repository_identity(governed_checkout) == REPOSITORY


def test_repository_identity_prefers_explicit_configuration(
    governed_checkout, monkeypatch
):
    monkeypatch.setenv(hook_adapter.REPOSITORY_ENV, "Other/repo")
    assert hook_adapter.resolve_repository_identity(governed_checkout) == "Other/repo"


def test_repository_identity_is_none_without_a_remote(tmp_path, monkeypatch):
    monkeypatch.delenv(hook_adapter.REPOSITORY_ENV, raising=False)
    assert hook_adapter.resolve_repository_identity(tmp_path) is None


# --- key regression: `Work on #1259`, with and without a local `gh` ---------


@pytest.fixture(params=("gh-absent", "gh-present"))
def local_gh(request, tmp_path, monkeypatch):
    """Control whether a local `gh` is on PATH, instead of trusting the runner.

    The governed route must win either way, so both cases are asserted
    deterministically rather than inherited from whatever CI happens to install.
    """
    path_dir = tmp_path / f"bin-{request.param}"
    path_dir.mkdir()
    if request.param == "gh-present":
        executable = path_dir / "gh"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_dir))
    assert (shutil.which("gh") is not None) is (request.param == "gh-present")
    return request.param


def test_work_on_1259_reaches_governed_resume_regardless_of_local_gh(
    governed_checkout, configured_env, local_gh
):
    descriptor = _descriptor()
    append_invocation_descriptor(configured_env, descriptor)

    notice = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1259", "cwd": str(governed_checkout)})
    )

    assert f"/agent-os resume {descriptor.handoff_id}" in notice
    assert "Do not select generic GitHub publish tooling" in notice
    assert "never evidence that Agent OS execution is" in notice


def test_prompt_hook_is_silent_outside_a_governed_checkout(tmp_path, configured_env):
    plain = tmp_path / "plain"
    plain.mkdir()
    append_invocation_descriptor(configured_env, _descriptor())

    output = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1259", "cwd": str(plain)})
    )

    assert output == ""


def test_prompt_hook_is_silent_without_an_issue_reference(
    governed_checkout, configured_env
):
    output = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "summarize the README", "cwd": str(governed_checkout)})
    )

    assert output == ""


def test_prompt_hook_fails_closed_when_the_store_is_unconfigured(
    governed_checkout, monkeypatch
):
    monkeypatch.delenv(hook_adapter.STORE_ROOT_ENV, raising=False)
    monkeypatch.delenv(hook_adapter.REPOSITORY_ENV, raising=False)

    notice = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1259", "cwd": str(governed_checkout)})
    )

    assert "status=needs-decision" in notice
    assert "descriptor-store-not-configured" in notice
    assert "/agent-os resume" not in notice


def test_prompt_hook_tolerates_malformed_payloads(configured_env):
    assert hook_adapter.run_user_prompt_submit_hook("") == ""
    assert hook_adapter.run_user_prompt_submit_hook("{not json") == ""
    assert hook_adapter.run_user_prompt_submit_hook("[]") == ""


# --- pre-tool guard: missing local gh never becomes an Agent OS blocker -----


@pytest.mark.parametrize(
    "command,expected",
    [
        ("gh pr create", True),
        ("which gh", True),
        ("command -v gh", True),
        ("gh --version", True),
        ("git status", False),
        ("echo alright", False),
        ("./tools/gh-helper.sh", False),
        (None, False),
    ],
)
def test_references_local_gh(command, expected):
    assert hook_adapter.references_local_gh(command) is expected


def test_pre_tool_guard_restates_the_invariant_for_gh_probes(governed_checkout):
    payload = hook_adapter.run_pre_tool_use_hook(
        json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "which gh"},
                "cwd": str(governed_checkout),
            }
        )
    )

    decoded = json.loads(payload)
    context = decoded["hookSpecificOutput"]["additionalContext"]
    assert decoded["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "never evidence that Agent OS execution is" in context
    assert "/agent-os resume" in context
    # advisory only: the guard must never deny or pre-approve a tool call
    assert "permissionDecision" not in json.dumps(decoded)


def test_pre_tool_guard_is_silent_for_non_gh_and_non_bash_calls(governed_checkout):
    assert (
        hook_adapter.run_pre_tool_use_hook(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "git log -1"},
                    "cwd": str(governed_checkout),
                }
            )
        )
        == ""
    )
    assert (
        hook_adapter.run_pre_tool_use_hook(
            json.dumps(
                {
                    "tool_name": "Read",
                    "tool_input": {"file_path": "gh"},
                    "cwd": str(governed_checkout),
                }
            )
        )
        == ""
    )


def test_pre_tool_guard_is_silent_outside_a_governed_checkout(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    assert (
        hook_adapter.run_pre_tool_use_hook(
            json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "gh pr create"},
                    "cwd": str(plain),
                }
            )
        )
        == ""
    )
