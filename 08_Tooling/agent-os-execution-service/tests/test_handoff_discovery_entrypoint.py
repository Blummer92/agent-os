from __future__ import annotations

import hashlib
import json

import pytest

from agent_os_execution_service.handoff_discovery_entrypoint import (
    DiscoveryRequestError,
    STORE_ROOT_ENV,
    main,
    parse_discovery_argv,
    resolve_store_root,
    run_handoff_discovery,
)
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME,
    INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor,
    append_invocation_descriptor,
)

REPOSITORY = "Blummer92/agent-os"
ISSUE = 1284


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _id(prefix: str, label: str) -> str:
    return f"{prefix}:{_digest(label)}"


def _descriptor(label: str = "one", **overrides: object) -> GovernedInvocationDescriptor:
    values: dict[str, object] = {
        "schema_name": INVOCATION_DESCRIPTOR_SCHEMA_NAME,
        "schema_version": INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        "repository": REPOSITORY,
        "issue_number": ISSUE,
        "issue_or_handoff_identity": f"issue:{ISSUE}",
        "handoff_id": _id("executor-handoff", f"handoff-{label}"),
        "route_decision_id": _id("executor-route-decision", f"route-{label}"),
        "execution_service_request_fingerprint": _id(
            "execution-request", f"request-{label}"
        ),
        "authorization_id": _id("authorization", f"authorization-{label}"),
        "source_ref": "refs/heads/agent/1284-github-native-handoff-discovery",
        "source_sha": "a" * 40,
        "checkpoint_id": _id("agent-os.execution-checkpoint", f"checkpoint-{label}"),
        "resume_plan_id": _id(
            "agent-os.execution-checkpoint.resume-plan", f"resume-{label}"
        ),
        "environment_profile_id": _id("environment-profile", f"profile-{label}"),
        "environment_health_evidence_id": _id("environment-health", f"health-{label}"),
        "required_environment_id": _id("required-environment", f"required-{label}"),
        "dependency_readiness_evidence_id": _id(
            "dependency-readiness", f"readiness-{label}"
        ),
        "execution_surface_id": "execution-surface:gce-agent-os-test",
        "workspace_identity": _id("pilot-workspace", f"workspace-{label}"),
        "workflow_runtime_identity": _id("workflow-runtime", f"runtime-{label}"),
        "candidate_packet_id": _id("candidate-packet", f"packet-{label}"),
        "runtime_configuration_fingerprint": _id(
            "concrete-adapters", f"configuration-{label}"
        ),
        "execution_id": f"execution-{ISSUE}-{label}",
        "invocation_id": f"invocation-{ISSUE}-{label}",
    }
    values.update(overrides)
    return GovernedInvocationDescriptor(**values)


def _discover(tmp_path, *, repository: str = REPOSITORY, issue: int = ISSUE) -> dict:
    return json.loads(
        run_handoff_discovery(
            ["--repository", repository, "--issue-number", str(issue)],
            environ={STORE_ROOT_ENV: str(tmp_path)},
        )
    )


def _assert_never_authorizes(payload: dict) -> None:
    assert payload["execution_authorized"] is False
    assert payload["scheduler_invoked"] is False
    assert payload["side_effects_performed"] is False


def test_exactly_one_descriptor_returns_the_existing_handoff(tmp_path) -> None:
    descriptor = _descriptor()
    append_invocation_descriptor(tmp_path, descriptor)
    payload = _discover(tmp_path)
    assert payload["status"] == "found"
    assert payload["handoff_id"] == descriptor.handoff_id
    assert payload["matching_descriptor_count"] == 1
    assert payload["repository"] == REPOSITORY
    assert payload["issue_number"] == ISSUE
    _assert_never_authorizes(payload)


def test_zero_matches_is_not_found_without_a_fabricated_handoff(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor(issue_number=999))
    payload = _discover(tmp_path)
    assert payload["status"] == "not-found"
    assert payload["handoff_id"] is None
    assert payload["matching_descriptor_count"] == 0
    _assert_never_authorizes(payload)


