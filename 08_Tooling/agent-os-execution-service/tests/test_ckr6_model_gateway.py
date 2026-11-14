"""T13: mandatory CKR6 admission at an application-owned model-execution boundary.

Every test drives the REAL repository R07 owners (``parse_envelope``,
``classify_envelope``, ``select_ckr6_result_comment``,
``ckr6_result_admits_boundary``). Only GitHub (a mutable in-memory store with
an independent GET) and the model provider (a counting fake) are faked. No
credential, network egress, or paid inference is used anywhere.
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from agent_os_execution_service import ckr6_github_bridge as bridge
from agent_os_execution_service.ckr6_model_gateway import (
    GatewayConfig,
    InvocationRequest,
    ModelGateway,
    StopBoundary,
)

REPO = "Blummer92/agent-os"
ISSUE = 4001
T0 = datetime(2026, 11, 12, 12, 0, 0, tzinfo=timezone.utc)
HINTS = {
    "library_hints": ("pydantic",),
    "language_hints": ("python",),
    "capability_keywords": ("validators",),
}


class FakeClock:
    def __init__(self) -> None:
        self.t = T0

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def sufficient_result(envelope, request_id, **changes):
    value = {
        "operation": envelope.operation,
        "repository": envelope.repository,
        "issue_number": envelope.issue_number,
        "status": "sufficient",
        "reason_codes": ["lesson-retrieval-required"],
        "selected_lesson_ids": ["LL-87"],
        "selected_lessons": [
            {"lesson_id": "LL-87", "source_revision": "r1", "selection_reason_codes": ["relevant"]}
        ],
        "materiality_source": "plan-retrieval-required",
        "canonical_github_refs": [],
        "rejected_candidate_provenance": [],
        "handoff_projection": {
            "known_facts": ["coding-knowledge-sufficiency:sufficient"],
            "prior_decisions": [], "allowed_inspect_first": [], "stop_conditions": [],
        },
        "substantial_hypothesis_admissible": True,
        "execution_authorized": False, "github_writes_authorized": False,
        "merge_authorized": False, "closure_authorized": False,
        "side_effects_performed": False,
        "notion_read_performed": True, "retrieval_required": True,
        "recommended_escalation": "filtered-data-source-query",
    }
    if envelope.operation == "failed-repair":
        value.pop("substantial_hypothesis_admissible")
        value.update(mutation_admissible=True, retry_reentry_outcome="consumed",
                     attempt_id=envelope.attempt_id)
    value.update(changes)
    return value


def not_needed_result(envelope, request_id, **changes):
    value = {
        "operation": envelope.operation, "repository": envelope.repository,
        "issue_number": envelope.issue_number, "status": "not-needed",
        "reason_codes": ["knowledge-not-needed"], "selected_lesson_ids": [],
        "canonical_github_refs": [], "substantial_hypothesis_admissible": True,
        "execution_authorized": False, "github_writes_authorized": False,
        "merge_authorized": False, "closure_authorized": False,
        "side_effects_performed": False, "retrieval_required": False,
        "recommended_escalation": "none",
    }
    if envelope.operation == "failed-repair":
        value.pop("substantial_hypothesis_admissible")
        value.update(mutation_admissible=True, retry_reentry_outcome="not-material",
                     attempt_id=envelope.attempt_id)
    value.update(changes)
    return value


class FakeGitHub:
    """Mutable issue-comment store with a delayed ``github-actions[bot]`` producer."""

    def __init__(self, clock: FakeClock, *, producer=None, request_author="Blummer92",
                 result_delay=20):
        self.clock = clock
        self.producer = producer
        self.request_author = request_author
        self.result_delay = result_delay
        self.records: list[dict] = []
        self._next = 5000
        self.posts = 0
        self.gets = 0
        self.lists = 0
        self.lock = threading.Lock()
        self.tamper_after_post = None   # callable(record) mutating the stored request
        self.list_hook = None           # callable(list_count) invoked at the start of each list
        self.post_error = None
        self.list_error = None
        self.no_time_filter = False     # a transport that does not hide future-dated comments

    def _record(self, body, *, login, uid, utype, at, repo=REPO, issue=ISSUE):
        self._next += 1
        rec = {
            "id": self._next, "body": body,
            "user": {"login": login, "id": uid, "type": utype},
            "created_at": iso(at), "updated_at": iso(at),
            "issue_url": f"https://api.github.com/repos/{repo}/issues/{issue}",
            "html_url": f"https://github.com/{repo}/issues/{issue}#issuecomment-{self._next}",
        }
        self.records.append(rec)
        return rec

    def add_result(self, body, *, at=None, login="github-actions[bot]", uid=41898282,
                   utype="Bot", repo=REPO, issue=ISSUE):
        return self._record(body, login=login, uid=uid, utype=utype,
                            at=at or self.clock.now(), repo=repo, issue=issue)

    # -- transport protocol used by the gateway ---------------------------------
    def post_issue_comment(self, repository, issue_number, body):
        if self.post_error is not None:
            self.posts += 1
            raise self.post_error
        with self.lock:
            self.posts += 1
            rec = self._record(body, login=self.request_author, uid=1, utype="User",
                               at=self.clock.now(), repo=repository, issue=issue_number)
        if self.tamper_after_post is not None:
            self.tamper_after_post(rec)
        if self.producer is not None and body.startswith(bridge.COMMAND_PREFIX):
            envelope = bridge.parse_envelope(bridge._command_payload(body[len(bridge.COMMAND_PREFIX):]))
            result = self.producer(envelope, rec["id"])
            if result is not None:
                self.add_result(
                    bridge.serialize_ckr6_result_comment(result, request_comment_id=rec["id"]),
                    at=self.clock.now() + timedelta(seconds=self.result_delay),
                    repo=repository, issue=issue_number)
        return rec["id"]

    def get_issue_comment(self, repository, comment_id):
        self.gets += 1
        for rec in self.records:
            if rec["id"] == comment_id:
                return copy.deepcopy(rec)
        raise LookupError("comment not found")

    def list_issue_comments(self, repository, issue_number):
        self.lists += 1
        if self.list_error is not None:
            raise self.list_error
        if self.list_hook is not None:
            self.list_hook(self.lists)
        now = self.clock.now()
        return [copy.deepcopy(r) for r in self.records
                if self.no_time_filter or datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) <= now]


class CountingBackend:
    """Fake provider reachable only through the gateway in the in-process tests."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        return "model:" + prompt

    def stream(self, prompt: str):
        self.calls.append(prompt)
        for token in ("a", "b", "c"):
            yield token


def build(producer=sufficient_result, *, backend=None, clock=None, **gateway_kwargs):
    clock = clock or FakeClock()
    store = FakeGitHub(clock, producer=producer)
    backend = backend or CountingBackend()
    config = GatewayConfig(allowed_repositories=(REPO,), request_author_login="Blummer92")
    gateway_kwargs.setdefault("verify_failed_attempt", lambda request: True)
    gateway = ModelGateway(store, backend, config=config, clock=clock.now,
                           sleep=clock.sleep, **gateway_kwargs)
    return gateway, store, backend, clock


def request(**changes):
    base = dict(invocation_id="inv-1", operation="issue-start", repository=REPO,
                issue_number=ISSUE, task_reference="integrate pydantic validators",
                prompt="do the work", **HINTS)
    base.update(changes)
    return InvocationRequest(**base)


def events(outcome):
    return [e["event"] for e in outcome.trace]


# --------------------------------------------------------------------------- P01
def test_no_admission_means_zero_backend_calls():
    gateway, store, backend, _ = build(producer=lambda env, rid: None)  # producer never answers
    out = gateway.invoke(request())
    assert out.admitted is False
    assert out.reason == "bounded-wait-expired"
    assert backend.calls == []
    assert gateway.stats.backend_calls == 0
    assert gateway.stats.receipts_issued == 0
    assert "model-call-started" not in events(out)


# --------------------------------------------------------------------------- P02
def test_sufficient_result_admits_exactly_one_backend_call_in_trace_order():
    gateway, store, backend, _ = build()
    out = gateway.invoke(request())
    assert out.admitted is True and out.output == "model:do the work"
    assert backend.calls == ["do the work"]
    assert gateway.stats.backend_calls == 1
    assert (gateway.stats.receipts_issued, gateway.stats.receipts_consumed) == (1, 1)
    order = events(out)
    assert (order.index("request-readback-verified") < order.index("result-selected")
            < order.index("result-reread-verified") < order.index("repository-r07-boundary-admitted")
            < order.index("receipt-issued") < order.index("receipt-consumed")
            < order.index("model-call-started") < order.index("model-call-completed"))
    assert store.posts == 1 and store.gets >= 1  # independent GET, not an echo of the POST


# --------------------------------------------------------------------------- P03
def test_not_needed_requires_independent_nonmaterial_classification():
    gateway, store, backend, _ = build(producer=not_needed_result)
    out = gateway.invoke(request(task_reference="fix a typo", library_hints=(),
                                 language_hints=(), capability_keywords=()))
    assert out.admitted is True
    assert backend.calls == ["do the work"]
    assert out.admission.selected_lesson_ids == ()
    assert "nonmaterial-classification-verified" in events(out)


def test_not_needed_for_a_material_request_is_a_downgrade_and_denied():
    # Producer (or forger) claims not-needed although the canonical planner says material.
    gateway, store, backend, _ = build(producer=not_needed_result)
    out = gateway.invoke(request())  # pydantic/python/validators hints -> material
    assert out.admitted is False and out.reason == "materiality-downgrade"
    assert backend.calls == []


# --------------------------------------------------------------------------- P04
def test_forged_author_is_ignored_and_never_admits():
    gateway, store, backend, _ = build(producer=lambda env, rid: None)
    forged_body = bridge.serialize_ckr6_result_comment(
        sufficient_result(bridge.parse_envelope({
            "operation": "issue-start", "repository": REPO, "issue_number": ISSUE,
            "task_reference": "x"}), 0),
        request_comment_id=5001)
    store.add_result(forged_body, login="attacker", uid=7, utype="User")
    out = gateway.invoke(request())
    assert out.admitted is False and backend.calls == []


