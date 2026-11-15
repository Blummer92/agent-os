"""Trusted-host adapter tests (local candidate; NOT wired to any production host entrypoint).

Real: pathway, registries (04_Registry), CKR6 preflight, router, admission/composition,
authorization reacquisition over an in-memory transport, journal and receipt files.
Doubles (named): ScenarioGitRunner, runtime outcome built via real adapters, in-memory
authorization transport, routing-evidence provider returning fixed ids.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_ai_navigation_pathway as base
from test_ai_navigation_pathway import (  # noqa: F401
    _CAND, _INV, _Transport, _clock, _host, _payload, _record, REPOSITORY_ROOT, ROUTING, nav, tec,
)
from agent_os_execution_service import ai_navigation_trusted_host as th
from agent_os_execution_service.ai_navigation_pathway import FileReceiptSink, NavigationRoutingEvidence
from agent_os_execution_service.ai_navigation_trusted_host import (
    DispatchJournal, TrustedHostComposition, reconcile_navigation_receipt, run_trusted_host_navigation,
)

REG = REPOSITORY_ROOT / "04_Registry"
CAPS = REG / "reusable-capabilities.yml"


def _comp(tmp_path, monkeypatch, *, transport=None, routing=lambda r, p: ROUTING, host=True, sink=None,
          registry_dir=REG, caps=CAPS, payload_parts=None, **kw):
    payload, request, plan = payload_parts or _payload()
    transport = transport if transport is not None else _Transport([_record(request, plan)])
    comp = TrustedHostComposition(
        clock=_clock, transport=transport, candidate_packet_id=_CAND, invocation_id=_INV,
        operation="validation-only", host=_host(tmp_path, monkeypatch) if host else None,
        routing_evidence_provider=routing, registry_dir=registry_dir, capability_registry_path=caps,
        receipt_sink=sink or FileReceiptSink(tmp_path / "receipts" / "nav.jsonl"),
        journal=DispatchJournal(tmp_path / "journal"), **kw)
    return payload, comp


def _no_routing_key(payload):
    payload = dict(payload)
    payload.pop("routing_evidence", None)
    return payload


def _parts():
    payload, request, plan = _payload()
    return _no_routing_key(payload), request, plan


def test_trusted_host_completes_once_and_journals(tmp_path, monkeypatch):
    parts = _parts()
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=parts)
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "completed" and out["receipt_persisted"] and out["execution_attempted"]
    rec = comp.journal.read(out["journal_key"])
    assert rec["state"] == "completed-receipt-persisted"
    assert out["merge_authorized"] is False and out["lesson_candidate_authorized"] is False


def test_exactly_once_second_call_refused_without_dispatch(tmp_path, monkeypatch):
    parts = _parts()
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=parts)
    assert run_trusted_host_navigation(payload, comp)["status"] == "completed"
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    again = run_trusted_host_navigation(payload, comp)
    assert again["status"] == "request-rejected" and "dispatch-already-recorded" in again["reason_codes"]
    assert calls == [] and again["execution_attempted"] is False


@pytest.mark.parametrize("key", ["routing_evidence", "authorization", "host", "evaluated_at", "receipt_sink", "git_runner"])
def test_payload_cannot_carry_trusted_inputs(tmp_path, monkeypatch, key):
    payload, request, plan = _payload()
    payload = dict(payload); payload[key] = {"x": 1}
    _, comp = _comp(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "request-rejected" and out["failure_class"] == "policy-denial" and calls == []


@pytest.mark.parametrize("change", [dict(execution_authorized=False), dict(expires_at="2026-07-29T15:00:01Z"),
                                    dict(authorized_invocation_id="invocation-other"), dict(expected_sha="e" * 40)])
def test_revoked_expired_mismatched_owner_record(tmp_path, monkeypatch, change):
    parts = _parts()
    _, request, plan = parts
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=parts, transport=_Transport([_record(request, plan, **change)]))
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "approval-required" and out["execution_attempted"] is False
    assert not list((tmp_path / "journal").glob("nav-dispatch-*"))


def test_authorization_outage_is_infrastructure(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), transport=_Transport(fail=True))
    out = run_trusted_host_navigation(payload, comp)
    assert out["failure_class"] == "infrastructure-unavailable" and out["execution_attempted"] is False


def test_missing_routing_evidence_refused_not_fabricated(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), routing=lambda r, p: None)
    out = run_trusted_host_navigation(payload, comp)
    assert out["reason_codes"] == ["routing-evidence-not-produced"] and out["execution_attempted"] is False


def test_partial_routing_identities_refused_by_router_path(tmp_path, monkeypatch):
    partial = NavigationRoutingEvidence(operating_mode_decision_id="operating-mode:t1")
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), routing=lambda r, p: partial)
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] != "completed" and out["execution_attempted"] is False


def test_routing_provider_outage_is_infrastructure(tmp_path, monkeypatch):
    def boom(r, p):
        raise ConnectionError("producer down")
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), routing=boom)
    out = run_trusted_host_navigation(payload, comp)
    assert out["failure_class"] == "infrastructure-unavailable" and out["execution_attempted"] is False


def test_ckr6_read_unavailable_blocks_when_knowledge_material(tmp_path, monkeypatch):
    payload, request, plan = _parts()
    payload = dict(payload); payload["specialized_knowledge_required"] = True
    seen = []

    def down(_):
        seen.append(1)
        raise ConnectionError("notion down")
    p, comp = _comp(tmp_path, monkeypatch, payload_parts=(payload, request, plan), execute_read=down)
    out = run_trusted_host_navigation(p, comp)
    assert seen, "host-owned CKR6 read transport must be the one used"
    assert out["status"] != "completed" and out["execution_attempted"] is False
    assert out["lesson_retrieval_status"] not in (None, "not-needed")


def test_invalid_capability(tmp_path, monkeypatch):
    payload, request, plan = _parts()
    payload = dict(payload); payload["capability_id"] = "no-such-capability"
    p, comp = _comp(tmp_path, monkeypatch, payload_parts=(payload, request, plan))
    out = run_trusted_host_navigation(p, comp)
    assert out["status"] == "invalid-capability" and out["execution_attempted"] is False


def test_registry_distribution_absent_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(th.importlib.util, "find_spec", lambda name: None)
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    out = run_trusted_host_navigation(payload, comp)
    assert "capability-registry-distribution-unavailable" in out["reason_codes"]
    assert out["failure_class"] == "infrastructure-unavailable" and out["execution_attempted"] is False


def test_registry_locations_missing_fail_closed(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), registry_dir=tmp_path / "nope",
                          caps=tmp_path / "nope.yml")
    out = run_trusted_host_navigation(payload, comp)
    assert any(r.startswith("agent-registry-data-unavailable") for r in out["reason_codes"])
    assert "capability-registry-data-unavailable" in out["reason_codes"] and out["execution_attempted"] is False


def test_runtime_host_down(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), host=False)
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "host-unavailable" and out["execution_attempted"] is False
    assert not list((tmp_path / "journal").glob("nav-dispatch-*"))


def test_failed_command_journaled_and_not_replayed(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    comp = TrustedHostComposition(**{**{f: getattr(comp, f) for f in comp.__slots__}, "host": _host(tmp_path, monkeypatch, passing=False)})
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "execution-failed" and out["execution_attempted"]
    assert comp.journal.read(out["journal_key"])["state"] == "dispatched-not-completed"
    assert run_trusted_host_navigation(payload, comp)["reason_codes"][0] == "dispatch-already-recorded"


def test_intent_journal_unavailable_means_no_dispatch(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    monkeypatch.setattr(DispatchJournal, "create_intent", lambda self, k, r: (_ for _ in ()).throw(OSError("ro fs")))
    out = run_trusted_host_navigation(payload, comp)
    assert "dispatch-intent-record-unavailable" in out["reason_codes"] and calls == [] and not out["execution_attempted"]


def _flaky_sink(path):
    state = {"fail": True}
    real = FileReceiptSink(path)
    def sink(jsonl):
        if state["fail"]:
            raise OSError("disk full")
        real(jsonl)
    return sink, state


def test_receipt_failure_after_dispatch_recovers_without_replay(tmp_path, monkeypatch):
    sink, state = _flaky_sink(tmp_path / "receipts" / "nav.jsonl")
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), sink=sink)
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "receipt-persistence-failed" and out["execution_attempted"]
    key = out["journal_key"]
    assert comp.journal.read(key)["state"] == "dispatched-receipt-failed"
    # naive replay is refused
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    assert run_trusted_host_navigation(payload, comp)["reason_codes"][0] == "dispatch-already-recorded"
    # reconciliation while sink still down: blocked, record kept
    blocked = reconcile_navigation_receipt(comp, key)
    assert blocked.action == "blocked" and comp.journal.read(key)["state"] == "dispatched-receipt-failed"
    state["fail"] = False
    done = reconcile_navigation_receipt(comp, key)
    assert done.action == "re-persisted" and done.replay_attempted is False and calls == []
    from agent_os_execution_service.evidence_ledger import EvidenceLedger
    ledger = EvidenceLedger.from_jsonl((tmp_path / "receipts" / "nav.jsonl").read_text())  # chain verifies
    assert ledger.entries[-1].decision_type.value == "completion"
    assert comp.journal.read(key)["state"] == "reconciled"
    assert reconcile_navigation_receipt(comp, key).action == "already-persisted"


def test_crash_between_intent_and_outcome_needs_manual_review_never_replay(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    request = _parts()[1]
    plan_id = nav.validation_command_plan_id(_parts()[2])
    key = DispatchJournal.key(request, plan_id)
    comp.journal.create_intent(key, {"state": "dispatching"})
    assert reconcile_navigation_receipt(comp, key).action == "manual-review-required"
    out = run_trusted_host_navigation(payload, comp)
    assert out["reason_codes"][0] == "dispatch-already-recorded" and not out["execution_attempted"]


def test_reconcile_unknown_key(tmp_path, monkeypatch):
    _, comp = _comp(tmp_path, monkeypatch)
    assert reconcile_navigation_receipt(comp, "0" * 40).action == "no-record"


def test_module_boundaries_no_lesson_write_or_network_imports():
    import ast
    src = Path(th.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    roots = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            roots |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            roots.add(n.module.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.level:
            assert not any(x in (n.module or "") for x in ("lesson", "ckr7", "refinement", "notion", "publication", "github"))
    assert not roots & {"github", "requests", "httpx", "socket", "subprocess", "scripts", "workflow_scheduler"}


def test_intent_create_is_exclusive(tmp_path):
    j = DispatchJournal(tmp_path / "j")
    j.create_intent("k", {"state": "dispatching"})
    with pytest.raises(FileExistsError):
        j.create_intent("k", {"state": "dispatching"})


# ---- recovery hardening: adversarial corruption, cross-binding, concurrency, intent race ----
import json as _json
import threading as _threading


def _failed_run(tmp_path, monkeypatch):
    sink, state = _flaky_sink(tmp_path / "receipts" / "nav.jsonl")
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts(), sink=sink)
    out = run_trusted_host_navigation(payload, comp)
    assert out["status"] == "receipt-persistence-failed"
    state["fail"] = False
    return payload, comp, out["journal_key"], state


def _tamper(comp, key, **changes):
    record = comp.journal.read(key)
    record.update(changes)
    comp.journal.write(key, record)


def _no_sink_write(tmp_path):
    return not (tmp_path / "receipts" / "nav.jsonl").exists()


def test_recovery_records_binding_fields(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    record = comp.journal.read(key)
    for field in ("retained_ledger_sha256", "retained_ledger_head_digest", "request_fingerprint", "command_plan_id"):
        assert record[field]


@pytest.mark.parametrize("mutate,reason", [
    (lambda r: {"retained_ledger_jsonl": r["retained_ledger_jsonl"].replace("completion", "completiom", 1)}, "retained-ledger-sha256-mismatch"),
    (lambda r: {"retained_ledger_jsonl": "not json\n"}, "retained-ledger-sha256-mismatch"),
    (lambda r: {"retained_ledger_head_digest": "0" * 64}, "retained-ledger-head-digest-mismatch"),
    (lambda r: {"request_fingerprint": "f" * 64}, "journal-key-binding-mismatch"),
    (lambda r: {"command_plan_id": "other-plan"}, "journal-key-binding-mismatch"),
    (lambda r: {"retained_ledger_jsonl": None}, "no-retained-receipt"),
])
def test_reconcile_refuses_tampered_record(tmp_path, monkeypatch, mutate, reason):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    _tamper(comp, key, **mutate(comp.journal.read(key)))
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "blocked" and reason in res.reason_codes and res.replay_attempted is False
    assert _no_sink_write(tmp_path) and comp.journal.read(key)["state"] == "dispatched-receipt-failed"


def test_reconcile_refuses_internally_consistent_but_broken_chain(tmp_path, monkeypatch):
    import hashlib
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    lines = comp.journal.read(key)["retained_ledger_jsonl"].splitlines()
    first = _json.loads(lines[0])
    first["rationale"] = "forged" if "rationale" in first else first.get("rationale")
    first["entry_digest"] = "1" * 64  # chain no longer verifies, sha/head recomputed to look consistent
    forged = "\n".join([_json.dumps(first, sort_keys=True)] + lines[1:]) + "\n"
    _tamper(comp, key, retained_ledger_jsonl=forged, retained_ledger_sha256=hashlib.sha256(forged.encode()).hexdigest())
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "blocked" and "retained-ledger-chain-invalid" in res.reason_codes and _no_sink_write(tmp_path)


def test_reconcile_refuses_ledger_from_another_request(tmp_path, monkeypatch):
    import hashlib
    from agent_os_execution_service.evidence_ledger import EvidenceLedger
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    record = comp.journal.read(key)
    other = record["retained_ledger_jsonl"].replace(record["request_fingerprint"], "e" * len(record["request_fingerprint"]))
    # a ledger whose content was swapped from a different request cannot pass: either the chain breaks or the request binding fails
    _tamper(comp, key, retained_ledger_jsonl=other, retained_ledger_sha256=hashlib.sha256(other.encode()).hexdigest())
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "blocked" and _no_sink_write(tmp_path)


def test_reconcile_refuses_record_bound_to_other_key(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    comp.journal.write("a" * 40, comp.journal.read(key))  # record copied under a different key
    res = reconcile_navigation_receipt(comp, "a" * 40)
    assert res.action == "blocked" and "journal-key-binding-mismatch" in res.reason_codes and _no_sink_write(tmp_path)


def test_concurrent_reconcile_writes_sink_exactly_once(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    writes, gate = [], _threading.Barrier(6)
    real = comp.receipt_sink

    def slow_sink(jsonl):
        writes.append(1)
        import time; time.sleep(0.05)
        real(jsonl)
    object.__setattr__(comp, "receipt_sink", slow_sink)
    results = []

    def go():
        gate.wait()
        results.append(reconcile_navigation_receipt(comp, key).action)
    threads = [_threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert len(writes) == 1 and results.count("re-persisted") == 1
    assert set(results) <= {"re-persisted", "blocked", "already-persisted"}
    assert comp.journal.read(key)["state"] == "reconciled"
    assert not list((tmp_path / "journal").glob("*.lock"))


def test_stale_reconcile_lock_blocks_rather_than_double_writes(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    comp.journal.acquire_lock(key)
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "blocked" and "reconcile-in-progress-or-stale-lock" in res.reason_codes and _no_sink_write(tmp_path)


def test_reconcile_after_journal_update_failure_is_reported_not_replayed(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    real_write = DispatchJournal.write
    monkeypatch.setattr(DispatchJournal, "write", lambda self, k, r: (_ for _ in ()).throw(OSError("ro")))
    res = reconcile_navigation_receipt(comp, key)
    monkeypatch.setattr(DispatchJournal, "write", real_write)
    assert res.action == "blocked" and "journal-update-failed-receipt-written" in res.reason_codes
    assert res.replay_attempted is False


def test_intent_race_loser_gets_clean_policy_refusal_without_dispatch(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    real_read = DispatchJournal.read
    state = {"first": True}

    def racing_read(self, key):  # preflight sees nothing, then a competitor wins the exclusive create
        if state["first"]:
            state["first"] = False
            self.create_intent(key, {"state": "dispatching"})
            return None
        return real_read(self, key)
    monkeypatch.setattr(DispatchJournal, "read", racing_read)
    out = run_trusted_host_navigation(payload, comp)
    assert out["reason_codes"][0] == "dispatch-already-recorded"
    assert out["failure_class"] != "infrastructure-unavailable" and calls == [] and not out["execution_attempted"]


def _rebuild(jsonl, *, keep=None, swap=None):
    import hashlib
    from agent_os_execution_service.evidence_ledger import EvidenceLedger
    source = EvidenceLedger.from_jsonl(jsonl)
    ledger = EvidenceLedger()
    for entry in source.entries[:keep]:
        refs = tuple(sorted(swap(r) for r in entry.provenance_refs)) if swap else entry.provenance_refs
        ledger = ledger.append(
            mission_id=entry.mission_id, decision_type=entry.decision_type, inputs_digest=entry.inputs_digest,
            reason_codes=entry.reason_codes, provenance_refs=refs, recorded_at=entry.recorded_at,
            actor=entry.actor, decision_label=entry.decision_label)
    text = ledger.to_jsonl()
    return {"retained_ledger_jsonl": text, "retained_ledger_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "retained_ledger_head_digest": ledger.entries[-1].entry_digest}


def test_reconcile_refuses_valid_chain_for_a_different_request(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    record = comp.journal.read(key)
    fp = record["request_fingerprint"]
    _tamper(comp, key, **_rebuild(record["retained_ledger_jsonl"], swap=lambda r: r.replace(fp, "9" * len(fp))))
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "blocked" and "retained-ledger-request-binding-mismatch" in res.reason_codes and _no_sink_write(tmp_path)


def test_reconcile_refuses_valid_chain_that_is_not_a_completion(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    _tamper(comp, key, **_rebuild(comp.journal.read(key)["retained_ledger_jsonl"], keep=1))
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "blocked" and "retained-ledger-not-a-completion" in res.reason_codes and _no_sink_write(tmp_path)


def test_reconcile_rereads_state_under_the_lock(tmp_path, monkeypatch):
    _, comp, key, _ = _failed_run(tmp_path, monkeypatch)
    real_acquire = DispatchJournal.acquire_lock

    def competitor_finishes_first(self, k):
        real_acquire(self, k)
        record = self.read(k)
        record["state"] = "reconciled"
        self.write(k, record)  # another reconcile completed between our read and our lock
    monkeypatch.setattr(DispatchJournal, "acquire_lock", competitor_finishes_first)
    res = reconcile_navigation_receipt(comp, key)
    assert res.action == "already-persisted" and _no_sink_write(tmp_path)
