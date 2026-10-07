"""Reconstructed #2826 controller acceptance; never native ChatGPT evidence.

Only test-local adapters and in-memory side effects are used. The existing
fixed remote-validation suite runs this fixture and the fixed regressions below.
No uploaded probe, caller argv, new profile, persistence, or transport is added.
"""
from __future__ import annotations

import json
import os
import platform
from contextlib import nullcontext
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.agent_os_execution_interface.continuation_driver import (
    ContinuationDecision, completion_continuation_payload,
    drive_governed_continuation,
)
from scripts.agent_os_execution_interface.finite_batch_admission import (
    evaluate_finite_batch_admission,
)
from scripts.agent_os_execution_interface.investigation_completion_admission import (
    evaluate_investigation_completion_admission,
)
from scripts.agent_os_execution_interface.operation_target_admission import (
    LifecycleOperation, TargetKind, evaluate_operation_target_admission,
)

ROOT = Path(__file__).resolve().parents[2]
REGRESSIONS = tuple("tests/agent_os_execution_interface/" + name for name in (
    "test_continuation_driver.py", "test_continuation_reachability.py",
    "test_finite_batch_admission.py", "test_issue_2523_investigation_completion.py",
    "test_mission_completion_admission.py", "test_2201_subordinate_write_continuation.py",
    "test_2203_through_pr_batch_continuation.py", "test_operation_target_admission.py",
))

# #3297: the fixed regression bundle takes about 45 s on an idle machine and
# previously had only 15 s of headroom under the 60 s subprocess ceiling.
# Keep a bounded failure ceiling, but allow >2x the measured baseline so normal
# shared-runner contention does not turn healthy main into a false red.
FIXED_REGRESSION_TIMEOUT_SECONDS = 120


@pytest.fixture(scope="session")
def acceptance_evidence(request):
    """Emit compact observed results at teardown into the runner's bounded tail."""
    evidence = {"issue": 2826, "provenance": "reconstructed", "cases": {},
                "python": platform.python_version(), "pytest": pytest.__version__}
    head = subprocess.run(("git", "rev-parse", "HEAD"), cwd=ROOT,
                          capture_output=True, text=True, check=False, timeout=10)
    evidence["checkout_sha"] = head.stdout.strip() if head.returncode == 0 else None
    yield evidence
    reporter = request.config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        capture = request.config.pluginmanager.getplugin("capturemanager")
        with capture.global_and_fixture_disabled() if capture else nullcontext():
            reporter.write_line("ISSUE_2826_ACCEPTANCE=" + json.dumps(evidence, separators=(",", ":")))


@pytest.fixture
def case_result(request, acceptance_evidence):
    """Missing pass receipt is explicitly unverified, including assertion failures."""
    name = request.node.name.removeprefix("test_")
    acceptance_evidence["cases"][name] = "unverified"
    yield
    if getattr(request.node, "_2826_passed", False):
        acceptance_evidence["cases"][name] = "pass"


def passed(request):
    request.node._2826_passed = True


class ReadBatch:
    """Finite test workload consumed by the production continuation driver."""
    def __init__(self, count=3):
        self.count = count
        self.cursor = 0
        self.processed = []
        self.deliveries = []
        self.payloads = []

    def observe(self):
        investigation = evaluate_investigation_completion_admission(
            repository="Blummer92/agent-os", issue_number=2826,
            material_branch_states=tuple(
                "resolved-supported" if i < self.cursor else "untouched"
                for i in range(self.count)),
            executable_next_action_available=self.cursor < self.count,
            subordinate_write_performed=False,
        )
        batch = evaluate_finite_batch_admission(
            requested_count=self.count, delivered_count=self.cursor,
            reconciled_candidate_count=self.cursor,
            population_exhausted=self.cursor == self.count, shared_blocker=False,
        )
        payload = completion_continuation_payload(
            terminal=investigation.completion_admissible and batch.completion_admissible,
            blocked=False, next_action=investigation.next_action,
            reason_codes=investigation.reason_codes + batch.reason_codes,
        )
        self.payloads.append(payload)
        return payload

    def dispatch(self, action):
        assert action == "continue-same-lineage-investigation"
        assert self.cursor not in self.processed
        self.processed.append(self.cursor)
        self.cursor += 1

    def deliver(self, *, guarded):
        if guarded and not self.observe()["terminal"]:
            return False
        self.deliveries.append(tuple(self.processed))
        return True