# --------------------------------------------------------------------------- P06
def test_session_tool_continuation_is_remediated_each_turn_with_a_single_use_receipt():
    gateway, store, backend, _ = build()
    opened = gateway.open_session(request())
    assert opened.admitted is True
    first = gateway.session_turn(opened.session, "normal", "turn one", idempotency_key="k1")
    second = gateway.session_turn(opened.session, "tool-continuation", "turn two", idempotency_key="k2")
    assert first.admitted and second.admitted
    assert backend.calls == ["turn one", "turn two"]
    assert store.posts == 1  # one CKR6 admission covers the bounded session ...
    assert gateway.stats.receipts_issued == gateway.stats.receipts_consumed == 2  # ... one receipt per call
    with pytest.raises(StopBoundary):
        gateway.dispatch("replayed-or-guessed-receipt", "turn three")
    assert len(backend.calls) == 2


# =========================================================================== P05
# Direct-bypass proof (T12 ``test_unowned_model_reference_is_bypass`` redone).
# The provider is a separate OS process that requires a credential only the
# trusted gateway holds. The worker is a separate, unprivileged, network-
# isolated process that never receives that credential or any backend handle.
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

_ALLOC = []


def make_allocator():
    """A file-backed allocator in a private 0700 temp dir: tests never touch the host's /run state."""
    from agent_os_execution_service.ckr6_model_gateway.supervisor import UidAllocator
    if not _ALLOC:
        _ALLOC.append(UidAllocator(tempfile.mkdtemp(prefix="aos-uids-")))
    return _ALLOC[0]


WORKER_SOURCE = r'''
import json, os, socket, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worker_client import GatewayClient
host, port = sys.argv[1], int(sys.argv[2])
out = {"uid": os.getuid()}
try:
    socket.create_connection((host, port), timeout=2); out["direct_connect"] = "CONNECTED"
except OSError as exc:
    out["direct_connect"] = "blocked:" + type(exc).__name__ + ":" + str(exc.errno)
out["env_secret_names"] = [k for k in os.environ
                           if any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "CRED", "BEARER", "AUTH"))]
for name in ("environ", "mem"):
    try:
        with open(f"/proc/{os.getppid()}/{name}", "rb") as fh:
            fh.read(1)
        out["parent_" + name] = "READ"
    except OSError as exc:
        out["parent_" + name] = "blocked:" + type(exc).__name__
try:
    os.setuid(0); out["regain_root"] = "OK"
except OSError as exc:
    out["regain_root"] = "blocked:" + type(exc).__name__
client = GatewayClient(int(os.environ["AOS_GATEWAY_FD"]))
out["forged_admitted_flag"] = client.raw({"method": "turn", "session": "guess", "kind": "normal",
                                          "prompt": "x", "key": "k1", "admitted": True})
out["forged_receipt"] = client.raw({"method": "dispatch", "receipt": "guess", "prompt": "x"})
out["turn_without_session"] = client.raw({"method": "turn", "session": "guess", "kind": "normal",
                                          "prompt": "x", "key": "k2"})
opened = client.open()
out["open"] = {"admitted": opened["admitted"], "reason": opened.get("reason")}
if opened["admitted"]:
    turn = client.turn(opened["session"], "normal", "hello from worker", "k3")
    out["turn"] = {"admitted": turn["admitted"], "output": turn.get("output")}
out["fds"] = sorted(int(f) for f in os.listdir("/proc/self/fd") if f.isdigit())
print(json.dumps(out))
'''


@pytest.fixture()
def provider_process():
    from agent_os_execution_service.ckr6_model_gateway.fake_provider import FakeProviderProcess
    provider = FakeProviderProcess.start()
    try:
        yield provider
    finally:
        provider.stop()


def run_worker(gateway, binding, provider, *, source=None):
    from agent_os_execution_service.ckr6_model_gateway import worker_client
    from agent_os_execution_service.ckr6_model_gateway.rpc import GatewayRpcServer
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        IsolationUnavailable, spawn_isolated_worker)
    workdir = Path(tempfile.mkdtemp(prefix="aos-worker-"))
    os.chmod(workdir, 0o755)
    (workdir / "worker.py").write_text(source or WORKER_SOURCE)
    shutil.copy(worker_client.__file__, workdir / "worker_client.py")
    for p in workdir.iterdir():
        os.chmod(p, 0o644)
    parent_sock, child_sock = socket.socketpair()
    server = GatewayRpcServer(gateway, binding)
    thread = threading.Thread(target=server.serve, args=(parent_sock,), daemon=True)
    thread.start()
    try:
        try:
            proc = spawn_isolated_worker(
                [sys.executable, "-I", str(workdir / "worker.py"), provider.host, str(provider.port)],
                pass_fds=(child_sock.fileno(),),
                env={"AOS_GATEWAY_FD": str(child_sock.fileno())}, cwd=str(workdir),
                allocator=make_allocator())
        except IsolationUnavailable:
            return None  # fail-closed: no worker was started at all
        stdout, stderr = proc.communicate(timeout=60)
        assert proc.returncode == 0, stderr.decode()
        return json.loads(stdout.decode().strip().splitlines()[-1])
    finally:
        child_sock.close(); parent_sock.close(); thread.join(timeout=5)
        shutil.rmtree(workdir, ignore_errors=True)


def test_direct_provider_access_is_impossible_for_an_isolated_worker(provider_process):
    from agent_os_execution_service.ckr6_model_gateway.provider import HttpProviderBackend
    backend = HttpProviderBackend(provider_process.host, provider_process.port, provider_process.credential)
    gateway, store, _, _ = build(producer=lambda env, rid: None, backend=backend)
    binding = request(prompt="")
    seen = run_worker(gateway, binding, provider_process)
    stats = provider_process.stats()
    if seen is None:
        # Unprivileged CI host: the supervisor must refuse to start a worker rather than
        # start an un-isolated one. That is the only acceptable alternative outcome.
        assert stats["authenticated_calls"] == 0
        return
    assert seen["uid"] != 0
    assert seen["direct_connect"].startswith("blocked:")
    assert seen["env_secret_names"] == []
    assert seen["parent_environ"].startswith("blocked:") and seen["parent_mem"].startswith("blocked:")
    assert seen["regain_root"].startswith("blocked:")
    assert seen["forged_admitted_flag"]["admitted"] is False
    assert seen["forged_receipt"]["admitted"] is False
    assert seen["turn_without_session"]["admitted"] is False
    assert seen["open"]["admitted"] is False  # CKR6 result never arrived
    assert "turn" not in seen
    assert stats["authenticated_calls"] == 0 and stats["rejected_calls"] == 0
    assert len([f for f in seen["fds"] if f > 2]) <= 2  # only the gateway socket (+ the fd listing itself)


def test_admitted_scenario_reaches_the_provider_only_through_the_gateway(provider_process):
    from agent_os_execution_service.ckr6_model_gateway.provider import HttpProviderBackend
    backend = HttpProviderBackend(provider_process.host, provider_process.port, provider_process.credential)
    gateway, store, _, _ = build(producer=sufficient_result, backend=backend)
    seen = run_worker(gateway, request(prompt=""), provider_process)
    stats = provider_process.stats()
    if seen is None:
        assert stats["authenticated_calls"] == 0
        return
    assert seen["open"]["admitted"] is True
    assert seen["turn"]["admitted"] is True and seen["turn"]["output"].startswith("provider-reply:")
    assert stats["authenticated_calls"] == 1 and stats["rejected_calls"] == 0
    # the provider's OWN log is the ordering/counter authority, not the gateway's
    assert stats["events"][0]["prompt_sha256"] is not None


# ---------------------------------------------------------------------------
# Provider-side controls: the credential and the network are INDEPENDENT layers.
def http_post(provider, path, prompt, token=None):
    import http.client
    conn = http.client.HTTPConnection(provider.host, provider.port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    conn.request("POST", path, body=json.dumps({"prompt": prompt}), headers=headers)
    return conn.getresponse().status


def test_control_provider_is_live_and_the_credential_alone_is_the_capability(provider_process):
    # Control for the isolation tests: the provider IS reachable from the host namespace, so a worker's
    # failure to connect is attributable to isolation, and a reachable-but-credentialless caller is refused.
    assert http_post(provider_process, "/v1/complete", "p", token=None) == 401
    assert http_post(provider_process, "/v1/complete", "p", token="guessed") == 401
    stats = provider_process.stats()
    assert (stats["authenticated_calls"], stats["rejected_calls"]) == (0, 2)
    assert http_post(provider_process, "/v1/complete", "p", token=provider_process.credential) == 200
    assert provider_process.stats()["authenticated_calls"] == 1


FULL_WORKER_SOURCE = r'''
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worker_client import GatewayClient
c = GatewayClient(int(os.environ["AOS_GATEWAY_FD"]))
out = {}
opened = c.open(); out["open"] = opened["admitted"]
s = opened["session"]
out["normal"] = c.turn(s, "normal", "turn-normal", "n1")["admitted"]
out["tool"] = c.turn(s, "tool-continuation", "turn-tool", "n2")["admitted"]
out["stream"] = [f.get("chunk") for f in c.stream(s, "turn-stream", "n3") if f.get("chunk")]
out["retry_in_session"] = c.turn(s, "retry", "x", "n4")["reason"]
out["resume_in_session"] = c.turn(s, "resume", "x", "n5")["reason"]
out["subagent_in_root"] = c.turn(s, "subagent", "x", "n6")["reason"]
child = c.child(s); out["child"] = child["admitted"]
out["subagent"] = c.turn(child["session"], "subagent", "turn-subagent", "c1")["admitted"]
out["normal_in_child"] = c.turn(child["session"], "normal", "x", "c2")["reason"]
out["foreign_session"] = c.turn("not-mine", "normal", "x", "c3")["reason"]
print(json.dumps(out))
'''


def test_continuation_stream_and_subagent_reach_the_provider_only_through_receipted_gateway_calls(provider_process):
    from agent_os_execution_service.ckr6_model_gateway.provider import HttpProviderBackend
    backend = HttpProviderBackend(provider_process.host, provider_process.port, provider_process.credential)
    gateway, store, _, _ = build(producer=sufficient_result, backend=backend)
    seen = run_worker(gateway, request(prompt=""), provider_process, source=FULL_WORKER_SOURCE)
    stats = provider_process.stats()
    if seen is None:
        assert stats["authenticated_calls"] == 0
        return
    assert seen["open"] and seen["normal"] and seen["tool"] and seen["subagent"]
    assert seen["stream"] == ["alpha", "beta", "gamma"]
    assert seen["retry_in_session"] == "retry-requires-new-admission"
    assert seen["resume_in_session"] == "resume-requires-new-admission"
    assert seen["subagent_in_root"] == "subagent-requires-child-session"
    assert seen["normal_in_child"] == "child-session-turns-must-be-subagent"
    assert seen["foreign_session"] == "unknown-session"
    # normal + tool + stream + subagent = 4 provider calls, each with its own receipt; one CKR6 admission.
    assert stats["authenticated_calls"] == 4 and stats["rejected_calls"] == 0
    assert gateway.stats.backend_calls == 4
    assert gateway.stats.receipts_issued == gateway.stats.receipts_consumed == 4
    assert store.posts == 1


# ----------------------------------------------------------------- adversarial: ingress
def test_request_tampered_in_the_store_is_caught_by_the_independent_get():
    gateway, store, backend, _ = build()
    store.tamper_after_post = lambda rec: rec.update(body=rec["body"].replace(ISSUE.__str__(), "9999"))
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "request-readback-mismatch:body")
    assert backend.calls == [] and store.gets == 1