def test_multiple_matches_are_needs_decision_and_never_pick_latest(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor("one"))
    append_invocation_descriptor(tmp_path, _descriptor("two"))
    payload = _discover(tmp_path)
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["multiple-matching-descriptors"]
    assert payload["handoff_id"] is None
    assert payload["matching_descriptor_count"] == 2
    _assert_never_authorizes(payload)


def test_corrupt_descriptor_fails_closed(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor())
    corrupt = next((tmp_path / "invocations").glob("*.json"))
    corrupt.write_text("{not json", encoding="utf-8")
    payload = _discover(tmp_path)
    assert payload["status"] == "needs-decision"
    assert payload["handoff_id"] is None
    _assert_never_authorizes(payload)


def test_unconfigured_store_root_is_needs_decision_not_a_default_path() -> None:
    payload = json.loads(
        run_handoff_discovery(
            ["--repository", REPOSITORY, "--issue-number", str(ISSUE)], environ={}
        )
    )
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["store-not-configured"]
    assert payload["handoff_id"] is None
    _assert_never_authorizes(payload)


def test_blank_store_root_is_also_unconfigured() -> None:
    assert resolve_store_root({STORE_ROOT_ENV: "   "}) is None
    assert resolve_store_root({}) is None
    assert resolve_store_root({STORE_ROOT_ENV: "/srv/agent-os"}) == "/srv/agent-os"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--repository", REPOSITORY],
        ["--repository", REPOSITORY, "--issue-number", str(ISSUE), "--extra"],
        ["--issue-number", str(ISSUE), "--repository", REPOSITORY],
        ["--repository", REPOSITORY, "--issue-number", "0"],
        ["--repository", REPOSITORY, "--issue-number", "-3"],
        ["--repository", REPOSITORY, "--issue-number", "12a"],
        ["--store-root", "/tmp", "--repository", REPOSITORY],
    ],
)
def test_noncanonical_argv_is_rejected(argv: list[str]) -> None:
    with pytest.raises(DiscoveryRequestError):
        parse_discovery_argv(argv)


def test_caller_cannot_supply_a_store_root(tmp_path) -> None:
    """The store root is host composition; argv can never redirect the scan."""
    append_invocation_descriptor(tmp_path, _descriptor())
    with pytest.raises(DiscoveryRequestError):
        parse_discovery_argv(
            [
                "--repository",
                REPOSITORY,
                "--issue-number",
                str(ISSUE),
                "--store-root",
                str(tmp_path),
            ]
        )


def test_invalid_request_never_scans_a_store(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor())
    payload = json.loads(
        run_handoff_discovery(
            ["--repository", REPOSITORY], environ={STORE_ROOT_ENV: str(tmp_path)}
        )
    )
    assert payload["status"] == "needs-decision"
    assert payload["reason_codes"] == ["invalid-request"]
    assert payload["handoff_id"] is None


def test_shell_and_prose_text_cannot_become_a_repository(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor())
    for hostile in (
        "Blummer92/agent-os; rm -rf /",
        "executor-handoff:" + "b" * 64,
        "../../etc",
    ):
        payload = _discover(tmp_path, repository=hostile)
        assert payload["status"] == "needs-decision"
        assert payload["handoff_id"] is None


def test_replay_returns_the_same_identity_and_result(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor())
    first = _discover(tmp_path)
    second = _discover(tmp_path)
    assert first == second
    assert first["result_id"] == second["result_id"]
    assert first["handoff_id"] == second["handoff_id"]


def test_repository_matching_is_case_insensitive(tmp_path) -> None:
    descriptor = _descriptor()
    append_invocation_descriptor(tmp_path, descriptor)
    payload = _discover(tmp_path, repository="blummer92/AGENT-OS")
    assert payload["status"] == "found"
    assert payload["handoff_id"] == descriptor.handoff_id


def test_discovery_never_writes_to_the_store(tmp_path) -> None:
    append_invocation_descriptor(tmp_path, _descriptor())
    before = {
        path.name: path.read_bytes() for path in (tmp_path / "invocations").iterdir()
    }
    _discover(tmp_path)
    _discover(tmp_path, issue=999)
    after = {
        path.name: path.read_bytes() for path in (tmp_path / "invocations").iterdir()
    }
    assert before == after


