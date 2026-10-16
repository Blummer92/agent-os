"""#3333 causal-boundary regressions; stdlib tests also collected by pytest.

Only injected callbacks run. No payload process, SSH, credentials or network
is used. Existing pytest suites remain owed on the published exact head.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts.agent_os_execution_interface.codespaces_orchestrator_transport import (
    CodespaceCandidate, TransportReason, TransportRequest, TransportStatus,
    run_codespace_transport, validate_argv,
)

REPOSITORY = "Blummer92/agent-os"
BASE = "f6849de75dddde737215e333f807f99c3e444c02"


class CodespaceTransportContractTests(unittest.TestCase):
    def request(self, argv=("git", "status", "--short"), **overrides):
        fields = dict(repository=REPOSITORY, issue_identity="3333",
                      admission_id="admission-3333", argv=argv,
                      base_sha_or_none=BASE, workdir_or_none="/workspaces/agent-os")
        fields.update(overrides)
        return TransportRequest(**fields)

    def candidate(self, name="qualified", state="Available"):
        return CodespaceCandidate(name=name, state=state,
                                  repository_full_name=REPOSITORY, owner_login="Blummer92")

    def test_wrappers_paths_clients_and_helper_options_stop_before_discovery(self):
        attempts = (
            ("git", "push", "origin", "main"), ("gh", "issue", "create"),
            ("/usr/bin/git", "push", "origin", "main"),
            ("/usr/bin/gh", "issue", "create"), ("./git", "status"),
            ("sh", "-c", "git push origin main"), ("bash", "-lc", "gh issue create"),
            ("python", "-c", "import subprocess; subprocess.run(['git','push'])"),
            ("python3", "script.py"), ("python", "-m", "pip", "install", "anything"),
            ("env", "git", "push"), ("curl", "-X", "POST", "https://api.github.com"),
            ("hub", "pull-request"), ("git", "-c", "alias.publish=!git push", "publish"),
            ("git", "--exec-path=/tmp", "status"), ("git", "config", "alias.publish", "!gh api"),
            ("git", "diff", "--ext-diff"), ("git", "show", "--textconv"),
            ("rg", "--pre", "git push", "pattern"),
            ("pytest", "-p", "unknown_plugin", "tests/x.py"),
            ("python", "-m", "pytest", "--override-ini", "addopts=-p unknown"),
            ("pytest", "../foreign/test_x.py"), ("git", "worktree", "add", "-b", "main", "/tmp/w"),
        )
        for argv in attempts:
            with self.subTest(argv=argv):
                seen = []
                def discover():
                    seen.append("discovery")
                    return (self.candidate(),)
                result = run_codespace_transport(self.request(argv), list_candidates=discover,
                                                run=lambda *a, **k: seen.append("run"))
                self.assertEqual(result.status, TransportStatus.REJECTED)
                self.assertEqual(result.reason_codes, (TransportReason.FORBIDDEN_COMMAND,))
                self.assertEqual(seen, [])
                self.assertIsNone(result.started_at_or_none)
                self.assertIsNone(result.ended_at_or_none)

    def test_supported_finite_families_preserve_existing_commands(self):
        for argv in (("git", "rev-parse", "HEAD"), ("git", "status", "--short"),
                     ("git", "worktree", "add", "--detach", "/tmp/w", BASE),
                     ("git", "worktree", "add", "-b", "agent/3333", "/tmp/w", BASE),
                     ("git", "diff", "--check"), ("git", "show", "--stat", "HEAD"),
                     ("git", "log", "--oneline", "--max-count=10"),
                     ("rg", "--files", "scripts"), ("rg", "-n", "transport", "scripts"),
                     ("python", "-m", "pytest", "tests/x"),
                     ("python3", "-m", "pytest", "-q", "tests/x.py::test_case"),
                     ("pytest", "-x", "08_Tooling/workflow-scheduler/tests")):
            with self.subTest(argv=argv):
                self.assertIsNone(validate_argv(argv))

    def test_data_bounds_refuse_control_characters_and_oversized_argv(self):
        for argv in ((), ("git", ""), ("git", "a\x00b"), ("rg", "a\nb"),
                     ("rg", "x" * 4097), ("git",) * 65, ("rg",) + ("x" * 4096,) * 5):
            with self.subTest(argv=argv[:2]):
                self.assertEqual(validate_argv(argv), TransportReason.INVALID_REQUEST)
                with self.assertRaises(ValueError):
                    self.request(argv)

    def test_ssh_quotes_data_without_turning_it_into_a_command(self):
        argv = ("rg", "-e", "$(git push); 'quoted' pattern", "scripts")
        calls = []
        result = run_codespace_transport(self.request(argv),
                  list_candidates=lambda: (self.candidate(),),
                  run=lambda args, **k: (calls.append(args) or (0, "ok", "")))
        self.assertEqual(result.status, TransportStatus.COMPLETED)
        # Deterministic workdir contract (#3333 Option B): the remote command
        # is pinned under `cd <validated root> &&`; the admitted argv still
        # round-trips as quoted data, never as shell commands.
        self.assertEqual(shlex.split(" ".join(calls[0][6:])),
                         ["cd", "/workspaces/agent-os", "&&", *argv])
        self.assertEqual(result.argv, argv)
        self.assertEqual(len(calls), 1)

    def test_start_end_profile_and_monotonic_duration_are_returned(self):
        stamps = iter((datetime(2026, 10, 13, 1, 0, tzinfo=timezone.utc),
                       datetime(2026, 10, 13, 1, 0, 2, tzinfo=timezone.utc)))
        with patch("scripts.agent_os_execution_interface.codespaces_orchestrator_transport.time.monotonic",
                   side_effect=(10.0, 11.5)):
            result = run_codespace_transport(
                self.request(execution_profile_or_none="agent-os-codespaces-v1",
                             environment_health_evidence_or_none="health-3333"),
                list_candidates=lambda: (self.candidate(),),
                run=lambda *a, **k: (2, "output", "test-failed"), utc_now=lambda: next(stamps))
        payload = result.to_dict()
        self.assertEqual(payload["started_at_or_none"], "2026-10-13T01:00:00.000Z")
        self.assertEqual(payload["ended_at_or_none"], "2026-10-13T01:00:02.000Z")
        self.assertEqual(payload["duration_ms"], 1500)
        self.assertEqual(payload["execution_surface"], "codespaces")
        self.assertEqual(payload["execution_profile_or_none"], "agent-os-codespaces-v1")
        self.assertEqual(payload["environment_health_evidence_or_none"], "health-3333")
        self.assertEqual(payload["repository"], REPOSITORY)
        self.assertEqual(payload["exit_status_or_none"], 2)
        self.assertFalse(payload["github_writes_authorized"])
        self.assertFalse(payload["publication_authorized"])
        self.assertFalse(payload["merge_authorized"])

    def test_timeout_and_transport_error_retain_attempt_timestamps(self):
        for exc, reason in ((subprocess.TimeoutExpired("inert", 1), TransportReason.TRANSPORT_TIMEOUT),
                            (RuntimeError("inert"), TransportReason.TRANSPORT_ERROR)):
            with self.subTest(reason=reason):
                def fail(*a, **k):
                    raise exc
                result = run_codespace_transport(self.request(),
                          list_candidates=lambda: (self.candidate(),), run=fail)
                self.assertEqual(result.reason_codes, (reason,))
                self.assertIsNotNone(result.started_at_or_none)
                self.assertIsNotNone(result.ended_at_or_none)
                self.assertIsNone(result.exit_status_or_none)

    def test_missing_ambiguous_unqualified_and_changed_identity_never_run(self):
        cases = ((), (self.candidate("one"), self.candidate("two")),
                 (self.candidate(state="Shutdown"),), (self.candidate("different"),))
        for candidates in cases:
            with self.subTest(candidates=candidates):
                calls = []
                result = run_codespace_transport(self.request(codespace_name_or_none="qualified"),
                          list_candidates=lambda: candidates,
                          run=lambda *a, **k: calls.append(a))
                self.assertEqual(result.status, TransportStatus.FAILED)
                self.assertEqual(calls, [])
                self.assertIsNone(result.started_at_or_none)
                self.assertIsNone(result.ended_at_or_none)

    def test_profile_binding_changes_identity_without_rewriting_legacy_identity(self):
        legacy = self.request()
        material = [legacy.repository, legacy.issue_identity, legacy.admission_id,
                    list(legacy.argv), legacy.codespace_name_or_none, legacy.base_sha_or_none,
                    legacy.workdir_or_none, legacy.timeout_seconds]
        expected = hashlib.sha256(json.dumps(material, separators=(",", ":"),
                                             ensure_ascii=True).encode("ascii")).hexdigest()
        self.assertEqual(legacy.request_id, expected)
        first = self.request(execution_profile_or_none="profile-a", environment_health_evidence_or_none="health-a")
        second = self.request(execution_profile_or_none="profile-a", environment_health_evidence_or_none="health-b")
        self.assertNotEqual(first.request_id, legacy.request_id)
        self.assertNotEqual(first.request_id, second.request_id)

    def test_output_bounds_and_authority_survive_new_evidence_fields(self):
        result = run_codespace_transport(self.request(), list_candidates=lambda: (self.candidate(),),
                                        run=lambda *a, **k: (0, "o" * 6000, "e" * 6000))
        self.assertEqual(len(result.stdout_tail), 4096)
        self.assertEqual(len(result.stderr_tail), 4096)
        self.assertTrue(result.stdout_truncated)
        self.assertTrue(result.stderr_truncated)
        self.assertFalse(result.execution_authorized)
        self.assertFalse(result.merge_authorized)

    def test_production_dispatch_binds_runner_evidence_and_stale_gate_stays_closed(self):
        from agent_os_execution_service.executor_routing import ExecutorCapability
        from scripts.agent_os_execution_interface.codespace_implementation_dispatch import (
            DispatchStatus, dispatch_admitted_operation_to_codespace,
        )
        from scripts.agent_os_execution_interface.governed_runner_preference import (
            GovernedRunnerCandidate, GovernedRunnerKind,
        )
        capabilities = tuple(sorted((ExecutorCapability.CHECKOUT,
                        ExecutorCapability.PROCESS_EXECUTION, ExecutorCapability.TEST_EXECUTION),
                        key=lambda value: value.value))
        def runner(kind):
            return GovernedRunnerCandidate(kind=kind, available=True, current=True,
                    capabilities=capabilities, execution_surface_id=f"surface:{kind.value}",
                    environment_profile_id=f"profile:{kind.value}",
                    environment_health_evidence_id=f"health:{kind.value}",
                    workflow_runtime_identity=f"runtime:{kind.value}")
        seen = []
        arguments = dict(issue_identity="issue:3333", admission_id="admission:3333",
                    requested_operation="bounded-implementation", required_capabilities=capabilities,
                    codespaces_candidate=runner(GovernedRunnerKind.CODESPACES),
                    gce_candidate=runner(GovernedRunnerKind.GCE), argv=("git", "rev-parse", "HEAD"),
                    created_at="2026-10-13T01:00:00Z", expires_at="2026-10-13T02:00:00Z",
                    execution_service_request_fingerprint="request:3333",
                    operating_mode_decision_id="mode:3333", executable_lane_selection_id="lane:3333",
                    validation_command_plan_id_or_none="plan:3333", base_sha_or_none=BASE,
                    list_candidates=lambda: (self.candidate(),),
                    run=lambda *a, **k: (seen.append(a) or (0, BASE, "")))
        outcome = dispatch_admitted_operation_to_codespace(**arguments)
        self.assertEqual(outcome.status, DispatchStatus.DISPATCHED)
        result = outcome.transport_result_or_none
        self.assertEqual(result.execution_profile_or_none, "profile:codespaces")
        self.assertEqual(result.environment_health_evidence_or_none, "health:codespaces")
        self.assertEqual(result.argv, ("git", "rev-parse", "HEAD"))
        self.assertEqual(len(seen), 1)
        stale = dispatch_admitted_operation_to_codespace(**arguments, evidence_stale=True)
        self.assertEqual(stale.status, DispatchStatus.NOT_DISPATCHED)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main()
