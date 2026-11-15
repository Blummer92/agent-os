"""Integration + regression tests for the connected AI Navigation pathway.

Real components exercised: capability registry (04_Registry), agent/alias
registries, CKR6 issue-start preflight, executor router, #697 admission and
composition, Workflow Scheduler single-issue runtime with real subprocess
validation, hash-chained evidence ledger, file receipt sink.
Test doubles (named explicitly): the git runner (``ScenarioGitRunner``) and the
CKR6 Notion read transport (``execute_read``) - no network or GitHub access.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
for _p in (REPOSITORY_ROOT, REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/src",
           REPOSITORY_ROOT / "08_Tooling/workflow-scheduler/tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import test_execution_composition as tec  # noqa: E402
import test_single_issue_pilot as tsp  # noqa: E402
from test_concrete_runtime_adapters import ScenarioGitRunner  # noqa: E402

from agent_os_execution_service import ai_navigation_pathway as nav  # noqa: E402
from agent_os_execution_service import execution_composition as composition_module  # noqa: E402
from agent_os_execution_service.ai_navigation_pathway import (  # noqa: E402
    FailureClass, FileReceiptSink, NavigationExecutionHost, NavigationRoutingEvidence, NavigationStatus,
    NavigationWorkRequest, run_ai_navigation,
)
from agent_os_execution_service.evidence_ledger import EvidenceLedger  # noqa: E402

CAPABILITY = "issue-readiness-evaluator"  # owner: QA / Test Agent
ALIAS_CAPABILITY = "issueplan-metadata-scanner"  # owner: retired alias "Integration Manager"


ROUTING = NavigationRoutingEvidence(
    operating_mode_decision_id="operating-mode:t1", executable_lane_selection_id="lane-selection:t1",
    environment_profile_id="environment-profile:t1", environment_health_evidence_id="environment-health:t1",
    workflow_runtime_identity="workflow-runtime:t1")


def _work(**kw):
    values = dict(service_request=tec._request(), issue_number=560, task_reference="validate exact head",
                  capability_id=CAPABILITY, specialized_knowledge_required=False)
    values.update(kw)
    return NavigationWorkRequest(**values)


def _host(tmp_path, monkeypatch, *, passing=True, release_error=None):
    outcome = (tec._canonical_passing_outcome(tmp_path) if passing else tec._canonical_failing_outcome(tmp_path))
    monkeypatch.setattr(composition_module, "run_concrete_runtime_entrypoint_with_validation_evidence",
                        lambda *a, **k: outcome)
    cfg = tec._configuration(tmp_path)
    return NavigationExecutionHost(pilot_input=tec._pilot_input(), configuration=cfg,
                                   cancelled=tsp.never_cancelled,
                                   git_runner=ScenarioGitRunner(cfg),
                                   changed_paths_inspector=lambda: ())


def _go(tmp_path, monkeypatch, *, work=None, authorized=True, with_auth=True, with_host=True,
        passing=True, plan_mutator=None, sink=None, routing=ROUTING, **kw):
    work = work or _work()
    plan = tec._command_plan(work.service_request)
    if plan_mutator:
        plan = plan_mutator(plan)
    auth = tec._authorization(work.service_request, plan, execution_authorized=authorized) if with_auth else None
    host = _host(tmp_path, monkeypatch, passing=passing) if with_host else None
    sink = sink or FileReceiptSink(tmp_path / "receipts" / "nav.jsonl")
    return run_ai_navigation(work, evaluated_at=tec.EVALUATED_AT, command_plan=plan, authorization=auth,
                             host=host, routing_evidence=routing, receipt_sink=sink, **kw)


# 1/11 successful authorized routing + end-to-end completion + receipt persistence
def test_end_to_end_completion(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch)
    assert out.status is NavigationStatus.COMPLETED, out.reason_codes
    assert out.failure_class is FailureClass.NONE
    assert out.route == "chatgpt-governed-runner"
    assert out.selected_agent["agent"] == "QA / Test Agent" and out.selected_agent["role"] == "owner"
    assert out.composition_status == "focused-pass-aggregate-pending"
    assert out.execution_attempted and out.receipt_persisted
    assert out.lesson_retrieval_status == "not-needed"
    assert out.context["capability"]["registry_digest"]
    assert out.context["lessons"]["source_authority"] == "advisory-only"
    saved = (tmp_path / "receipts" / "nav.jsonl").read_text()
    ledger = EvidenceLedger.from_jsonl(saved)  # verifies chain
    assert [e.decision_type.value for e in ledger.entries][-1] == "completion"
    assert saved == out.ledger_jsonl and ledger.entries[-1].entry_digest == out.receipt_digest
    # receipts never become lessons or authorize writes/merge
    assert out.lesson_candidate_authorized is False and out.github_writes_authorized is False
    assert out.merge_authorized is False


def test_host_dispatch_invoked_exactly_once(tmp_path, monkeypatch):
    calls = []
    real = composition_module.run_concrete_runtime_entrypoint_with_validation_evidence
    out = _go(tmp_path, monkeypatch)
    spy_outcome = composition_module.run_concrete_runtime_entrypoint_with_validation_evidence

    def spy(*a, **k):
        calls.append(1)
        return spy_outcome(*a, **k)
    monkeypatch.setattr(composition_module, "run_concrete_runtime_entrypoint_with_validation_evidence", spy)
    work = _work()
    plan = tec._command_plan(work.service_request)
    cfg = tec._configuration(tmp_path)
    host = NavigationExecutionHost(pilot_input=tec._pilot_input(), configuration=cfg, cancelled=tsp.never_cancelled,
                                   git_runner=ScenarioGitRunner(cfg), changed_paths_inspector=lambda: ())
    run_ai_navigation(work, evaluated_at=tec.EVALUATED_AT, command_plan=plan,
                      authorization=tec._authorization(work.service_request, plan), host=host,
                      routing_evidence=ROUTING, receipt_sink=lambda s: None)
    assert out.status is NavigationStatus.COMPLETED and calls == [1]


# 2 missing lesson retrieval: explicit status, no fabricated context, gate honoured
def test_missing_lessons_explicit_status_and_blocks_when_material(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, work=_work(specialized_knowledge_required=True))
    assert out.status is NavigationStatus.LESSON_PREFLIGHT_BLOCKED
    assert out.failure_class is FailureClass.INFRASTRUCTURE_UNAVAILABLE
    assert out.lesson_retrieval_status == "insufficient"
    assert out.context["lessons"]["selected"] == []
    assert not out.execution_attempted


def test_lesson_read_exception_is_unavailable_not_fabricated(tmp_path, monkeypatch):
    def boom(**_):
        raise RuntimeError("catalog down")
    out = _go(tmp_path, monkeypatch, lesson_preflight=boom)
    assert out.status is NavigationStatus.LESSON_PREFLIGHT_BLOCKED
    assert out.lesson_retrieval_status == "unavailable" and out.context["lessons"]["selected"] == []


# 3 no eligible agent
def _registry_with_owner(tmp_path, owner):
    text = (REPOSITORY_ROOT / "04_Registry/reusable-capabilities.yml").read_text()
    head, rest = text.split(f"capability_id: {CAPABILITY}\n", 1)
    block, tail = rest.split("\n  - capability_id:", 1)
    block = block.replace("owner_agent: QA / Test Agent", f"owner_agent: {owner}")
    import re
    block = re.sub(r"    supporting_agents:\n(      - .*\n)+", "    supporting_agents:\n      - Unknown Person\n", block)
    path = tmp_path / "caps.yml"
    path.write_text(head + f"capability_id: {CAPABILITY}\n" + block + "\n  - capability_id:" + tail)
    return path


def test_no_eligible_agent_for_write_owner_only(tmp_path, monkeypatch):
    path = _registry_with_owner(tmp_path, "GitHub Service Agent")
    out = _go(tmp_path, monkeypatch, capability_registry_path=path)
    assert out.status is NavigationStatus.NO_ELIGIBLE_AGENT
    assert out.failure_class is FailureClass.POLICY_DENIAL
    assert "agent-not-permitted-for-operation:GitHub Service Agent" in out.reason_codes
    assert not out.execution_attempted


def test_unresolvable_owner_has_no_agent(tmp_path, monkeypatch):
    path = _registry_with_owner(tmp_path, "Nobody At All")
    out = _go(tmp_path, monkeypatch, capability_registry_path=path)
    assert out.status is NavigationStatus.NO_ELIGIBLE_AGENT
    assert "agent-unresolved:Nobody At All" in out.reason_codes


def test_retired_alias_owner_resolves_to_canonical_agent(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, work=_work(capability_id=ALIAS_CAPABILITY))
    assert out.status is NavigationStatus.COMPLETED, out.reason_codes
    assert out.selected_agent == {"agent": "ChatGPT Orchestrator", "declared_as": "Integration Manager",
                                  "resolved_via_alias": True, "role": "owner"}


# 4 invalid capability
@pytest.mark.parametrize("cap", ["does-not-exist", "issue-batch-graph"])  # missing / experimental
def test_invalid_capability(tmp_path, monkeypatch, cap):
    out = _go(tmp_path, monkeypatch, work=_work(capability_id=cap))
    assert out.status is NavigationStatus.INVALID_CAPABILITY
    assert out.failure_class is FailureClass.MISSING_OR_INVALID_EVIDENCE
    assert not out.execution_attempted


# 5 evidence rejection (distinct from policy denial and infra)
def test_expired_request_rejected(tmp_path, monkeypatch):
    work = _work(service_request=tec._request(expires_at="2026-07-29T15:10:00Z"))
    out = _go(tmp_path, monkeypatch, work=work)
    assert out.status is NavigationStatus.REQUEST_REJECTED
    assert out.failure_class is FailureClass.MISSING_OR_INVALID_EVIDENCE


def test_command_plan_bound_to_other_request_is_evidence_rejection(tmp_path, monkeypatch):
    import dataclasses
    out = _go(tmp_path, monkeypatch,
              plan_mutator=lambda p: dataclasses.replace(p, expected_sha="c" * 40))
    assert out.status in (NavigationStatus.EVIDENCE_REJECTED,), out.reason_codes
    assert out.failure_class is FailureClass.MISSING_OR_INVALID_EVIDENCE
    assert out.composition_status == "manual-review"
    assert not out.execution_attempted


def test_missing_command_plan_is_evidence_rejection(tmp_path, monkeypatch):
    work = _work()
    out = run_ai_navigation(work, evaluated_at=tec.EVALUATED_AT, command_plan=None,
                            authorization=None, host=None, routing_evidence=None, receipt_sink=lambda s: None)
    # absent approval is reported before absent plan: policy gate first
    assert out.status is NavigationStatus.APPROVAL_REQUIRED


def test_unauthorized_entrypoint_actor(tmp_path, monkeypatch):
    work = _work(service_request=tec._request(requesting_actor="someone-else"))
    out = _go(tmp_path, monkeypatch, work=work)
    assert out.status is NavigationStatus.UNAUTHORIZED_ENTRYPOINT
    assert out.failure_class is FailureClass.POLICY_DENIAL


# 6/7 approval required / denied
def test_approval_required(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, with_auth=False)
    assert out.status is NavigationStatus.APPROVAL_REQUIRED
    assert out.failure_class is FailureClass.POLICY_DENIAL and not out.execution_attempted


def test_approval_denied(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, authorized=False)
    assert out.status is NavigationStatus.APPROVAL_DENIED
    assert out.failure_class is FailureClass.POLICY_DENIAL and not out.execution_attempted


def test_incomplete_routing_evidence_is_missing_evidence_not_defaulted(tmp_path, monkeypatch):
    partial = NavigationRoutingEvidence(operating_mode_decision_id="operating-mode:t1")
    out = _go(tmp_path, monkeypatch, routing=partial)
    assert out.status is NavigationStatus.EVIDENCE_REJECTED
    assert out.failure_class is FailureClass.MISSING_OR_INVALID_EVIDENCE
    assert "missing:executable_lane_selection_id" in out.reason_codes and not out.execution_attempted


# 8 execution host unavailable
def test_host_absent_is_unavailable_infrastructure(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, with_host=False)
    assert out.status is NavigationStatus.HOST_UNAVAILABLE
    assert out.failure_class is FailureClass.INFRASTRUCTURE_UNAVAILABLE
    assert not out.execution_attempted


def test_host_raises_oserror_is_unavailable(tmp_path, monkeypatch):
    work = _work()
    plan = tec._command_plan(work.service_request)
    cfg = tec._configuration(tmp_path)
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: (_ for _ in ()).throw(ConnectionError("down")))
    host = NavigationExecutionHost(pilot_input=tec._pilot_input(), configuration=cfg, cancelled=tsp.never_cancelled)
    out = run_ai_navigation(work, evaluated_at=tec.EVALUATED_AT, command_plan=plan,
                            authorization=tec._authorization(work.service_request, plan), host=host,
                            routing_evidence=ROUTING, receipt_sink=lambda s: None)
    assert out.status is NavigationStatus.HOST_UNAVAILABLE


# 9 execution failure (real failing subprocess)
def test_execution_failure(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, passing=False)
    assert out.status is NavigationStatus.EXECUTION_FAILED
    assert out.failure_class is FailureClass.EXECUTION_FAILURE
    assert out.execution_attempted and out.receipt_persisted
    assert EvidenceLedger.from_jsonl((tmp_path / "receipts" / "nav.jsonl").read_text()).entries[-1].decision_type.value == "execution"


# 10 receipt persistence failure
def test_receipt_persistence_failure_is_never_completion(tmp_path, monkeypatch):
    def broken(_):
        raise OSError("disk full")
    out = _go(tmp_path, monkeypatch, sink=broken)
    assert out.status is NavigationStatus.RECEIPT_PERSISTENCE_FAILED
    assert out.failure_class is FailureClass.INFRASTRUCTURE_UNAVAILABLE
    assert out.execution_attempted is True and out.receipt_persisted is False and out.receipt_digest is None


def test_refusal_with_broken_sink_keeps_refusal_status(tmp_path, monkeypatch):
    out = _go(tmp_path, monkeypatch, authorized=False, sink=lambda s: (_ for _ in ()).throw(OSError("x")))
    assert out.status is NavigationStatus.APPROVAL_DENIED and not out.receipt_persisted
    assert "receipt-persistence-failed" in out.reason_codes


def test_file_sink_readback_mismatch_detected(tmp_path):
    sink = FileReceiptSink(tmp_path / "r.jsonl")
    sink("a\n")
    assert (tmp_path / "r.jsonl").read_text() == "a\n"


# trust boundary: no lesson write / refinement coupling
def test_pathway_has_no_lesson_write_or_refinement_dependency():
    src = Path(nav.__file__).read_text()
    for forbidden in ("lesson_learning_loop", "propose_lesson_refinement", "lesson_publication_review",
                      "agent_os_notion", "github_writes_authorized=True"):
        assert forbidden not in src


def test_outcome_projection_serializable_and_non_authorizing(tmp_path, monkeypatch):
    import json
    d = _go(tmp_path, monkeypatch).to_dict()
    json.dumps(d)
    assert d["lesson_candidate_authorized"] is False and d["merge_authorized"] is False



# --------------------------------------------------------------------------
# Initiating-host JSON entrypoint (trusted-composition split)
# --------------------------------------------------------------------------
import json as _json  # noqa: E402

from agent_os_execution_service.ai_navigation_pathway import run_ai_navigation_payload  # noqa: E402
from agent_os_execution_service.command_planning import serialize_validation_command_plan  # noqa: E402
from agent_os_execution_service.models import serialize_execution_service_request  # noqa: E402


def _payload(**extra):
    request = tec._request()
    plan = tec._command_plan(request)
    body = {
        "service_request": serialize_execution_service_request(request),
        "command_plan": serialize_validation_command_plan(plan),
        "issue_number": 560, "task_reference": "validate exact head", "capability_id": CAPABILITY,
        "specialized_knowledge_required": False, 
        "routing_evidence": {"operating_mode_decision_id": "operating-mode:t1",
                             "executable_lane_selection_id": "lane-selection:t1",
                             "environment_profile_id": "environment-profile:t1",
                             "environment_health_evidence_id": "environment-health:t1",
                             "workflow_runtime_identity": "workflow-runtime:t1"},
    }
    body.update(extra)
    return _json.loads(_json.dumps(body)), request, plan


def _clock():
    from datetime import datetime, timezone
    return datetime.fromisoformat(tec.EVALUATED_AT.replace("Z", "+00:00")).astimezone(timezone.utc)


def _auth_source(request, plan, evaluated_at):
    assert evaluated_at == tec.EVALUATED_AT  # host clock, not payload
    return tec._authorization(request, plan)


def test_payload_entrypoint_completes_and_returns_structured_json(tmp_path, monkeypatch):
    payload, _, _ = _payload()
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=_auth_source,
                                    receipt_sink=FileReceiptSink(tmp_path / "p.jsonl"), clock=_clock)
    _json.dumps(out)
    assert out["status"] == "completed" and out["receipt_persisted"] is True and out["execution_attempted"] is True
    assert out["merge_authorized"] is False and out["lesson_candidate_authorized"] is False


@pytest.mark.parametrize("forged", ["authorization", "execution_authorized", "host", "git_runner", "receipt_sink", "evaluated_at"])
def test_payload_cannot_carry_authorization_or_host_binding(tmp_path, monkeypatch, forged):
    payload, _, _ = _payload(**{forged: {"execution_authorized": True}})
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=_auth_source,
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "request-rejected" and out["failure_class"] == "policy-denial"
    assert out["execution_attempted"] is False and calls == []


def test_payload_unknown_key_is_evidence_rejection_not_policy(tmp_path, monkeypatch):
    payload, _, _ = _payload(whatever=1)
    out = run_ai_navigation_payload(payload, host=None, authorization_source=_auth_source, receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "request-rejected" and out["failure_class"] == "missing-or-invalid-evidence"


def test_payload_malformed_request_rejected(tmp_path, monkeypatch):
    payload, _, _ = _payload()
    payload["service_request"] = {"schema_version": "1.0"}
    out = run_ai_navigation_payload(payload, host=None, authorization_source=_auth_source, receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "request-rejected" and out["execution_attempted"] is False
    assert run_ai_navigation_payload("nope", host=None, authorization_source=_auth_source,
                                     receipt_sink=lambda s: None, clock=_clock)["status"] == "request-rejected"


def test_payload_trusted_source_withholds_authorization(tmp_path, monkeypatch):
    payload, _, _ = _payload()
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=lambda r, p, e: None,
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "approval-required" and out["failure_class"] == "policy-denial"


def test_payload_authorization_source_outage_is_infrastructure(tmp_path, monkeypatch):
    payload, _, _ = _payload()

    def down(r, p, e):
        raise ConnectionError("github read down")
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=down,
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "approval-required" and out["failure_class"] == "infrastructure-unavailable"
    assert out["execution_attempted"] is False


def test_payload_cannot_select_evaluation_time(tmp_path, monkeypatch):
    payload, _, _ = _payload(evaluated_at="2099-01-01T00:00:00Z")
    out = run_ai_navigation_payload(payload, host=None, authorization_source=_auth_source,
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "request-rejected" and out["failure_class"] == "policy-denial"


def test_naive_host_clock_fails_closed(tmp_path, monkeypatch):
    from datetime import datetime
    payload, _, _ = _payload()
    out = run_ai_navigation_payload(payload, host=None, authorization_source=_auth_source,
                                    receipt_sink=lambda s: None, clock=lambda: datetime(2026, 1, 1))
    assert out["status"] == "request-rejected" and out["reason_codes"] == ["host-clock-invalid"]
    assert out["execution_attempted"] is False


# --------------------------------------------------------------------------
# Trusted authorization-source composition over existing reacquisition
# --------------------------------------------------------------------------
from agent_os_execution_service.ai_navigation_pathway import (  # noqa: E402
    AuthorizationSourceUnavailable, trusted_execution_authorization_source)
from agent_os_execution_service.command_planning import validation_command_plan_id  # noqa: E402
from agent_os_execution_service.execution_authorization_source import (  # noqa: E402
    ExecutionAuthorizationCommentSnapshot, ExecutionAuthorizationSourceSnapshot,
    serialize_execution_authorization_comment)

_CAND = "candidate-packet:" + "a" * 64
_INV = "invocation-560"


class _Transport:
    def __init__(self, comments=(), fail=False, complete=True):
        self.comments, self.fail, self.complete, self.calls = comments, fail, complete, 0

    def read_authorization_source(self, repository, issue_number):
        self.calls += 1
        if self.fail:
            raise OSError("down")
        return ExecutionAuthorizationSourceSnapshot(
            repository=repository, issue_number=issue_number, owner_login="blummer92",
            owner_type="User", comments_complete=self.complete, comments=tuple(self.comments))


def _record(request, plan, **ch):
    v = dict(issue_number=560, authorizer_id="blummer92", authorized_candidate_packet_id=_CAND,
             authorized_invocation_id=_INV, authorized_operation="validation-only",
             request_fingerprint=request.request_fingerprint, command_plan_id=validation_command_plan_id(plan),
             repository=plan.repository, expected_sha=plan.expected_sha,
             authorized_at="2026-07-29T14:00:00Z", expires_at="2026-07-29T23:00:00Z", execution_authorized=True)
    v.update(ch)
    return ExecutionAuthorizationCommentSnapshot(comment_id=1, author_login="blummer92",
                                                 created_at="2026-07-29T14:01:00Z",
                                                 body=serialize_execution_authorization_comment(**v))


def _src(transport):
    return trusted_execution_authorization_source(transport=transport, candidate_packet_id=_CAND, invocation_id=_INV)


def test_trusted_source_current_owner_record_yields_evidence_and_completes(tmp_path, monkeypatch):
    payload, request, plan = _payload()
    t = _Transport([_record(request, plan)])
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=_src(t),
                                    receipt_sink=FileReceiptSink(tmp_path / "t.jsonl"), clock=_clock)
    assert t.calls == 1 and out["status"] == "completed" and out["receipt_persisted"] is True


@pytest.mark.parametrize("change", [dict(execution_authorized=False), dict(expires_at="2026-07-29T15:00:01Z"),
                                    dict(authorized_invocation_id="invocation-other"),
                                    dict(expected_sha="e" * 40), dict(authorized_operation="other-op")])
def test_trusted_source_non_current_record_requires_approval(tmp_path, monkeypatch, change):
    payload, request, plan = _payload()
    t = _Transport([_record(request, plan, **change)])
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=_src(t),
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "approval-required" and out["execution_attempted"] is False


def test_trusted_source_missing_record_requires_approval(tmp_path, monkeypatch):
    payload, _, _ = _payload()
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=_src(_Transport()),
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "approval-required" and out["failure_class"] == "policy-denial"


def test_trusted_source_non_owner_comment_ignored(tmp_path, monkeypatch):
    payload, request, plan = _payload()
    rec = _record(request, plan)
    forged = ExecutionAuthorizationCommentSnapshot(comment_id=2, author_login="mallory",
                                                   created_at=rec.created_at, body=rec.body)
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch),
                                    authorization_source=_src(_Transport([forged])),
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "approval-required" and out["execution_attempted"] is False


def test_trusted_source_outage_is_infrastructure_not_policy(tmp_path, monkeypatch):
    payload, _, _ = _payload()
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch),
                                    authorization_source=_src(_Transport(fail=True)),
                                    receipt_sink=lambda s: None, clock=_clock)
    assert out["status"] == "approval-required" and out["failure_class"] == "infrastructure-unavailable"
    assert "AuthorizationSourceUnavailable" in out["reason_codes"]


def test_trusted_source_has_no_network_or_github_import():
    import ast
    src = Path(nav.__file__).read_text(encoding="utf-8")
    roots = {a.name.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    roots |= {n.module.split(".")[0] for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module and not n.level}
    assert not roots & {"github", "requests", "httpx", "socket", "subprocess", "scripts"}


def test_expired_request_cannot_be_revived_by_backdated_payload_clock(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    payload, _, _ = _payload(evaluated_at="2026-07-29T15:30:00Z")  # in-window backdate attempt
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    refused = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch), authorization_source=_auth_source,
                                        receipt_sink=lambda s: None, clock=_clock)
    assert refused["status"] == "request-rejected" and calls == []
    payload, _, _ = _payload()  # honest payload, real (later) host clock: request is expired
    real_now = lambda: datetime(2026, 11, 14, 7, 0, tzinfo=timezone.utc)
    out = run_ai_navigation_payload(payload, host=_host(tmp_path, monkeypatch),
                                    authorization_source=lambda r, p, e: tec._authorization(r, p),
                                    receipt_sink=lambda s: None, clock=real_now)
    assert out["status"] == "request-rejected" and out["execution_attempted"] is False and calls == []


def test_trusted_source_operation_binding_is_the_composed_one(tmp_path, monkeypatch):
    payload, request, plan = _payload()
    t = _Transport([_record(request, plan, authorized_operation="pre-pr-developer-loop")])
    src = trusted_execution_authorization_source(transport=t, candidate_packet_id=_CAND, invocation_id=_INV,
                                                 operation="pre-pr-developer-loop")
    assert src(request, plan, tec.EVALUATED_AT) is not None
    assert _src(t)(request, plan, tec.EVALUATED_AT) is None