def test_cli_prints_one_bounded_projection(tmp_path, capsys) -> None:
    descriptor = _descriptor()
    append_invocation_descriptor(tmp_path, descriptor)
    monkeyed = {STORE_ROOT_ENV: str(tmp_path)}
    import agent_os_execution_service.handoff_discovery_entrypoint as module

    original = module.os.environ
    module.os.environ = monkeyed  # type: ignore[assignment]
    try:
        assert main(["--repository", REPOSITORY, "--issue-number", str(ISSUE)]) == 0
    finally:
        module.os.environ = original  # type: ignore[assignment]
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["status"] == "found"
    assert payload["handoff_id"] == descriptor.handoff_id
    _assert_never_authorizes(payload)


def _installer():
    import pathlib

    return pathlib.Path(__file__).parents[1] / "scripts" / "install-handoff-discovery"


def _installer_env(target, **overrides: str) -> dict:
    import os
    import subprocess

    env = os.environ | {
        "TARGET": str(target),
        "OWNER": subprocess.check_output(["id", "-un"], text=True).strip(),
        "GROUP": subprocess.check_output(["id", "-gn"], text=True).strip(),
        "MODE": "0755",
        "STORE_ROOT": "/var/lib/agent-os/checkpoints",
    }
    env.update(overrides)
    return env


def test_installer_contract_is_fixed_and_idempotent(tmp_path) -> None:
    import hashlib
    import stat
    import subprocess

    target = tmp_path / "agent-os-handoff-discovery"
    env = _installer_env(target)
    subprocess.run([str(_installer())], check=True, env=env)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    subprocess.run([str(_installer())], check=True, env=env)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert stat.S_IMODE(target.stat().st_mode) == 0o755
    text = target.read_text()
    assert "python3 -m agent_os_execution_service.handoff_discovery_entrypoint" in text
    assert '"$@"' in text
    # The store root is fixed at install time, never taken from the caller.
    assert "AGENT_OS_CHECKPOINT_STORE_ROOT=/var/lib/agent-os/checkpoints" in text
    # A read-only locator needs no delegated execution scope.
    assert "systemd-run" not in text


def test_installer_refuses_unrelated_target(tmp_path) -> None:
    import subprocess

    proc = subprocess.run(
        [str(_installer())],
        env=_installer_env(tmp_path / "not-the-entrypoint"),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 64
    assert "refusing unexpected target" in proc.stderr


@pytest.mark.parametrize(
    "store_root", ["relative/path", "/srv/../etc", "/srv/agent os", "/srv/$(whoami)"]
)
def test_installer_refuses_unsafe_store_root(tmp_path, store_root: str) -> None:
    import subprocess

    proc = subprocess.run(
        [str(_installer())],
        env=_installer_env(
            tmp_path / "agent-os-handoff-discovery", STORE_ROOT=store_root
        ),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 64
    assert not (tmp_path / "agent-os-handoff-discovery").exists()


def test_installed_wrapper_ignores_a_caller_supplied_store_root(tmp_path) -> None:
    """A forwarded environment must never redirect the canonical scan."""
    import os
    import subprocess

    store = tmp_path / "store"
    descriptor = _descriptor()
    append_invocation_descriptor(store, descriptor)
    target = tmp_path / "agent-os-handoff-discovery"
    subprocess.run(
        [str(_installer())],
        check=True,
        env=_installer_env(target, STORE_ROOT=str(store)),
    )
    import pathlib

    here = pathlib.Path(__file__).resolve()
    repo_root = here.parents[3]
    service_src = here.parents[1] / "src"
    env = os.environ | {
        # A hostile caller sets the store root; the wrapper must overwrite it.
        "AGENT_OS_CHECKPOINT_STORE_ROOT": str(tmp_path / "attacker"),
        "PYTHONPATH": os.pathsep.join(
            [os.fspath(repo_root), os.fspath(service_src)]
            + [p for p in [os.environ.get("PYTHONPATH")] if p]
        ),
    }
    proc = subprocess.run(
        [str(target), "--repository", REPOSITORY, "--issue-number", str(ISSUE)],
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["status"] == "found"
    assert payload["handoff_id"] == descriptor.handoff_id
