"""Behavioral coverage for governed host hook re-entry (#1237/#2139)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
)
from scripts.agent_os_execution_interface import hook_adapter
from scripts.agent_os_execution_interface.governed_route_preflight import GOVERNED_CHECKOUT_MARKERS

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


def test_repository_identity_prefers_explicit_configuration(governed_checkout, monkeypatch):
    monkeypatch.setenv(hook_adapter.REPOSITORY_ENV, "Other/repo")
    assert hook_adapter.resolve_repository_identity(governed_checkout) == "Other/repo"


def test_repository_identity_is_none_without_a_remote(tmp_path, monkeypatch):
    monkeypatch.delenv(hook_adapter.REPOSITORY_ENV, raising=False)
    assert hook_adapter.resolve_repository_identity(tmp_path) is None


@pytest.fixture(params=("gh-absent", "gh-present"))
def local_gh(request, tmp_path, monkeypatch):
    path_dir = tmp_path / f"bin-{request.param}"
    path_dir.mkdir()
    if request.param == "gh-present":
        executable = path_dir / "gh"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(path_dir))
    assert (shutil.which("gh") is not None) is (request.param == "gh-present")
    return request.param


def test_work_on_1259_reaches_governed_resume_regardless_of_local_gh(governed_checkout, configured_env, local_gh):
    descriptor = _descriptor()
    append_invocation_descriptor(configured_env, descriptor)
    notice = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1259", "cwd": str(governed_checkout)})
    )
    assert f"/agent-os resume {descriptor.handoff_id}" in notice
    assert "Do not select generic GitHub publish tooling" in notice
    assert "never evidence that Agent OS execution is" in notice


def test_missing_handoff_continues_to_existing_publication_adapter(governed_checkout, configured_env):
    notice = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1117", "cwd": str(governed_checkout)})
    )
    assert "status=publication-required" in notice
    assert "continuation=execution-interface-adapter" in notice
    assert "publish_current_pre_pr_handoff(...)" in notice
    assert "publish_governed_handoff(...)" in notice
    assert "/agent-os resume executor-handoff:" not in notice


def test_prompt_hook_is_silent_outside_a_governed_checkout(tmp_path, configured_env):
    plain = tmp_path / "plain"
    plain.mkdir()
    append_invocation_descriptor(configured_env, _descriptor())
    assert hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1259", "cwd": str(plain)})
    ) == ""


def test_prompt_hook_is_silent_without_an_issue_reference(governed_checkout, configured_env):
    assert hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "summarize the README", "cwd": str(governed_checkout)})
    ) == ""


def test_prompt_hook_tolerates_malformed_payloads(configured_env):
    assert hook_adapter.run_user_prompt_submit_hook("") == ""
    assert hook_adapter.run_user_prompt_submit_hook("{not json") == ""
    assert hook_adapter.run_user_prompt_submit_hook("[]") == ""


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


def test_pre_tool_guard_restates_invariant_for_local_gh(governed_checkout):
    payload = hook_adapter.run_pre_tool_use_hook(
        json.dumps({"tool_name": "Bash", "tool_input": {"command": "which gh"}, "cwd": str(governed_checkout)})
    )
    decoded = json.loads(payload)
    context = decoded["hookSpecificOutput"]["additionalContext"]
    assert decoded["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "never evidence that Agent OS execution is" in context
    assert "permissionDecision" not in json.dumps(decoded)


def test_pre_tool_guard_reaches_github_mutation_tool_without_becoming_a_gate(governed_checkout):
    payload = hook_adapter.run_pre_tool_use_hook(
        json.dumps({"tool_name": "mcp__github__update_file", "tool_input": {}, "cwd": str(governed_checkout)})
    )
    decoded = json.loads(payload)
    context = decoded["hookSpecificOutput"]["additionalContext"]
    assert "Reacquire current repository" in context
    assert "grant no implementation" in context
    assert "permissionDecision" not in json.dumps(decoded)


def test_pre_tool_guard_is_silent_for_non_gh_bash_and_read(governed_checkout):
    assert hook_adapter.run_pre_tool_use_hook(
        json.dumps({"tool_name": "Bash", "tool_input": {"command": "git log -1"}, "cwd": str(governed_checkout)})
    ) == ""
    assert hook_adapter.run_pre_tool_use_hook(
        json.dumps({"tool_name": "Read", "tool_input": {"file_path": "gh"}, "cwd": str(governed_checkout)})
    ) == ""


def test_stop_blocks_once_for_structured_authorized_next_action(governed_checkout):
    raw = json.dumps(
        {
            "cwd": str(governed_checkout),
            "stop_hook_active": False,
            "agent_os_continuation": {
                "action": "create-draft-pr",
                "terminal": False,
                "blocked": False,
                "stalled": False,
                "reason_codes": ["authorized-next-action"],
            },
        }
    )
    decoded = json.loads(hook_adapter.run_stop_hook(raw))
    assert decoded["decision"] == "block"
    assert "create-draft-pr" in decoded["reason"]
    assert "grant no implementation" in decoded["reason"]


def test_stop_allows_reentry_after_one_block(governed_checkout):
    raw = json.dumps(
        {
            "cwd": str(governed_checkout),
            "stop_hook_active": True,
            "agent_os_continuation": {"action": "create-draft-pr"},
        }
    )
    assert hook_adapter.run_stop_hook(raw) == ""


@pytest.mark.parametrize(
    "observation",
    [
        {"action": "", "terminal": True, "blocked": False, "stalled": False, "reason_codes": []},
        {"action": "", "terminal": False, "blocked": True, "stalled": False, "reason_codes": ["authorization-boundary"]},
        {"action": "", "terminal": False, "blocked": False, "stalled": True, "reason_codes": ["recovery-stalled"]},
    ],
)
def test_stop_allows_terminal_blocked_and_stalled_states(governed_checkout, observation):
    assert hook_adapter.run_stop_hook(
        json.dumps({"cwd": str(governed_checkout), "agent_os_continuation": observation})
    ) == ""


def test_stop_evaluator_error_fails_open(governed_checkout):
    assert hook_adapter.run_stop_hook(
        json.dumps({"cwd": str(governed_checkout), "agent_os_continuation": {"action": 123}})
    ) == ""


# --- #3588: hook startup must not depend on PyYAML ---------------------------
#
# The locator import chain reaches PyYAML-backed issue-acceptance modules. A host
# hook interpreter without PyYAML (a Copilot CLI Codespace) crashed before any
# governed handling. These tests run the real hook entrypoint under an import
# blocker for ``yaml`` so the guarantee is proven end to end, not mocked.

_ENTRYPOINT = (
    Path(__file__).resolve().parents[2] / "scripts" / "agent-os-execution-interface-preflight.py"
)
_DISCOVERY_MODULE = "scripts.agent_os_execution_checkpoint.handoff_discovery"

_NO_YAML_RUNNER = """
import json, runpy, sys