def test_request_posted_under_a_different_author_is_refused():
    gateway, store, backend, _ = build()
    store.request_author = "mallory"
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "request-readback-mismatch:author")
    assert backend.calls == []


def test_post_failure_is_terminal_and_never_retried():
    gateway, store, backend, _ = build()
    store.post_error = OSError("boom")
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "ingress-post-failed")
    assert store.posts == 1 and backend.calls == []


def test_result_transport_error_is_a_stop():
    gateway, store, backend, _ = build()
    store.list_error = OSError("boom")
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-transport-error") and backend.calls == []


def test_result_after_the_absolute_deadline_never_admits():
    gateway, store, backend, _ = build()
    store.result_delay = 400
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "bounded-wait-expired") and backend.calls == []


def test_cancellation_while_waiting_stops_before_any_backend_call():
    cancel = threading.Event()
    clock = FakeClock()
    orig = clock.sleep
    clock.sleep = lambda s: (cancel.set(), orig(s))[1]
    gateway, store, backend, _ = build(producer=lambda e, r: None, clock=clock)
    out = gateway.invoke(request(), cancel=cancel)
    assert (out.admitted, out.reason) == (False, "cancelled-while-waiting") and backend.calls == []


def test_cancellation_before_admission_posts_nothing():
    cancel = threading.Event(); cancel.set()
    gateway, store, backend, _ = build()
    out = gateway.invoke(request(), cancel=cancel)
    assert (out.admitted, out.reason) == (False, "cancelled-before-admission")
    assert store.posts == 0 and backend.calls == []


def test_conflicting_trusted_results_are_ambiguous():
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    env = bridge.parse_envelope(request().envelope_payload())
    rid = 5001  # the id the store will assign to the request comment
    store.add_result(bridge.serialize_ckr6_result_comment(sufficient_result(env, rid), request_comment_id=rid))
    store.add_result(bridge.serialize_ckr6_result_comment(
        sufficient_result(env, rid, selected_lesson_ids=["LL-9"],
                          selected_lessons=[{"lesson_id": "LL-9", "source_revision": "r", "selection_reason_codes": []}]),
        request_comment_id=rid))
    # records predate the request comment id (5001) -> both are untrusted -> not returned, never admitted
    out = gateway.invoke(request())
    assert out.admitted is False and backend.calls == []


def test_two_distinct_trusted_results_for_one_request_are_ambiguous():
    def producer(env, rid):
        store.add_result(bridge.serialize_ckr6_result_comment(
            sufficient_result(env, rid, selected_lesson_ids=["LL-9"], selected_lessons=[
                {"lesson_id": "LL-9", "source_revision": "r", "selection_reason_codes": []}]),
            request_comment_id=rid), at=clock.now() + timedelta(seconds=10))
        return sufficient_result(env, rid)
    clock = FakeClock()
    gateway, store, backend, _ = build(producer=producer, clock=clock)
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-ambiguous") and backend.calls == []


def test_result_for_another_issue_cannot_be_replayed_across_issues():
    def producer(env, rid):
        store.add_result(bridge.serialize_ckr6_result_comment(sufficient_result(env, rid), request_comment_id=rid),
                         issue=ISSUE + 1, at=clock.now() + timedelta(seconds=5))
        return None
    clock = FakeClock()
    gateway, store, backend, _ = build(producer=producer, clock=clock)
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "bounded-wait-expired") and backend.calls == []


def test_result_edited_after_selection_fails_the_independent_reread():
    gateway, store, backend, _ = build()

    def hook(n):
        if n == 3:  # poll 1 sees nothing, poll 2 selects, list 3 is the independent reread; a GitHub edit bumps updated_at
            for rec in store.records:
                if rec["body"].startswith(bridge.CKR6_RESULT_MARKER):
                    rec["updated_at"] = iso(T0 + timedelta(minutes=5))
    store.list_hook = hook
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-reread-mismatch") and backend.calls == []


def test_a_different_valid_result_appearing_at_reread_time_is_refused():
    gateway, store, backend, _ = build()

    def hook(n):
        if n == 3:  # swap in a DIFFERENT but individually valid trusted result (same ids/timestamps)
            for rec in store.records:
                if rec["body"].startswith(bridge.CKR6_RESULT_MARKER):
                    env = bridge.parse_envelope(request().envelope_payload())
                    swapped = sufficient_result(env, 0, selected_lesson_ids=["LL-99"], selected_lessons=[
                        {"lesson_id": "LL-99", "source_revision": "r", "selection_reason_codes": []}])
                    request_id = next(r["id"] for r in store.records if r["body"].startswith(bridge.COMMAND_PREFIX))
                    rec["body"] = bridge.serialize_ckr6_result_comment(swapped, request_comment_id=request_id)
    store.list_hook = hook
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-reread-mismatch") and backend.calls == []


def test_result_deleted_after_selection_fails_the_independent_reread():
    gateway, store, backend, _ = build()
    store.list_hook = lambda n: store.records.__setitem__(
        slice(None), [r for r in store.records if not r["body"].startswith(bridge.CKR6_RESULT_MARKER)]) if n == 3 else None
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-reread-mismatch") and backend.calls == []


@pytest.mark.parametrize("changes,reason", [
    ({"execution_authorized": True}, "result-rejected"),
    ({"selected_lesson_ids": []}, "repository-r07-boundary-not-admitted"),
    ({"substantial_hypothesis_admissible": False}, "result-rejected"),
    ({"status": "insufficient", "substantial_hypothesis_admissible": False}, "repository-r07-boundary-not-admitted"),
    ({"status": "manual-review", "substantial_hypothesis_admissible": False}, "repository-r07-boundary-not-admitted"),
    ({"selected_lessons": [{"lesson_id": "LL-OTHER", "source_revision": "r", "selection_reason_codes": []}]},
     "selection-incoherent"),
])
def test_forged_or_blocked_results_never_admit(changes, reason):
    gateway, store, backend, _ = build(producer=lambda e, r: sufficient_result(e, r, **changes))
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, reason) and backend.calls == []
    assert gateway.stats.receipts_issued == 0


def test_sufficient_for_a_request_the_planner_calls_nonmaterial_is_refused():
    gateway, store, backend, _ = build()  # producer says sufficient
    out = gateway.invoke(request(task_reference="fix a typo", library_hints=(), language_hints=(),
                                 capability_keywords=()))
    assert (out.admitted, out.reason) == (False, "sufficient-with-nonmaterial-request") and backend.calls == []


def test_caller_cannot_assert_materiality_or_admission():
    with pytest.raises(TypeError):
        InvocationRequest(invocation_id="x", operation="issue-start", repository=REPO, issue_number=1,
                          task_reference="t", specialized_knowledge_required=False)
    with pytest.raises(TypeError):
        InvocationRequest(invocation_id="x", operation="issue-start", repository=REPO, issue_number=1,
                          task_reference="t", admitted=True)
    # and the posted envelope never carries the flag, so the producer cannot be steered by it
    assert "specialized_knowledge_required" not in request().envelope_payload()


def test_unavailable_safe_fallback_is_not_admitted_without_independent_verification():
    fallback = lambda e, r: sufficient_result(e, r, status="unavailable-safe-fallback", selected_lesson_ids=[],
                                              selected_lessons=[], notion_read_performed=False)
    gateway, store, backend, _ = build(producer=fallback)
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "canonical-unavailability-not-verified") and backend.calls == []
    gateway, store, backend, _ = build(producer=fallback, verify_canonical_unavailability=lambda req, res: True)
    assert gateway.invoke(request()).admitted is True and len(backend.calls) == 1
    gateway, store, backend, _ = build(producer=fallback, verify_canonical_unavailability=lambda req, res: True)
    out = gateway.invoke(request(task_reference="fix a typo", library_hints=(), language_hints=(), capability_keywords=()))
    assert (out.admitted, out.reason) == (False, "nonmaterial-fallback") and backend.calls == []


def test_repository_outside_the_allow_list_is_refused_before_any_ingress():
    gateway, store, backend, _ = build()
    out = gateway.invoke(request(repository="Other/repo"))
    assert (out.admitted, out.reason) == (False, "repository-not-allowed") and store.posts == 0


# ------------------------------------------------------------- failed-repair / attempts
def repair(**changes):
    base = dict(invocation_id="rep-1", operation="failed-repair", attempt_id="attempt-2",
                failed_hypothesis="hypothesis A failed", result_summary="CI red", **HINTS)
    base.update(changes)
    return request(**base)