def decide(payload):
    """Consume the actual structured projection, without classifying prose."""
    assert payload["execution_authorized"] is False
    assert payload["github_writes_authorized"] is False
    assert payload["side_effects_performed"] is False
    return ContinuationDecision(
        payload["action"], terminal=payload["terminal"], blocked=payload["blocked"],
        stalled=payload["stalled"], reason_codes=tuple(payload["reason_codes"]),
    )


@pytest.mark.usefixtures("case_result")
def test_early_response_control(request):
    batch = ReadBatch()
    assert batch.deliver(guarded=False)
    assert batch.deliveries == [()]
    assert batch.cursor == 0 and batch.observe()["terminal"] is False
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_early_response_treatment(request):
    batch = ReadBatch()
    assert batch.deliver(guarded=True) is False
    result = drive_governed_continuation(batch, decide)
    assert result.status == "completed" and result.user_turns_required == 0
    assert batch.processed == [0, 1, 2] and len(result.transitions) == 3
    assert batch.deliver(guarded=True) and batch.deliveries == [(0, 1, 2)]
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_inner_ceiling_control(request):
    batch = ReadBatch()
    for _ in range(2):
        batch.dispatch(batch.observe()["action"])
    assert batch.cursor == 2 and batch.processed == [0, 1]
    assert batch.observe()["terminal"] is False and batch.deliveries == []
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_inner_ceiling_treatment(request):
    batch = ReadBatch()
    first = drive_governed_continuation(batch, decide, max_transitions=2)
    assert first.status == "recovery-stalled"
    assert first.reason_codes == ("finite-transition-bound-exhausted",)
    assert batch.cursor == 2 and batch.deliver(guarded=True) is False
    # Test controller owns this next batch; no user callback or rebuilt cursor.
    second = drive_governed_continuation(batch, decide)
    assert second.status == "completed" and len(second.transitions) == 1
    assert first.user_turns_required == second.user_turns_required == 0
    assert batch.processed == [0, 1, 2] and batch.deliver(guarded=True)
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_already_terminal_delivery(request):
    batch = ReadBatch()
    batch.cursor = 3
    batch.processed = [0, 1, 2]
    result = drive_governed_continuation(batch, decide)
    assert result.status == "completed" and result.transitions == ()
    assert batch.deliver(guarded=True) and batch.processed == [0, 1, 2]
    passed(request)


def operation_admission(*, zero_effect=True, current=True, authorized=True):
    return evaluate_operation_target_admission(
        repository="Blummer92/agent-os", target_number=2826,
        operation=LifecycleOperation.UPDATE_ISSUE, selected_target_kind=TargetKind.ISSUE,
        prior_effect_none_proven=zero_effect, current_target_reacquired=current,
        capable_alternative_available=authorized,
    )