class _BlockYaml:
    attempts = []

    def find_spec(self, name, path=None, target=None):
        if name == "yaml" or name.startswith("yaml.") or name == "_yaml":
            _BlockYaml.attempts.append(name)
            raise ModuleNotFoundError("No module named 'yaml'", name="yaml")
        return None

sys.meta_path.insert(0, _BlockYaml())
entrypoint, report, *argv = sys.argv[1:]
sys.argv = [entrypoint, *argv]
code = 0
try:
    runpy.run_path(entrypoint, run_name="__main__")
except SystemExit as exc:
    code = exc.code or 0
with open(report, "w", encoding="utf-8") as handle:
    json.dump(
        {
            "exit": code,
            "yaml_attempts": _BlockYaml.attempts,
            "discovery_imported": %r in sys.modules,
        },
        handle,
    )
""" % _DISCOVERY_MODULE


def _run_without_pyyaml(tmp_path, args, stdin="", *, extra_env=None):
    """Run the real hook entrypoint with ``yaml`` unimportable; return (proc, report)."""
    report = tmp_path / "no-yaml-report.json"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in (hook_adapter.STORE_ROOT_ENV, hook_adapter.REPOSITORY_ENV)
    }
    env.update(extra_env or {})
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _NO_YAML_RUNNER, str(_ENTRYPOINT), str(report), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )
    if not report.exists():
        pytest.fail(f"hook entrypoint crashed before completing (exit {proc.returncode}):\n{proc.stderr}")
    return proc, json.loads(report.read_text(encoding="utf-8"))


def _assert_started_cleanly(proc, report):
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 0, proc.stderr
    assert report["exit"] == 0


@pytest.mark.parametrize(
    "hook,payload_for,expected_stdout",
    [
        ("user-prompt-submit", lambda cwd: {"prompt": "summarize the README", "cwd": cwd}, ""),
        (
            "pre-tool-use",
            lambda cwd: {"tool_name": "Bash", "tool_input": {"command": "git status --short"}, "cwd": cwd},
            "",
        ),
        (
            "pre-tool-use",
            lambda cwd: {"toolName": "bash", "toolArgs": json.dumps({"command": "git rev-parse HEAD"}), "cwd": cwd},
            "",
        ),
        (
            "pre-tool-use",
            lambda cwd: {"tool_name": "Bash", "tool_input": {"command": "python3 --version"}, "cwd": cwd},
            "",
        ),
        ("stop", lambda cwd: {"cwd": cwd, "stop_hook_active": False}, ""),
    ],
    ids=("prompt", "claude-read-only", "copilot-read-only", "claude-python-version", "stop"),
)
def test_hook_entrypoint_starts_without_pyyaml_when_no_discovery_is_needed(
    tmp_path, governed_checkout, hook, payload_for, expected_stdout
):
    proc, report = _run_without_pyyaml(
        tmp_path,
        ["--hook", hook],
        json.dumps(payload_for(str(governed_checkout))),
    )

    _assert_started_cleanly(proc, report)
    assert proc.stdout.strip() == expected_stdout
    assert report["yaml_attempts"] == []
    assert report["discovery_imported"] is False


def test_pre_tool_guard_still_restates_invariant_without_pyyaml(tmp_path, governed_checkout):
    proc, report = _run_without_pyyaml(
        tmp_path,
        ["--hook", "pre-tool-use"],
        json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "which gh"}, "cwd": str(governed_checkout)}
        ),
    )

    _assert_started_cleanly(proc, report)
    decoded = json.loads(proc.stdout)
    assert "never evidence that Agent OS execution is" in decoded["hookSpecificOutput"]["additionalContext"]
    assert "permissionDecision" not in proc.stdout
    assert report["yaml_attempts"] == []
    assert report["discovery_imported"] is False


@pytest.mark.parametrize("hook", ("user-prompt-submit", "pre-tool-use", "stop"))
@pytest.mark.parametrize("raw", ("", "{not-valid-json", "[]"))
def test_malformed_hook_input_is_bounded_without_pyyaml(tmp_path, hook, raw):
    proc, report = _run_without_pyyaml(tmp_path, ["--hook", hook], raw)

    _assert_started_cleanly(proc, report)
    assert proc.stdout.strip() == ""
    assert report["yaml_attempts"] == []
    assert report["discovery_imported"] is False


def test_unconfigured_store_stays_needs_decision_without_importing_discovery(tmp_path, governed_checkout):
    proc, report = _run_without_pyyaml(
        tmp_path,
        ["--hook", "user-prompt-submit"],
        json.dumps({"prompt": "Work on #1259", "cwd": str(governed_checkout)}),
    )

    _assert_started_cleanly(proc, report)
    assert "status=needs-decision" in proc.stdout
    assert "descriptor-store-not-configured" in proc.stdout
    assert "/agent-os resume" not in proc.stdout
    assert report["yaml_attempts"] == []
    assert report["discovery_imported"] is False


def test_required_discovery_without_pyyaml_fails_closed_and_never_synthesizes_a_handoff(
    tmp_path, governed_checkout, configured_env
):
    # A valid descriptor exists, so a success here would prove a synthetic or
    # stale answer: with the locator unimportable the only honest result is the
    # bounded needs-decision.
    append_invocation_descriptor(configured_env, _descriptor())

    proc, report = _run_without_pyyaml(
        tmp_path,
        [
            "--checkout-root", str(governed_checkout),
            "--repository", REPOSITORY,
            "--issue", "1259",
            "--store-root", str(configured_env),
        ],
    )

    _assert_started_cleanly(proc, report)
    decoded = json.loads(proc.stdout.splitlines()[0])
    assert decoded["status"] == "needs-decision"
    assert decoded["reason_codes"] == ["discovery-dependency-unavailable"]
    assert decoded["handoff_id"] is None
    assert decoded["resume_command"] is None
    for flag in (
        "repository_implementation_authorized",
        "execution_authorized",
        "github_writes_authorized",
        "merge_authorized",
        "issue_closure_authorized",
        "external_writes_authorized",
        "scheduler_invoked",
        "handoff_persisted",
        "side_effects_performed",
        "local_gh_absence_is_execution_blocker",
    ):
        assert decoded[flag] is False
    assert "executor-handoff:" not in proc.stdout
    assert report["discovery_imported"] is False


def test_prompt_hook_reports_unavailable_discovery_dependency_as_needs_decision(
    governed_checkout, configured_env, monkeypatch
):
    append_invocation_descriptor(configured_env, _descriptor())
    # ``None`` in sys.modules makes the lazy locator import raise ImportError.
    monkeypatch.setitem(sys.modules, _DISCOVERY_MODULE, None)

    notice = hook_adapter.run_user_prompt_submit_hook(
        json.dumps({"prompt": "Work on #1259", "cwd": str(governed_checkout)})
    )

    assert "status=needs-decision" in notice
    assert "discovery-dependency-unavailable" in notice
    assert "Fail closed." in notice
    assert "/agent-os resume" not in notice
    assert "executor-handoff:" not in notice