def test_failed_repair_admits_only_for_the_exact_recorded_attempt():
    gateway, store, backend, _ = build()
    assert gateway.invoke(repair()).admitted is True and len(backend.calls) == 1


def test_failed_repair_without_a_verified_attempt_record_is_refused():
    gateway, store, backend, _ = build(verify_failed_attempt=lambda r: False)
    out = gateway.invoke(repair())
    assert (out.admitted, out.reason) == (False, "failed-attempt-record-not-verified")
    assert store.posts == 0 and backend.calls == []
    out = gateway.invoke(repair(invocation_id="rep-2", attempt_id=None))
    assert (out.admitted, out.reason) == (False, "missing-recorded-failed-attempt")


def test_cross_attempt_result_cannot_admit_a_later_attempt():
    gateway, store, backend, _ = build(producer=lambda e, r: sufficient_result(e, r, attempt_id="attempt-1"))
    out = gateway.invoke(repair())
    assert (out.admitted, out.reason) == (False, "result-rejected") and backend.calls == []


def test_attempt_superseded_between_admission_and_dispatch_is_stale():
    live = {"ok": True}
    gateway, store, backend, _ = build(verify_failed_attempt=lambda r: live["ok"])
    real_issue = gateway._issue_receipt

    def issue_then_supersede(*a, **k):
        rid = real_issue(*a, **k)
        live["ok"] = False  # another attempt is recorded after admission, before the call
        return rid
    gateway._issue_receipt = issue_then_supersede
    out = gateway.invoke(repair())
    assert (out.admitted, out.reason) == (False, "stale-failed-attempt") and backend.calls == []


def test_stale_head_hook_blocks_dispatch_for_issue_start_too():
    gateway, store, backend, _ = build(verify_binding_current=lambda r: False)
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "stale-binding") and backend.calls == []


def test_failed_repair_is_always_material_so_not_material_results_are_downgrades():
    # Canonical owner (plan_lesson_preflight) FORCES material-use evaluation for failed-PR repair, so no
    # repair request can be independently proven nonmaterial: a not-needed/not-material result never admits.
    for hints in (HINTS, {}):
        gateway, store, backend, _ = build(producer=not_needed_result)
        out = gateway.invoke(repair(task_reference="fix a typo", **({k: () for k in HINTS} if not hints else {})))
        assert (out.admitted, out.reason) == (False, "materiality-downgrade") and backend.calls == []


# ---------------------------------------------------- idempotency / receipts / replay
def test_duplicate_invocation_replays_the_cached_outcome_without_a_second_call():
    gateway, store, backend, _ = build()
    first = gateway.invoke(request())
    again = gateway.invoke(request())
    assert again.replayed is True and again.output == first.output
    assert store.posts == 1 and len(backend.calls) == 1
    clash = gateway.invoke(request(prompt="a different prompt"))
    assert (clash.admitted, clash.reason) == (False, "invocation-id-reuse-mismatch")
    assert len(backend.calls) == 1


def test_a_denied_invocation_id_is_not_retried_by_resubmission():
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    gateway.invoke(request())
    posts = store.posts
    again = gateway.invoke(request())
    assert again.replayed is True and again.admitted is False and store.posts == posts


def test_concurrent_duplicates_produce_exactly_one_post_and_one_backend_call():
    gateway, store, backend, _ = build()
    results = []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        results.append(gateway.invoke(request()))
    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert store.posts == 1 and len(backend.calls) == 1
    assert sum(1 for r in results if r.admitted and not r.replayed) == 1


def test_consumed_receipt_replay_and_expired_receipt_and_wrong_prompt_are_refused():
    gateway, store, backend, clock = build()
    captured = []
    real_issue = gateway._issue_receipt
    gateway._issue_receipt = lambda *a, **k: captured.append(real_issue(*a, **k)) or captured[-1]
    assert gateway.invoke(request()).admitted
    with pytest.raises(StopBoundary, match="receipt-unknown-or-used"):
        gateway.dispatch(captured[0], "do the work")  # replay of a consumed receipt
    assert len(backend.calls) == 1
    # a fresh receipt that expires before use
    trace = gateway._trace()
    proof, _ = gateway._admitter.admit(request(invocation_id="inv-9"), trace)
    rid = real_issue(trace, request(invocation_id="inv-9"), proof, kind="normal",
                     binding_sha256=__import__("hashlib").sha256(b"p").hexdigest(), session_id=None)
    clock.sleep(61)
    with pytest.raises(StopBoundary, match="receipt-expired"):
        gateway.dispatch(rid, "p")
    # a fresh receipt bound to prompt "p" cannot be spent on another prompt
    rid2 = real_issue(trace, request(invocation_id="inv-9"), proof, kind="normal",
                      binding_sha256=__import__("hashlib").sha256(b"p").hexdigest(), session_id=None)
    with pytest.raises(StopBoundary, match="receipt-binding-mismatch"):
        gateway.dispatch(rid2, "something else")
    assert len(backend.calls) == 1


def test_a_forged_receipt_id_is_refused():
    gateway, store, backend, _ = build()
    for guess in ("", "x" * 32, None, 7):
        with pytest.raises(StopBoundary):
            gateway.dispatch(guess, "p")
    assert backend.calls == []


def test_backend_failure_after_admission_is_reported_and_never_retried():
    class Boom(CountingBackend):
        def complete(self, prompt):
            self.calls.append(prompt)
            raise RuntimeError("provider down")
    gateway, store, backend, _ = build(backend=Boom())
    out = gateway.invoke(request())
    assert out.admitted is True and out.reason == "admitted-model-failed:RuntimeError" and out.output is None
    assert len(backend.calls) == 1


def test_every_invoke_kind_needs_its_own_fresh_admission():
    gateway, store, backend, _ = build()
    for i, kind in enumerate(("normal", "retry", "resume", "tool-continuation", "subagent")):
        assert gateway.invoke(request(invocation_id=f"k{i}", kind=kind, prompt=kind)).admitted
        assert store.posts == i + 1 and len(backend.calls) == i + 1
    assert gateway.stats.receipts_issued == gateway.stats.receipts_consumed == 5


def test_trace_and_outcomes_never_contain_prompts_lessons_or_credentials():
    credential_marker = "sk-test-NOT-A-REAL-CREDENTIAL"
    gateway, store, backend, _ = build()
    out = gateway.invoke(request(prompt="PROMPT-SENTINEL " + credential_marker))
    blob = json.dumps([list(out.trace), gateway.trace_log], default=str)
    assert "PROMPT-SENTINEL" not in blob and credential_marker not in blob and "LL-87" not in blob.replace("selected_lesson_ids", "")


# ------------------------------------------------------------------------ sessions
def test_session_budget_expiry_and_kind_rules():
    gateway, store, backend, clock = build(
        )
    s = gateway.open_session(request())
    assert s.admitted
    for kind in ("retry", "resume", "stream", "subagent"):
        assert gateway.session_turn(s.session, kind, "x", idempotency_key="k-" + kind).admitted is False
    assert backend.calls == []
    for i in range(8):
        assert gateway.session_turn(s.session, "normal", f"t{i}", idempotency_key=f"t{i}").admitted
    over = gateway.session_turn(s.session, "normal", "t9", idempotency_key="t9")
    assert (over.admitted, over.reason) == (False, "session-turn-budget-exhausted")
    assert len(backend.calls) == 8 and store.posts == 1
    s2 = gateway.open_session(request(invocation_id="inv-2"))
    clock.sleep(301)
    expired = gateway.session_turn(s2.session, "normal", "late", idempotency_key="late")
    assert (expired.admitted, expired.reason) == (False, "session-expired-needs-new-admission")
    assert len(backend.calls) == 8
    again = gateway.session_turn(s2.session, "normal", "late", idempotency_key="late2")
    assert again.reason == "unknown-session"  # closed on expiry; resume needs a NEW admission


def test_session_idempotency_key_replays_without_a_second_call_and_rejects_reuse_with_other_prompt():
    gateway, store, backend, _ = build()
    s = gateway.open_session(request())
    a = gateway.session_turn(s.session, "normal", "same", idempotency_key="k")
    b = gateway.session_turn(s.session, "normal", "same", idempotency_key="k")
    c = gateway.session_turn(s.session, "normal", "other", idempotency_key="k")
    assert b.replayed and b.output == a.output and (c.admitted, c.reason) == (False, "idempotency-key-reuse-mismatch")
    assert len(backend.calls) == 1


def test_subagent_sessions_inherit_binding_expiry_and_budget_and_die_with_the_parent():
    gateway, store, backend, clock = build()
    s = gateway.open_session(request())
    child = gateway.session_child(s.session)
    assert child.admitted
    assert gateway.session_turn(child.session, "subagent", "sub work", idempotency_key="c1").admitted
    assert store.posts == 1  # inherits the parent's admission; no new GitHub request
    grand = gateway.session_child(child.session)
    assert grand.admitted
    assert gateway.session_child(grand.session).reason == "subagent-limit-reached"  # depth bound
    gateway.session_close(s.session)  # parent closes -> whole subtree closes
    for token in (child.session, grand.session):
        assert gateway.session_turn(token, "subagent", "x", idempotency_key="z").reason == "unknown-session"
    assert len(backend.calls) == 1


def test_a_child_cannot_outspend_its_parents_budget():
    gateway, store, backend, _ = build()
    s = gateway.open_session(request())
    child = gateway.session_child(s.session)           # takes 4 of 8
    other = gateway.session_child(s.session)           # takes 2 of remaining 4
    assert child.admitted and other.admitted
    spent = 0
    for token in (child.session, other.session, s.session):
        for i in range(10):
            if gateway.session_turn(token, "subagent" if token != s.session else "normal", "p", idempotency_key=f"{token[:4]}{i}").admitted:
                spent += 1
    assert spent <= 8 and len(backend.calls) == spent


def test_session_for_a_denied_admission_does_not_exist():
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    opened = gateway.open_session(request())
    assert opened.admitted is False and opened.session is None
    assert gateway.session_turn("anything", "normal", "x", idempotency_key="k").reason == "unknown-session"
    assert backend.calls == []