@pytest.mark.parametrize("boundary", ("genuine-blocker", "authorization", "currentness"))
@pytest.mark.usefixtures("case_result")
def test_boundary_stops_dispatch(request, boundary):
    batch = ReadBatch()
    admission = operation_admission(current=boundary != "currentness",
                                    authorized=boundary != "authorization")
    payload = completion_continuation_payload(
        terminal=False, blocked=boundary == "genuine-blocker" or not admission.mutation_admissible,
        next_action=admission.next_action,
        reason_codes=("genuine-shared-blocker",) if boundary == "genuine-blocker" else admission.reason_codes,
    )
    result = drive_governed_continuation(batch, lambda _: decide(payload))
    assert result.status == "blocked" and batch.processed == []
    assert batch.deliveries == [] and batch.cursor == 0
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_repeated_no_progress_stop(request):
    batch = ReadBatch()
    attempts = []
    # Adapter reports repeated equivalent observation, rather than inventing
    # progress merely because dispatch returned. Existing driver consumes stall.
    batch.dispatch = lambda action: attempts.append((batch.cursor, action))
    def stalled(payload):
        decision = decide(payload)
        return ContinuationDecision(decision.action, stalled=bool(attempts))
    result = drive_governed_continuation(batch, stalled)
    assert result.status == "recovery-stalled" and len(attempts) == 1
    assert batch.cursor == 0 and batch.deliveries == []
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_hard_transition_cap(request):
    batch = ReadBatch(count=20)
    result = drive_governed_continuation(batch, decide)
    assert result.status == "recovery-stalled" and len(result.transitions) == 12
    assert batch.processed == list(range(12)) and batch.cursor == 12
    assert batch.deliver(guarded=True) is False
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_uncertain_mutation_receipt_reconciliation(request):
    # The synthetic effect persisted but its acknowledgement was lost.
    ledger = {"writes": 0, "receipt": None, "events": []}
    def mutate_with_lost_ack():
        ledger["writes"] += 1
        ledger["receipt"] = "effect:2826"
        ledger["events"].extend(("write", "lost-ack"))
        raise TimeoutError("acknowledgement lost after synthetic effect")
    with pytest.raises(TimeoutError):
        mutate_with_lost_ack()
    class ReceiptAdapter:
        def observe(self):
            return ledger.get("reconciled", False)
        def dispatch(self, action):
            assert action == "read-back-canonical-state-before-any-mutation"
            ledger["events"].append("receipt-read")
            assert ledger["receipt"] == "effect:2826"
            ledger["reconciled"] = True
    admission = operation_admission(zero_effect=False)
    def reconcile(done):
        return ContinuationDecision("", terminal=True) if done else ContinuationDecision(admission.next_action)
    assert admission.mutation_admissible is False
    result = drive_governed_continuation(ReceiptAdapter(), reconcile)
    assert result.status == "completed" and result.user_turns_required == 0
    assert ledger["events"] == ["write", "lost-ack", "receipt-read"]
    assert ledger["writes"] == 1 and ledger["reconciled"] is True
    # Parent work still continues after reconciliation, using the same driver.
    parent = ReadBatch()
    assert drive_governed_continuation(parent, decide).status == "completed"
    assert parent.processed == [0, 1, 2] and parent.deliver(guarded=True)
    passed(request)


@pytest.mark.usefixtures("case_result")
def test_fixed_current_main_regressions(request, tmp_path, acceptance_evidence):
    """Run canonical tests as tests, retaining collection failures and counts."""
    report = tmp_path / "regressions.xml"
    command = (sys.executable, "-m", "pytest", "-q", *REGRESSIONS, "--junitxml=" + str(report))
    start = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   timeout=FIXED_REGRESSION_TIMEOUT_SECONDS, check=False,
                                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired as exc:
        def text_tail(value, bound):
            text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
            return text[-bound:]
        acceptance_evidence["regressions"] = {
            "command": list(command), "exit": None, "timed_out": True,
            "seconds": round(time.monotonic() - start, 3),
            "timeout_seconds": FIXED_REGRESSION_TIMEOUT_SECONDS,
            "counts_complete": False, "modules": len(REGRESSIONS),
            "stdout_tail": text_tail(exc.stdout, 600),
            "stderr_tail": text_tail(exc.stderr, 300),
        }
        pytest.fail(
            "Fixed canonical regressions exceeded the bounded "
            f"{FIXED_REGRESSION_TIMEOUT_SECONDS}-second ceiling"
        )
    suites = ET.parse(report).getroot().findall("testsuite")
    counts = {name: sum(int(s.get(name, "0")) for s in suites)
              for name in ("tests", "failures", "errors", "skipped")}
    acceptance_evidence["regressions"] = {
        "exit": completed.returncode, "seconds": round(time.monotonic() - start, 3),
        **counts, "modules": len(REGRESSIONS),
        "command": list(command), "stdout_tail": completed.stdout[-600:],
        "stderr_tail": completed.stderr[-300:],
    }
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-12000:]
    assert counts["tests"] > 0 and counts["errors"] == counts["failures"] == counts["skipped"] == 0
    observed = {case.get("classname", "").split(".")[-1]
                for suite in suites for case in suite.findall("testcase")}
    assert {Path(path).stem for path in REGRESSIONS} <= observed
    passed(request)