# ------------------------------------------------------------------------ streaming
def test_admitted_stream_calls_the_provider_once_after_admission():
    gateway, store, backend, _ = build()
    assert list(gateway.invoke_stream(request())) == ["a", "b", "c"]
    assert len(backend.calls) == 1 and store.posts == 1


def test_denied_stream_never_reaches_the_provider():
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    with pytest.raises(StopBoundary, match="bounded-wait-expired"):
        next(gateway.invoke_stream(request()))
    assert backend.calls == [] and gateway.stats.backend_calls == 0


def test_partial_stream_failure_is_not_retried_and_closes_the_session():
    class Flaky(CountingBackend):
        def stream(self, prompt):
            self.calls.append(prompt)
            yield "first"
            raise ConnectionError("dropped")
    gateway, store, backend, _ = build(backend=Flaky())
    s = gateway.open_session(request())
    got = []
    with pytest.raises(StopBoundary, match="stream-aborted-no-retry"):
        for chunk in gateway.session_stream(s.session, "p", idempotency_key="s1"):
            got.append(chunk)
    assert got == ["first"] and len(backend.calls) == 1
    assert gateway.session_turn(s.session, "normal", "again", idempotency_key="s2").reason == "unknown-session"
    assert len(backend.calls) == 1


def test_stream_cancellation_stops_delivery():
    gateway, store, backend, _ = build()
    cancel = threading.Event()
    s = gateway.open_session(request())
    got = []
    with pytest.raises(StopBoundary, match="cancelled-during-stream"):
        for chunk in gateway.session_stream(s.session, "p", idempotency_key="s1", cancel=cancel):
            got.append(chunk); cancel.set()
    assert got == ["a"]


# ------------------------------------------------------------------ RPC surface (in-process)
def rpc_pair(gateway, binding=None, **kw):
    from agent_os_execution_service.ckr6_model_gateway.rpc import GatewayRpcServer
    from agent_os_execution_service.ckr6_model_gateway.worker_client import GatewayClient
    a, b = socket.socketpair()
    server = GatewayRpcServer(gateway, binding or request(prompt=""), **kw)
    threading.Thread(target=server.serve, args=(a,), daemon=True).start()
    return server, GatewayClient(os.dup(b.fileno()))


def test_rpc_rejects_malformed_oversized_extra_field_and_foreign_frames():
    gateway, store, backend, _ = build()
    server, client = rpc_pair(gateway)
    assert client.raw({"method": "nope"})["reason"] == "bad-frame"
    assert client.raw({"method": "open", "session": "x"})["reason"] == "bad-frame"
    assert client.raw({"method": "open", "task_reference": "other task"})["reason"] == "bad-frame"  # no identity override
    assert client.raw({"method": "open", "repository": "Other/repo"})["reason"] == "bad-frame"
    assert client.raw({"nomethod": 1})["reason"] == "bad-frame"
    assert backend.calls == [] and store.posts == 0
    opened = client.open()
    assert opened["admitted"] is True
    assert client.raw({"method": "turn", "session": opened["session"], "kind": "normal", "prompt": 5, "key": "k"})["reason"] == "bad-frame"
    assert backend.calls == []


def test_rpc_session_tokens_are_not_transferable_between_connections():
    gateway, store, backend, _ = build()
    _, c1 = rpc_pair(gateway)
    _, c2 = rpc_pair(gateway, request(prompt="", invocation_id="inv-b"))
    tok = c1.open()["session"]
    assert c2.turn(tok, "normal", "steal", "k")["reason"] == "unknown-session"
    assert backend.calls == []


def test_rpc_open_is_rate_limited_so_a_worker_cannot_spam_github():
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    _, client = rpc_pair(gateway, max_opens=2)
    assert client.open()["reason"] == "bounded-wait-expired"
    assert client.open()["reason"] == "bounded-wait-expired"
    assert client.open()["reason"] == "open-limit-reached"
    assert store.posts == 2


def test_rpc_trusted_side_cancel_stops_a_waiting_worker():
    clock = FakeClock()
    holder = {}
    orig = clock.sleep
    clock.sleep = lambda s: (holder["server"].cancel.set(), orig(s))[1]
    gateway, store, backend, _ = build(producer=lambda e, r: None, clock=clock)
    server, client = rpc_pair(gateway)
    holder["server"] = server
    assert client.open()["reason"] == "cancelled-while-waiting" and backend.calls == []


# ---------------------------------------------------------- provider credential hygiene
def test_provider_backend_repr_never_exposes_the_credential():
    from agent_os_execution_service.ckr6_model_gateway.provider import HttpProviderBackend
    backend = HttpProviderBackend("127.0.0.1", 1, "sk-test-NOT-A-REAL-CREDENTIAL")
    assert "NOT-A-REAL" not in repr(backend) and "NOT-A-REAL" not in str(backend)


def test_isolated_spawn_fails_closed_when_isolation_is_impossible(monkeypatch):
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    monkeypatch.setattr(supervisor, "_PRIVILEGED", False)
    with pytest.raises(supervisor.IsolationUnavailable):
        supervisor.spawn_isolated_worker([sys.executable, "-I", "-c", "print('must never run')"])


def test_launcher_failure_raises_instead_of_returning_a_dead_or_unisolated_process(monkeypatch):
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    from agent_os_execution_service.ckr6_model_gateway.supervisor import InProcessUidAllocator
    never = [sys.executable, "-I", "-c", "print('must never run')"]
    with pytest.raises(supervisor.IsolationUnavailable):
        supervisor.spawn_isolated_worker([], allocator=make_allocator())
    root = InProcessUidAllocator(0, 1)  # a bad allocator must not be able to produce an un-dropped worker
    with pytest.raises(supervisor.IsolationUnavailable):
        supervisor.spawn_isolated_worker(never, allocator=root)
    failing = Path(tempfile.mkdtemp(prefix="aos-launcher-")) / "fail.py"
    failing.write_text("import os\nos._exit(97)\n")
    monkeypatch.setattr(supervisor, "_LAUNCHER", str(failing))
    with pytest.raises(supervisor.IsolationUnavailable):  # launcher died before readiness -> raise, no Popen
        supervisor.spawn_isolated_worker(never, allocator=make_allocator())


def test_in_process_uid_allocator_never_hands_out_a_uid_twice_and_exhaustion_fails_closed():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import IsolationUnavailable, InProcessUidAllocator
    alloc = InProcessUidAllocator(500_000, 3)
    assert [alloc.allocate() for _ in range(3)] == [500_000, 500_001, 500_002]
    with pytest.raises(IsolationUnavailable):
        alloc.allocate()


def test_A1prime_uids_are_unique_across_processes_and_forks_sharing_one_state_dir():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import UidAllocator
    state = tempfile.mkdtemp(prefix="aos-uids-")
    parent = UidAllocator(state)
    got = [parent.allocate()]  # parent has used the allocator BEFORE forking (the QA collision case)
    pipes = []
    for _ in range(4):
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            try:
                alloc = UidAllocator(state)
                os.write(w, json.dumps([alloc.allocate() for _ in range(25)]).encode())
            finally:
                os._exit(0)
        os.close(w); pipes.append((pid, r))
    got += [parent.allocate() for _ in range(25)]
    for pid, r in pipes:
        data = b""
        while chunk := os.read(r, 65536):
            data += chunk
        os.close(r); os.waitpid(pid, 0)
        got += json.loads(data)
    assert len(got) == 1 + 25 + 4 * 25 and len(set(got)) == len(got)  # no uid ever handed out twice


def test_A1prime_a_uid_cannot_be_claimed_twice_and_an_untrusted_state_dir_is_refused():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        IsolationUnavailable, UidAllocator, claim_uid)
    first = claim_uid(3_500_000_000)
    with pytest.raises(IsolationUnavailable, match="worker-uid-in-use"):
        claim_uid(3_500_000_000)  # exclusive no matter which allocator or state dir asks
    first.release()
    claim_uid(3_500_000_000).release()  # free again once the holder is gone
    loose = tempfile.mkdtemp(prefix="aos-uids-"); os.chmod(loose, 0o777)  # a worker could tamper with it
    with pytest.raises(IsolationUnavailable, match="uid-state-dir-untrusted"):
        UidAllocator(loose)
    parent = tempfile.mkdtemp(prefix="aos-uids-")
    os.mkdir(os.path.join(parent, "state"), 0o700)
    link = parent + "-link"
    os.symlink(parent, link)  # the FINAL component is a real 0700 dir; the symlink is higher up the path
    with pytest.raises(IsolationUnavailable, match="uid-state-dir-untrusted"):
        UidAllocator(os.path.join(link, "state"))


def test_A1prime_a_corrupt_counter_fails_closed_with_isolation_unavailable():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import IsolationUnavailable, UidAllocator
    state = tempfile.mkdtemp(prefix="aos-uids-")
    alloc = UidAllocator(state)
    for garbage in (b"garbage", b"1.5", b"\x00\x00", b"-7", b"99999999999999999999"):
        Path(state, "counter").write_bytes(garbage)
        with pytest.raises(IsolationUnavailable):
            alloc.allocate()


def test_A1doubleprime_concurrent_spawns_from_supervisors_with_separate_state_dirs_never_share_a_uid():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        IsolationUnavailable, UidAllocator, isolation_available, spawn_isolated_worker)
    import secrets
    sleeper = [sys.executable, "-I", "-c", "import time; time.sleep(30)"]
    spawned, lock = [], threading.Lock()
    try:
        for _ in range(4):
            base = 3_200_000_000 + secrets.randbelow(100_000_000)
            allocs = [UidAllocator(tempfile.mkdtemp(prefix="aos-uids-"), start=base) for _ in range(2)]
            barrier = threading.Barrier(2)
            results = []

            def go(alloc):
                barrier.wait()  # both launchers run concurrently: the window where /proc cannot see a uid
                try:
                    proc = spawn_isolated_worker(sleeper, allocator=alloc)
                except IsolationUnavailable as exc:
                    results.append(("refused", str(exc)))
                else:
                    with lock:
                        spawned.append(proc)
                    results.append(("started", proc.aos_uid))
            threads = [threading.Thread(target=go, args=(a,)) for a in allocs]
            [t.start() for t in threads]; [t.join() for t in threads]
            if not isolation_available():
                assert all(kind == "refused" for kind, _ in results)  # nothing started; proves nothing
                return
            started = [uid for kind, uid in results if kind == "started"]
            assert len(started) == len(set(started)) and len(started) <= 1  # one worker per uid, ever
    finally:
        for proc in spawned:
            proc.kill(); proc.communicate()


def test_A1prime_overlapping_independent_allocators_cannot_put_two_live_workers_on_one_uid():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        IsolationUnavailable, UidAllocator, isolation_available, spawn_isolated_worker)
    import secrets
    sleeper = [sys.executable, "-I", "-c", "import time; time.sleep(30)"]
    base = 3_600_000_000 + secrets.randbelow(100_000_000)  # random so a leaked process can never poison a rerun
    one = UidAllocator(tempfile.mkdtemp(prefix="aos-uids-"), start=base)
    two = UidAllocator(tempfile.mkdtemp(prefix="aos-uids-"), start=base)  # same range, separate state
    spawned = []
    try:
        try:
            spawned.append(spawn_isolated_worker(sleeper, allocator=one))
        except IsolationUnavailable:
            assert isolation_available() is False  # nothing started; this run proves nothing about isolation
            return
        try:
            spawned.append(spawn_isolated_worker(sleeper, allocator=two))  # would be the SAME uid as the live worker
        except IsolationUnavailable as exc:
            assert "worker-uid-in-use" in str(exc)
        else:
            pytest.fail("two live workers were given the same uid")
    finally:
        for proc in spawned:
            proc.kill(); proc.communicate()


def test_A1prime_a_worker_orphaned_by_a_crashed_supervisor_still_blocks_its_uid():
    import secrets
    import signal
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        InProcessUidAllocator, IsolationUnavailable, UidAllocator, isolation_available, spawn_isolated_worker)
    base = 3_300_000_000 + secrets.randbelow(100_000_000)
    sleeper = [sys.executable, "-I", "-c", "import time; time.sleep(30)"]
    state = tempfile.mkdtemp(prefix="aos-uids-")
    r, w = os.pipe()
    child = os.fork()
    if child == 0:  # a supervisor that spawns a worker and then CRASHES: its uid claim dies with it
        try:
            proc = spawn_isolated_worker(sleeper, allocator=UidAllocator(state, start=base))
            os.write(w, json.dumps({"uid": proc.aos_uid, "pid": proc.pid}).encode())
        except IsolationUnavailable:
            os.write(w, b"{}")
        finally:
            os._exit(0)
    os.close(w)
    info = json.loads(os.read(r, 4096) or b"{}"); os.close(r); os.waitpid(child, 0)
    if not info:
        assert isolation_available() is False
        return
    try:
        with pytest.raises(IsolationUnavailable, match="worker-uid-in-use"):  # claim is gone; only /proc can refuse
            spawn_isolated_worker(sleeper, allocator=InProcessUidAllocator(info["uid"], 1))
    finally:
        os.kill(info["pid"], signal.SIGKILL)


def test_isolation_probe_refuses_a_worker_uid_outside_the_mapped_range(tmp_path):
    # T13: the probe used to report True (root + unshare) on hosts whose uid_map
    # cannot cover a worker uid, while every spawn then failed at setgid.
    from agent_os_execution_service.ckr6_model_gateway.supervisor import _uid_mapped
    uid_map, gid_map = tmp_path / "uid_map", tmp_path / "gid_map"
    uid_map.write_text("         0     131072      65536\n")
    gid_map.write_text("         0     131072      65536\n")
    assert _uid_mapped(3_000_000_000, uid_map_path=str(uid_map), gid_map_path=str(gid_map)) is False
    assert _uid_mapped(100, uid_map_path=str(uid_map), gid_map_path=str(gid_map)) is True
    uid_map.write_text("         0          0 4294967295\n")
    gid_map.write_text("         0          0 4294967295\n")
    assert _uid_mapped(3_000_000_000, uid_map_path=str(uid_map), gid_map_path=str(gid_map)) is True


def test_A1prime_a_worker_runs_in_its_own_session():
    # T13 (F20): no regression test asserted start_new_session. Fail-first proof
    # (removing start_new_session) is deferred to a privileged host: this sandbox
    # cannot spawn, so here the test only asserts the fail-closed path.
    import secrets
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        InProcessUidAllocator, IsolationUnavailable, isolation_available, spawn_isolated_worker)
    sleeper = [sys.executable, "-I", "-c", "import time; time.sleep(30)"]
    uid = 3_500_000_000 + secrets.randbelow(100_000_000)
    try:
        proc = spawn_isolated_worker(sleeper, allocator=InProcessUidAllocator(uid, 1))
    except IsolationUnavailable:
        assert isolation_available() is False  # nothing started; proves nothing about sessions
        return
    try:
        assert os.getsid(proc.pid) != os.getsid(0)  # start_new_session: no shared process group
    finally:
        proc.kill(); proc.communicate()


def test_B1_a_supervisor_killed_mid_launch_does_not_free_the_uid_while_the_launcher_lives():
    import secrets
    import signal
    import time
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        InProcessUidAllocator, IsolationUnavailable, claim_uid, isolation_available, spawn_isolated_worker)
    if not isolation_available():
        with pytest.raises(IsolationUnavailable):  # nothing can launch here, so there is no window to test
            spawn_isolated_worker([sys.executable, "-I", "-c", "pass"], allocator=InProcessUidAllocator(3_400_000_000, 1))
        return
    uid = 3_400_000_000 + secrets.randbelow(100_000_000)
    # The REAL launcher with a stall inserted after unshare and before the uid drop: the window in which the
    # process is still root and /proc cannot see it at the worker uid.
    source = Path(supervisor._LAUNCHER).read_text()
    assert "    os.setgroups([])" in source
    slow = Path(tempfile.mkdtemp(prefix="aos-slow-")) / "slow_launcher.py"
    slow.write_text(source.replace("    os.setgroups([])", "    import time; time.sleep(4)\n    os.setgroups([])", 1))
    os.chmod(slow.parent, 0o755); os.chmod(slow, 0o644)
    r, w = os.pipe()
    child = os.fork()
    if child == 0:  # the supervisor: it will be SIGKILLed while the launcher is still pre-drop
        supervisor._LAUNCHER = str(slow)
        os.write(w, b"go")
        try:
            spawn_isolated_worker([sys.executable, "-I", "-c", "import time; time.sleep(8)"],
                                  allocator=InProcessUidAllocator(uid, 1))
        finally:
            os._exit(0)
    os.close(w); os.read(r, 2); os.close(r)
    time.sleep(1.0)               # launcher is now sleeping, still root, not yet at the worker uid
    os.kill(child, signal.SIGKILL); os.waitpid(child, 0)
    try:
        with pytest.raises(IsolationUnavailable, match="worker-uid-in-use"):
            claim_uid(uid)        # the dead supervisor's claim is still held by the launcher it spawned
    finally:
        time.sleep(0.2)
        subprocess.run(["pkill", "-f", "time.sleep\\(8\\)"], check=False)
        subprocess.run(["pkill", "-f", "slow_launcher.py"], check=False)
        time.sleep(0.2)


def test_A1prime_a_uid_belonging_to_a_real_host_account_is_never_used_for_a_worker():
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        InProcessUidAllocator, IsolationUnavailable, isolation_available, spawn_isolated_worker)
    marker = Path(tempfile.mkdtemp(prefix="aos-acct-")) / "ran"
    program = [sys.executable, "-I", "-c", f"open({str(marker)!r}, 'w').write('x')"]
    with pytest.raises(IsolationUnavailable):  # 65534 is the real 'nobody' account on this and most hosts
        spawn_isolated_worker(program, allocator=InProcessUidAllocator(65534, 1))
    assert not marker.exists()  # and the program never ran, as any uid
    assert isolation_available() in (True, False)


def test_a_crashing_binding_hook_is_a_stop_and_never_leaves_an_idempotency_key_stuck():
    calls = {"n": 0}

    def hook(req):
        calls["n"] += 1
        if calls["n"] <= 2:  # the hook runs twice per turn (direct check + inside consume)
            return True
        raise RuntimeError("hook crashed")
    gateway, store, backend, _ = build(verify_binding_current=hook)
    s = gateway.open_session(request())
    first = gateway.session_turn(s.session, "normal", "p", idempotency_key="k")
    assert (first.admitted, first.reason) == (True, "admitted")
    boom = gateway.session_turn(s.session, "normal", "q", idempotency_key="k2")
    assert (boom.admitted, boom.reason) == (False, "binding-check-failed")
    again = gateway.session_turn(s.session, "normal", "q", idempotency_key="k2")
    assert again.replayed is True and again.reason == "binding-check-failed"  # not "in-flight" forever
    assert len(backend.calls) == 1


# ------------------------------------------------------------ real Claude launch seam
def claude_invocation():
    from agent_os_execution_service.coding_worker_claude_adapter import build_claude_coding_worker_invocation
    from agent_os_execution_service.coding_worker_contract import (
        CODING_WORKER_SCHEMA_VERSION, CodingWorkerOperation, CodingWorkerRequest)
    worker_request = CodingWorkerRequest(
        schema_version=CODING_WORKER_SCHEMA_VERSION, task_id="issue-4001", repository=REPO,
        issue_or_handoff_identity="issue:4001", base_sha="a" * 40, workspace_identity="workspace:issue-4001",
        operation=CodingWorkerOperation.IMPLEMENT, implementation_packet_source_identity="packet:source:4001",
        executor_handoff_id="executor-handoff:4001", allowed_paths=("08_Tooling/agent-os-execution-service",),
        forbidden_paths=(".github",))
    return build_claude_coding_worker_invocation(
        request=worker_request, implementation_packet={"objective": "bounded"}, packet_source_fingerprint="1" * 64,
        source_identity_fingerprint="2" * 64, executable_path="/usr/local/bin/claude", observed_version="2.1.233",
        authenticated=True, working_directory="/workspace/agent-os")


class CountingLauncher:
    def __init__(self):
        self.spawns = []

    def __call__(self, argv, cwd):
        self.spawns.append((argv, cwd))
        return "handle"


def test_claude_launch_is_denied_without_ckr6_admission_and_spawns_nothing():
    from agent_os_execution_service.ckr6_model_gateway.claude_launch_gate import gated_claude_launch
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    launcher = CountingLauncher()
    out = gated_claude_launch(gateway, request(), claude_invocation(), launcher)
    assert (out.admitted, out.reason, out.scope) == (False, "bounded-wait-expired", "session-start-only")
    assert launcher.spawns == [] and gateway.stats.launches == 0


def test_claude_launch_is_admitted_once_bound_to_the_exact_argv_and_is_session_start_only():
    from agent_os_execution_service.ckr6_model_gateway.claude_launch_gate import gated_claude_launch
    gateway, store, backend, _ = build()
    launcher, invocation = CountingLauncher(), claude_invocation()
    out = gated_claude_launch(gateway, request(), invocation, launcher)
    assert (out.admitted, out.output, out.scope) == (True, "handle", "session-start-only")
    assert launcher.spawns == [(invocation.native_invocation.argv, "/workspace/agent-os")]
    assert backend.calls == []  # a launch is not a model call: it is NOT claimed as model-entry mediation
    order = events(out)
    assert order.index("repository-r07-boundary-admitted") < order.index("receipt-consumed") < order.index("launch-started")
    again = gated_claude_launch(gateway, request(), invocation, launcher)
    assert again.replayed is True and len(launcher.spawns) == 1  # native invocation id is the idempotency key


def test_claude_launch_receipt_is_scoped_to_launch_not_to_model_calls():
    gateway, store, backend, _ = build()
    captured = []
    real = gateway._issue_receipt
    gateway._issue_receipt = lambda *a, **k: captured.append(real(*a, **k)) or captured[-1]
    from agent_os_execution_service.ckr6_model_gateway.claude_launch_gate import gated_claude_launch
    gated_claude_launch(gateway, request(), claude_invocation(), CountingLauncher())
    trace = gateway._trace()
    proof, _ = gateway._admitter.admit(request(invocation_id="x"), trace)
    rid = real(trace, request(invocation_id="x"), proof, kind="normal", binding_sha256="0" * 64,
               session_id=None, scope="ckr6-session-start")
    with pytest.raises(StopBoundary, match="receipt-scope-mismatch"):
        gateway.dispatch(rid, "p")  # a launch receipt can never buy a provider call
    assert backend.calls == []


def test_stream_invocation_id_cannot_be_reused_to_obtain_a_second_provider_stream():
    gateway, store, backend, _ = build()
    assert list(gateway.invoke_stream(request())) == ["a", "b", "c"]
    with pytest.raises(StopBoundary, match="stream-invocation-id-already-used"):
        next(gateway.invoke_stream(request()))
    assert store.posts == 1 and len(backend.calls) == 1


@pytest.mark.parametrize("changes", [
    {"issue_number": "4001"}, {"issue_number": True}, {"repository": None}, {"task_reference": 7},
    {"library_hints": ["list-not-tuple"]}, {"language_hints": (1,)}, {"prompt": b"bytes"},
])
def test_malformed_requests_are_denied_cleanly_never_raised_and_never_reach_ingress_or_provider(changes):
    gateway, store, backend, _ = build()
    out = gateway.invoke(request(**changes))
    assert out.admitted is False and out.reason in ("invalid-request", "invalid-prompt")
    assert store.posts == 0 and backend.calls == []
    assert gateway.open_session(request(**changes)).admitted is False


# =========================================================================== QA regression suite
# Each test below reproduces a finding from the independent adversarial QA pass (A1, B1-B8, C1-C6).
PEER_ATTACK_SOURCE = r'''
import ctypes, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from worker_client import GatewayClient
role, victim_pid = sys.argv[1], int(sys.argv[2])
c = GatewayClient(int(os.environ["AOS_GATEWAY_FD"]))
if role == "victim":
    opened = c.open()
    print(json.dumps({"uid": os.getuid(), "admitted": opened["admitted"], "pid": os.getpid()}), flush=True)
    time.sleep(25)
    sys.exit(0)
out = {"uid": os.getuid(), "own_open": c.open()["admitted"]}
for name in ("environ", "mem", "maps"):
    try:
        open(f"/proc/{victim_pid}/{name}", "rb").read(1); out[name] = "READ"
    except OSError as exc:
        out[name] = "blocked:" + type(exc).__name__
try:
    pidfd = os.pidfd_open(victim_pid)
    libc = ctypes.CDLL(None, use_errno=True)
    stolen = [fd for fd in range(3, 12) if libc.syscall(438, pidfd, fd, 0) >= 0]  # pidfd_getfd
    out["stolen_fds"] = stolen
except OSError as exc:
    out["stolen_fds"] = "blocked:" + type(exc).__name__
try:
    os.kill(victim_pid, 0); out["signal"] = "ALLOWED"
except OSError as exc:
    out["signal"] = "blocked:" + type(exc).__name__
print(json.dumps(out))
'''


def test_A1_a_denied_worker_cannot_borrow_an_admitted_workers_gateway_socket():
    from agent_os_execution_service.ckr6_model_gateway import worker_client
    from agent_os_execution_service.ckr6_model_gateway.rpc import GatewayRpcServer
    from agent_os_execution_service.ckr6_model_gateway.supervisor import (
        IsolationUnavailable, isolation_available, spawn_isolated_worker)
    gateway, store, backend, _ = build(
        producer=lambda env, rid: sufficient_result(env, rid) if env.issue_number == ISSUE else None)
    workdir = Path(tempfile.mkdtemp(prefix="aos-peer-")); os.chmod(workdir, 0o755)
    (workdir / "w.py").write_text(PEER_ATTACK_SOURCE); shutil.copy(worker_client.__file__, workdir / "worker_client.py")
    for f in workdir.iterdir():
        os.chmod(f, 0o644)
    socks, procs = [], []

    def start(binding, role, victim_pid):
        a, b = socket.socketpair(); socks.extend([a, b])
        threading.Thread(target=GatewayRpcServer(gateway, binding).serve, args=(a,), daemon=True).start()
        proc = spawn_isolated_worker([sys.executable, "-I", str(workdir / "w.py"), role, str(victim_pid)],
                                     pass_fds=(b.fileno(),), env={"AOS_GATEWAY_FD": str(b.fileno())}, cwd=str(workdir),
                                     allocator=make_allocator())
        procs.append(proc)
        return proc
    try:
        try:
            victim = start(request(prompt="", invocation_id="victim"), "victim", 0)
        except IsolationUnavailable:
            assert isolation_available() is False  # fail closed: nothing started, nothing to attack
            return
        info = json.loads(victim.stdout.readline())
        assert info["admitted"] is True
        attacker = start(request(prompt="", invocation_id="attacker", issue_number=ISSUE + 1), "attacker", info["pid"])
        out = json.loads(attacker.communicate(timeout=60)[0].decode().strip().splitlines()[-1])
        assert out["uid"] != info["uid"] and out["uid"] != 0 and info["uid"] != 0   # unique uid per worker
        assert out["own_open"] is False                                             # its own CKR6 admission was denied
        assert out["environ"].startswith("blocked") and out["mem"].startswith("blocked")
        assert out["stolen_fds"] == [] or str(out["stolen_fds"]).startswith("blocked")
        assert out["signal"].startswith("blocked")
        assert backend.calls == [] and gateway.stats.backend_calls == 0
    finally:
        for proc in procs:
            proc.kill(); proc.communicate()
        for sock in socks:
            sock.close()
        shutil.rmtree(workdir, ignore_errors=True)


def test_B1_a_denied_stream_is_never_later_reported_as_admitted():
    gateway, store, backend, _ = build(producer=lambda e, r: None)
    with pytest.raises(StopBoundary, match="bounded-wait-expired"):
        next(gateway.invoke_stream(request()))
    later = gateway.invoke(request())
    assert later.admitted is False and later.reason == "bounded-wait-expired" and backend.calls == []
    gateway, store, backend, _ = build(verify_binding_current=lambda r: False)
    s = gateway.open_session(request())
    with pytest.raises(StopBoundary, match="stale-binding"):
        next(gateway.session_stream(s.session, "p", idempotency_key="k"))
    after = gateway.session_turn(s.session, "normal", "p", idempotency_key="k")
    assert after.admitted is False and backend.calls == []


class SlowBackend(CountingBackend):
    def complete(self, prompt):
        import time
        time.sleep(0.05)
        return super().complete(prompt)

    def stream(self, prompt):
        import time
        self.calls.append(prompt)
        time.sleep(0.05)
        yield "x"


def test_B2_concurrent_streams_cannot_overspend_the_session_budget():
    gateway, store, backend, _ = build(backend=SlowBackend())
    s = gateway.open_session(request())
    for i in range(7):
        assert gateway.session_turn(s.session, "normal", f"t{i}", idempotency_key=f"t{i}").admitted
    results, barrier = [], threading.Barrier(10)

    def go(i):
        barrier.wait()
        try:
            list(gateway.session_stream(s.session, f"s{i}", idempotency_key=f"s{i}"))
            results.append("ok")
        except StopBoundary as exc:
            results.append(exc.reason)
    threads = [threading.Thread(target=go, args=(i,)) for i in range(10)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert results.count("ok") == 1 and len(backend.calls) == 8
    assert gateway._sessions[s.session].turns_left == 0


def test_B3_concurrent_turns_with_one_idempotency_key_make_exactly_one_provider_call():
    gateway, store, backend, _ = build(backend=SlowBackend())
    s = gateway.open_session(request())
    outs, barrier = [], threading.Barrier(6)

    def go():
        barrier.wait()
        outs.append(gateway.session_turn(s.session, "normal", "same", idempotency_key="k"))
    threads = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(backend.calls) == 1
    assert sum(1 for o in outs if o.admitted and not o.replayed) == 1


def test_B4_session_tokens_are_never_replayed_or_shared_between_connections():
    gateway, store, backend, _ = build()
    first = gateway.open_session(request())
    again = gateway.open_session(request())
    assert first.admitted and (again.admitted, again.reason) == (False, "session-open-id-already-used")
    assert again.session is None
    # two RPC connections built from the SAME binding id still get distinct admissions and tokens
    _, c1 = rpc_pair(gateway, request(prompt="", invocation_id="dup"))
    _, c2 = rpc_pair(gateway, request(prompt="", invocation_id="dup"))
    t1, t2 = c1.open()["session"], c2.open()["session"]
    assert t1 and t2 and t1 != t2
    assert c2.turn(t1, "normal", "borrow", "k")["reason"] == "unknown-session"
    assert backend.calls == []


@pytest.mark.parametrize("ids", [[], ["LL-1", "LL-1"], [" "]])
def test_B5_failed_repair_sufficient_needs_a_valid_selection_like_issue_start(ids):
    lessons = [{"lesson_id": i, "source_revision": "r", "selection_reason_codes": []} for i in ids]
    gateway, store, backend, _ = build(
        producer=lambda e, r: sufficient_result(e, r, selected_lesson_ids=ids, selected_lessons=lessons))
    out = gateway.invoke(repair())
    assert out.admitted is False and out.reason == "sufficient-without-valid-selection" and backend.calls == []


def test_B5b_a_sufficient_result_that_says_retrieval_was_not_required_is_refused():
    gateway, store, backend, _ = build(producer=lambda e, r: sufficient_result(e, r, retrieval_required=False))
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-contradicts-materiality") and backend.calls == []


def test_B7_a_request_subclass_cannot_swap_the_prompt_after_the_receipt_is_bound():
    class Shifty(InvocationRequest):
        __slots__ = ()
        reads = [0]

        @property
        def prompt(self):  # a different value on later reads
            Shifty.reads[0] += 1
            return "benign" if Shifty.reads[0] == 1 else "EVIL never bound"

        @prompt.setter
        def prompt(self, value):
            pass
    gateway, store, backend, _ = build()
    out = gateway.invoke(Shifty(invocation_id="s", operation="issue-start", repository=REPO, issue_number=ISSUE,
                                task_reference="integrate pydantic validators", **HINTS))
    assert (out.admitted, out.reason) == (False, "invalid-request") and backend.calls == []


def test_B8_result_and_request_timestamps_are_checked_against_the_deadline_and_the_local_clock():
    def late_result(seconds):
        def producer(env, rid):  # injected AFTER the request so its id is valid; shown immediately (no time filter)
            holder["store"].add_result(
                bridge.serialize_ckr6_result_comment(sufficient_result(env, rid), request_comment_id=rid),
                at=T0 + timedelta(seconds=seconds))
            return None
        return producer
    holder = {}
    # result dated after the 360 s window although the transport shows it immediately
    gateway, store, backend, _ = build(producer=late_result(400))
    holder["store"] = store; store.no_time_filter = True
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-after-deadline") and backend.calls == []
    # result dated in the future (but inside the window) relative to the local clock
    gateway, store, backend, _ = build(producer=late_result(300))
    holder["store"] = store; store.no_time_filter = True
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-from-the-future") and backend.calls == []
    # request readback dated far in the future
    gateway, store, backend, _ = build()
    store.tamper_after_post = lambda rec: rec.update(created_at=iso(T0 + timedelta(days=3650)),
                                                     updated_at=iso(T0 + timedelta(days=3650)))
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "request-readback-mismatch:clock-skew") and backend.calls == []


def test_B8b_records_without_updated_at_are_refused_because_an_edit_could_hide():
    gateway, store, backend, _ = build()
    store.tamper_after_post = lambda rec: rec.pop("updated_at")
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "request-readback-mismatch:edited") and backend.calls == []
    gateway, store, backend, _ = build()

    def hook(n):
        for rec in store.records:
            if rec["body"].startswith(bridge.CKR6_RESULT_MARKER):
                rec.pop("updated_at", None)
    store.list_hook = hook
    out = gateway.invoke(request())
    assert (out.admitted, out.reason) == (False, "result-record-missing-or-edited-updated_at") and backend.calls == []


def test_C1_hostile_json_nesting_does_not_kill_the_rpc_connection():
    gateway, store, backend, _ = build()
    _, client = rpc_pair(gateway)
    # T13 (F10/M26): a thread-killing mutant must fail fast here, never hang the suite.
    client._sock.settimeout(10)
    client._file.write(b"[" * 200000 + b"\n"); client._file.flush()
    assert client._recv()["reason"] == "bad-frame"
    assert client.open()["admitted"] is True  # the same connection still works


def test_C2_oversized_frame_is_discarded_whole_without_desyncing_the_stream():
    from agent_os_execution_service.ckr6_model_gateway.rpc import MAX_FRAME_BYTES
    gateway, store, backend, _ = build()
    _, client = rpc_pair(gateway)
    client._file.write(b"x" * (MAX_FRAME_BYTES + 10) + b'{"method":"open"}\n'); client._file.flush()
    assert client._recv()["reason"] == "bad-frame"
    assert store.posts == 0  # the smuggled open inside the oversized line was NOT executed
    assert client.open()["admitted"] is True and store.posts == 1


def test_C3_session_prompts_are_size_bounded_like_invoke():
    gateway, store, backend, _ = build()
    s = gateway.open_session(request())
    big = "x" * (256 * 1024 + 1)
    assert gateway.session_turn(s.session, "normal", big, idempotency_key="k").reason == "invalid-turn"
    with pytest.raises(StopBoundary, match="invalid-turn"):
        next(gateway.session_stream(s.session, big, idempotency_key="k2"))
    assert backend.calls == []


# ----------------------------------------------------- T13 QA review: supervisor hardening
@pytest.mark.parametrize("variable", [
    "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PATH", "AWS_SECRET_ACCESS_KEY",
])
def test_supervisor_rejects_untrusted_worker_environment(monkeypatch, variable):
    import sys
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    monkeypatch.setattr(supervisor, "_PRIVILEGED", True)  # tests rejection; does not prove isolation
    with pytest.raises(supervisor.IsolationUnavailable, match="worker-env-not-allowlisted"):
        supervisor.spawn_isolated_worker(
            [sys.executable, "-c", "pass"],
            env={variable: "/tmp/sentinel"},
            allocator=supervisor.InProcessUidAllocator(3_800_000_000, 1),
        )


def test_supervisor_allows_only_an_inherited_gateway_fd_in_worker_environment(monkeypatch):
    import os
    import secrets
    import sys
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    monkeypatch.setattr(supervisor, "_PRIVILEGED", True)
    read_fd, write_fd = os.pipe()
    uid = 3_800_000_000 + secrets.randbelow(10_000_000)
    captured = {}

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        raise OSError("intercept before process launch")

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    try:
        with pytest.raises(supervisor.IsolationUnavailable, match="worker-env-invalid-gateway-fd"):
            supervisor.spawn_isolated_worker(
                [sys.executable], env={"AOS_GATEWAY_FD": "1234567891"},
                pass_fds=(write_fd,), allocator=supervisor.InProcessUidAllocator(uid, 1),
            )
        with pytest.raises(OSError, match="intercept before process launch"):
            supervisor.spawn_isolated_worker(
                [sys.executable], env={"AOS_GATEWAY_FD": str(write_fd)},
                pass_fds=(write_fd,), allocator=supervisor.InProcessUidAllocator(uid, 1),
            )
        assert captured["env"] == {"PATH": "/usr/bin:/bin", "AOS_GATEWAY_FD": str(write_fd)}
        supervisor.claim_uid(uid).release()  # rejected Popen released the claim
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("failure", [OSError("readiness poll failed"), KeyboardInterrupt()])
def test_supervisor_post_spawn_failure_kills_reaps_and_releases_uid(monkeypatch, tmp_path, failure):
    import os
    import secrets
    import signal
    import subprocess
    import sys
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    # Substitute a harmless sleeper for the privileged launcher. This checks
    # failure cleanup independently of whether CI can isolate a real worker.
    launcher = tmp_path / "sleep_launcher.py"
    launcher.write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(supervisor, "_LAUNCHER", str(launcher))
    monkeypatch.setattr(supervisor, "_PRIVILEGED", True)
    uid = 3_810_000_000 + secrets.randbelow(10_000_000)
    children = []
    original_popen = subprocess.Popen

    def record_popen(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    def failing_select(*args, **kwargs):
        raise failure

    monkeypatch.setattr(supervisor.subprocess, "Popen", record_popen)
    monkeypatch.setattr(supervisor.select, "select", failing_select)
    try:
        with pytest.raises(type(failure)):
            supervisor.spawn_isolated_worker(
                [sys.executable], allocator=supervisor.InProcessUidAllocator(uid, 1),
            )
        assert len(children) == 1
        assert children[0].poll() is not None
        assert children[0].returncode == -signal.SIGKILL
        supervisor.claim_uid(uid).release()
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


def test_supervisor_missing_readiness_kills_and_reaps_child(monkeypatch, tmp_path):
    import os
    import secrets
    import signal
    import subprocess
    import sys
    from agent_os_execution_service.ckr6_model_gateway import supervisor
    launcher = tmp_path / "sleep_launcher.py"
    launcher.write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setattr(supervisor, "_LAUNCHER", str(launcher))
    monkeypatch.setattr(supervisor, "_PRIVILEGED", True)
    monkeypatch.setattr(supervisor, "_READY_TIMEOUT_SECONDS", 0.1)
    uid = 3_820_000_000 + secrets.randbelow(10_000_000)
    children = []
    original_popen = subprocess.Popen

    def record_popen(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(supervisor.subprocess, "Popen", record_popen)
    try:
        with pytest.raises(supervisor.IsolationUnavailable, match="host-cannot-isolate-worker"):
            supervisor.spawn_isolated_worker(
                [sys.executable], allocator=supervisor.InProcessUidAllocator(uid, 1),
            )
        assert children and children[0].poll() is not None
        supervisor.claim_uid(uid).release()
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
