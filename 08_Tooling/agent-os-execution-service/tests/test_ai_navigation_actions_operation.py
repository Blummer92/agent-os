"""Actions-side AI Navigation read-only operation tests (local candidate).

Real: canonical ``discover_issue_handoff`` over temporary local stores, the existing
issue-comment ingress parser, receipt build/verify, artifact-listing check.
Synthetic (test-only): descriptors written to temporary directories. They are fixtures, not a
genuine host store, so no test here is evidence of a live connection.
NOT exercised: any GitHub-hosted run, GitHub MCP, real checkpoint store, or workflow wiring.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

import pytest

REPO = "Blummer92/agent-os"
SHA = "a" * 40
ISSUE = 1233

import agent_os_execution_service.ai_navigation_actions_operation as op
from scripts.agent_os_execution_checkpoint.invocation_descriptor import (
    INVOCATION_DESCRIPTOR_SCHEMA_NAME, INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
    GovernedInvocationDescriptor, append_invocation_descriptor,
)


def _id(prefix, label):
    return f"{prefix}:{hashlib.sha256(label.encode()).hexdigest()}"


def _descriptor(label="one"):
    """Synthetic test-only descriptor (field set copied from the canonical discovery tests)."""
    return GovernedInvocationDescriptor(
        schema_name=INVOCATION_DESCRIPTOR_SCHEMA_NAME, schema_version=INVOCATION_DESCRIPTOR_SCHEMA_VERSION,
        repository=REPO, issue_number=ISSUE, issue_or_handoff_identity=f"issue:{ISSUE}",
        handoff_id=_id("executor-handoff", f"handoff-{label}"),
        route_decision_id=_id("executor-route-decision", f"route-{label}"),
        execution_service_request_fingerprint=_id("execution-request", f"request-{label}"),
        authorization_id=_id("authorization", f"authorization-{label}"),
        source_ref="refs/heads/agent/1233-x", source_sha="a" * 40,
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
        execution_id=f"execution-1233-{label}", invocation_id=f"invocation-1233-{label}",
    )



def _event(body="/agent-os ai-navigation-discover", login="Blummer92", issue=ISSUE, comment_id=77):
    return {"action": "created", "repository": {"full_name": REPO}, "issue": {"number": issue},
            "comment": {"id": comment_id, "body": body, "user": {"login": login}}, "sender": {"login": login}}


def _transport(**over):
    """Transport produced by the REAL existing ingress parser, then optionally tampered."""
    from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

    base = admit_issue_comment_event(_event(), expected_repository=REPO, allowed_actor="Blummer92", run_attempt=1).to_dict()
    base.update(over)
    return base


def _kw(**over):
    kw = dict(expected_repository=REPO, allowed_actor="Blummer92", run_id=9, source_sha=SHA)
    kw.update(over)
    return kw


def _binding():
    return op.admit_transport(_transport(), **_kw())


def _store(tmp_path, labels=()):
    root = tmp_path / "store"
    (root / "invocations").mkdir(parents=True)
    for label in labels:
        append_invocation_descriptor(root, _descriptor(label))
    return root


def test_admit_binds_everything():
    assert _binding()["comment_id"] == 77


@pytest.mark.parametrize("over,kw", [
    ({"reason": "accepted-envelope"}, {}), ({"status": "blocked"}, {}),
    ({"repository": "x/y"}, {}), ({"actor": "someone"}, {}),
    ({"issue_number": 2425}, {}),  # logical trigger id no longer matches the issue
    ({"logical_trigger_id_or_none": "issue-comment-trigger:" + "0" * 64}, {}),
    ({"logical_trigger_id_or_none": None}, {}),
    ({"comment_id": 0}, {}), ({}, {"source_sha": "abc"}), ({}, {"run_id": 0}), ({}, {"owning_issue": 999}),
])
def test_admit_refuses_mismatch(over, kw):
    with pytest.raises(op.ActionsOperationRefused):
        op.admit_transport(_transport(**over), **_kw(**kw))


def test_admit_refuses_non_mapping():
    with pytest.raises(op.ActionsOperationRefused):
        op.admit_transport(None, **_kw())


@pytest.mark.parametrize("env,reason", [
    ({}, "store-root-not-configured"), ({op.STORE_ROOT_ENV: "  "}, "store-root-not-configured"),
    ({op.STORE_ROOT_ENV: "relative/x"}, "store-root-not-absolute"),
])
def test_missing_or_bad_root_never_calls_locator(env, reason, monkeypatch):
    import scripts.agent_os_execution_checkpoint.handoff_discovery as hd
    monkeypatch.setattr(hd, "discover_issue_handoff", lambda *a, **k: pytest.fail("locator called"))
    receipt = op.run_readonly_discovery(_binding(), env)
    assert receipt["status"] == "blocked" and receipt["reason_codes"] == [reason]
    assert receipt["matching_descriptor_count"] is None  # not-run is never zero
    assert op.verify_receipt(receipt, expected_binding=_binding()) == (True, "verified")


def test_dir_without_invocations_refuses(tmp_path):
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(tmp_path)})
    assert receipt["reason_codes"] == ["store-root-has-no-invocations"]


def test_empty_store_not_found_zero(tmp_path):
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(_store(tmp_path))})
    assert (receipt["status"], receipt["matching_descriptor_count"], receipt["handoff_present"]) == ("not-found", 0, False)


def test_single_match_found_without_exposing_id(tmp_path):
    root = _store(tmp_path, ["one"])
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(root)})
    assert receipt["status"] == "found" and receipt["handoff_present"] is True
    assert "executor-handoff" not in json.dumps(receipt)
    assert op.verify_receipt(receipt, expected_binding=_binding())[0]
    assert receipt["execution_authorized"] is False


def test_multiple_matches_needs_decision(tmp_path):
    root = _store(tmp_path, ["one", "two"])
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(root)})
    assert receipt["status"] == "needs-decision" and receipt["handoff_present"] is False
    assert receipt["matching_descriptor_count"] == 2


def test_wrong_issue_not_found(tmp_path):
    root = _store(tmp_path, ["one"])
    from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event
    t = admit_issue_comment_event(_event(issue=999), expected_repository=REPO, allowed_actor="Blummer92", run_attempt=1).to_dict()
    b = op.admit_transport(t, **_kw())
    assert op.run_readonly_discovery(b, {op.STORE_ROOT_ENV: str(root)})["status"] == "not-found"


def test_corrupt_descriptor_fails_closed(tmp_path):
    root = _store(tmp_path, ["one"])
    path = next((root / "invocations").glob("*.json"))
    path.write_text(path.read_text()[:-20], encoding="utf-8")
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(root)})
    assert receipt["status"] == "needs-decision" and receipt["handoff_present"] is False


def test_symlinked_invocations_refused(tmp_path):
    real = _store(tmp_path, ["one"])
    link = tmp_path / "linked"
    link.mkdir()
    (link / "invocations").symlink_to(real / "invocations")
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(link)})
    assert receipt["status"] == "needs-decision" and receipt["handoff_present"] is False


def _good(tmp_path):
    return op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(_store(tmp_path, ["one"]))})


def test_verify_rejects_missing_forged_and_misbound(tmp_path):
    good = _good(tmp_path)
    assert op.verify_receipt(None, expected_binding=_binding())[1] == "receipt-missing"
    forged = copy.deepcopy(good); forged["status"] = "not-found"
    assert op.verify_receipt(forged, expected_binding=_binding())[1] == "digest-mismatch"
    flag = copy.deepcopy(good); flag["execution_authorized"] = True
    assert op.verify_receipt(flag, expected_binding=_binding())[1] == "digest-mismatch"
    for key, value in [("comment_id", 78), ("source_sha", "b" * 40), ("run_attempt", 2), ("issue_number", 5)]:
        assert op.verify_receipt(good, expected_binding={**_binding(), key: value})[1] == f"binding-mismatch:{key}"


def test_verify_rejects_resigned_inconsistent_receipts(tmp_path):
    good = _good(tmp_path)
    for mut, why in [({"matching_descriptor_count": 2}, "found-inconsistent"),
                     ({"execution_authorized": True}, "authority-flag-not-false"),
                     ({"status": "not-found", "reason_codes": ["no-matching-descriptor"]}, "non-found-exposes-handoff")]:
        r = {k: v for k, v in good.items() if k != "receipt_digest"}; r.update(mut); r["receipt_digest"] = op._digest(r)
        assert op.verify_receipt(r, expected_binding=_binding())[1] == why


def _resign(receipt, **mut):
    r = {k: v for k, v in receipt.items() if k != "receipt_digest"}
    r.update(mut)
    r["receipt_digest"] = op._digest(r)  # attacker recomputes the unkeyed digest
    return r


@pytest.mark.parametrize("mut,why", [
    ({"status": "garbage"}, "status-unknown"),
    ({"status": "not-found", "reason_codes": ["no-matching-descriptor"], "matching_descriptor_count": 7, "handoff_present": False}, "not-found-inconsistent"),
    ({"status": "needs-decision", "reason_codes": ["found"], "handoff_present": False}, "needs-decision-inconsistent"),
    ({"status": "needs-decision", "reason_codes": ["multiple-matching-descriptors"], "matching_descriptor_count": 1, "handoff_present": False}, "needs-decision-inconsistent"),
    ({"status": "needs-decision", "reason_codes": ["store-unavailable"], "matching_descriptor_count": 3, "handoff_present": False}, "needs-decision-inconsistent"),
    ({"status": "blocked", "reason_codes": ["no-matching-descriptor"], "matching_descriptor_count": None, "handoff_present": False}, "blocked-inconsistent"),
    ({"status": "blocked", "reason_codes": ["store-root-not-configured"], "matching_descriptor_count": 0, "handoff_present": False}, "blocked-inconsistent"),
    ({"status": "found", "reason_codes": ["found", "found"]}, "reason-shape-invalid"),
    ({"status": "found", "reason_codes": []}, "reason-shape-invalid"),
    ({"status": "found", "reason_codes": "found"}, "reason-shape-invalid"),
    ({"status": "found", "reason_codes": ["no-matching-descriptor"]}, "found-inconsistent"),
    ({"status": "found", "matching_descriptor_count": True}, "found-inconsistent"),
    ({"status": "found", "matching_descriptor_count": 1.0}, "found-inconsistent"),
    ({"handoff_present": "yes"}, "found-inconsistent"),
    ({"status": "blocked", "reason_codes": ["store-root-not-configured"], "matching_descriptor_count": None, "handoff_present": True}, "non-found-exposes-handoff"),
    ({"extra_field": "x"}, "unexpected-or-missing-fields"),
    ({"run_id": True}, "binding-mismatch:run_id"),
])
def test_verify_rejects_validly_rehashed_malformed_receipts(tmp_path, mut, why):
    good = _good(tmp_path)
    assert op.verify_receipt(_resign(good, **mut), expected_binding={**_binding(), "run_id": 1 if mut.get("run_id") is True else _binding()["run_id"]})[1] == why


def test_verify_accepts_every_canonical_shape(tmp_path):
    good = _good(tmp_path)
    shapes = [
        dict(status="not-found", reason_codes=["no-matching-descriptor"], matching_descriptor_count=0, handoff_present=False),
        dict(status="needs-decision", reason_codes=["multiple-matching-descriptors"], matching_descriptor_count=2, handoff_present=False),
        dict(status="needs-decision", reason_codes=["store-unavailable"], matching_descriptor_count=0, handoff_present=False),
        dict(status="needs-decision", reason_codes=["store-bound-exceeded"], matching_descriptor_count=0, handoff_present=False),
        dict(status="needs-decision", reason_codes=["descriptor-integrity-unverified"], matching_descriptor_count=1, handoff_present=False),
        dict(status="blocked", reason_codes=["locator-dependency-unavailable"], matching_descriptor_count=None, handoff_present=False),
    ]
    for shape in shapes:
        assert op.verify_receipt(_resign(good, **shape), expected_binding=_binding()) == (True, "verified"), shape


def test_every_receipt_the_module_emits_verifies(tmp_path):
    b = _binding()
    envs = [{}, {op.STORE_ROOT_ENV: "rel"}, {op.STORE_ROOT_ENV: str(tmp_path)},
            {op.STORE_ROOT_ENV: str(_store(tmp_path / "a"))}, {op.STORE_ROOT_ENV: str(_store(tmp_path / "b", ["one"]))},
            {op.STORE_ROOT_ENV: str(_store(tmp_path / "c", ["one", "two"]))}]
    for env in envs:
        assert op.verify_receipt(op.run_readonly_discovery(b, env), expected_binding=b)[0], env


def _page(ids, total):
    return {"total_count": total, "artifacts": [{"id": i} for i in ids]}


def test_artifact_listing_fails_closed_unless_complete():
    assert op.check_artifact_listing(None) == (False, "listing-missing")
    assert op.check_artifact_listing([_page(range(100), 2832)]) == (False, "listing-incomplete")  # the one-page case
    assert op.check_artifact_listing([_page([1, 2], 3), _page([], 3)], per_page=2) == (False, "listing-incomplete")
    assert op.check_artifact_listing([_page([1, 2], 3), _page([3], 4)], per_page=2) == (False, "total-count-inconsistent")
    assert op.check_artifact_listing([_page([1, 1], 2)], per_page=2) == (False, "artifact-ids-duplicate-or-missing")
    assert op.check_artifact_listing([_page([1], 2), _page([2], 2)], per_page=2) == (False, "page-size-inconsistent")
    assert op.check_artifact_listing([_page([1, 2], 3), _page([3], 3)], per_page=2) == (True, "complete")


def test_ingress_grammar_and_authorization_model_unchanged():
    from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event

    def adm(ev, attempt=1):
        return admit_issue_comment_event(ev, expected_repository=REPO, allowed_actor="Blummer92", run_attempt=attempt)
    ok = adm(_event())
    assert (ok.status, ok.reason) == ("accepted", op.ENVELOPE_REASON) and ok.execution_authorized is False
    assert ok.issue_number == ISSUE and ok.scheduler_invoked is False and ok.side_effects_performed is False
    # target issue is the commented issue; a body selector is NOT parsed
    for body in ("/agent-os ai-navigation-discover 2425", "/agent-os ai-navigation-discover ", "/agent-os  ai-navigation-discover",
                 "/AGENT-OS ai-navigation-discover", "/agent-os ai-navigation-discover\n/agent-os discover", "x /agent-os ai-navigation-discover"):
        assert adm(_event(body)).status == "ignored", body
    assert adm(_event(login="mallory")).status == "blocked"
    assert adm(_event(), attempt=2).reason == "workflow-rerun"
    pr = _event(); pr["issue"]["pull_request"] = {}
    assert adm(pr).status == "ignored"
    assert adm(_event("/agent-os discover")).reason == "accepted-discovery-envelope"  # existing grammar untouched


def test_duplicate_comment_yields_same_trigger_id_and_distinct_comments_differ():
    a, b, c = _transport(), _transport(), _transport()
    assert a["logical_trigger_id_or_none"] == b["logical_trigger_id_or_none"]  # issue+operation keyed, comment-independent
    from workflow_scheduler.governance.github_issue_comment_ingress import admit_issue_comment_event
    d = admit_issue_comment_event(_event(comment_id=78), expected_repository=REPO, allowed_actor="Blummer92", run_attempt=1).to_dict()
    assert d["logical_trigger_id_or_none"] == a["logical_trigger_id_or_none"] and d["comment_id"] != a["comment_id"]
    # receipts bind the comment id, so a receipt for comment 77 cannot be replayed as the answer to comment 78
    r77 = op.run_readonly_discovery(op.admit_transport(a, **_kw()), {})
    b78 = op.admit_transport(d, **_kw())
    assert op.verify_receipt(r77, expected_binding=b78)[1] == "binding-mismatch:comment_id"


def test_missing_locator_dependency_fails_closed_with_receipt(tmp_path, monkeypatch):
    import builtins
    root = _store(tmp_path, ["one"])
    real = builtins.__import__

    def deny(name, *a, **k):
        if name.startswith("scripts.agent_os_execution_checkpoint"):
            raise ModuleNotFoundError("yaml")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", deny)
    receipt = op.run_readonly_discovery(_binding(), {op.STORE_ROOT_ENV: str(root)})
    assert (receipt["status"], receipt["reason_codes"], receipt["matching_descriptor_count"]) == ("blocked", ["locator-dependency-unavailable"], None)
    monkeypatch.undo()
    assert op.verify_receipt(receipt, expected_binding=_binding())[0]


def test_cli_main_end_to_end_with_real_ingress_output(tmp_path, capsys):
    t = tmp_path / "t.json"; t.write_text(json.dumps(_transport()))
    out = tmp_path / "o" / "receipt.json"
    args = ["--transport", str(t), "--repository", REPO, "--allowed-actor", "Blummer92", "--run-id", "9", "--source-sha", SHA, "--output", str(out)]
    assert op.main(args, environ={}) == 0
    receipt = json.loads(out.read_text())
    assert receipt["reason_codes"] == ["store-root-not-configured"] and receipt["matching_descriptor_count"] is None
    assert op.verify_receipt(receipt, expected_binding=_binding())[0]
    # refused request writes nothing and exits 2
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(_transport(actor="mallory")))
    out2 = tmp_path / "o2.json"
    assert op.main(args[:1] + [str(bad)] + args[2:-1] + [str(out2)], environ={}) == 2 and not out2.exists()
    missing = tmp_path / "nope.json"
    assert op.main(args[:1] + [str(missing)] + args[2:-1] + [str(out2)], environ={}) == 2
    garbage = tmp_path / "g.json"; garbage.write_text("{not json")
    assert op.main(args[:1] + [str(garbage)] + args[2:-1] + [str(out2)], environ={}) == 2
    # with a real temp store the same entry point finds exactly one and still exposes no id
    root = _store(tmp_path, ["one"])
    out3 = tmp_path / "o3.json"
    assert op.main(args[:-1] + [str(out3)], environ={op.STORE_ROOT_ENV: str(root)}) == 0
    r3 = json.loads(out3.read_text())
    assert r3["status"] == "found" and "executor-handoff" not in out3.read_text()


WORKFLOWS = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows"


def test_new_workflow_is_read_only_owner_gated_and_secretless():
    import yaml

    text = (WORKFLOWS / "agent-os-ai-navigation-discover.yml").read_text()
    doc = yaml.safe_load(text)
    triggers = doc.get(True) or doc.get("on")  # YAML 1.1 parses the key `on` as True
    assert list(triggers) == ["issue_comment"] and triggers["issue_comment"] == {"types": ["created"]}
    assert doc["permissions"] == {"contents": "read"}
    (job,) = doc["jobs"].values()
    cond = job["if"]
    assert "github.event.comment.user.id == 32861845" in cond and "github.event.issue.pull_request == null" in cond
    assert "github.event.comment.body == '/agent-os ai-navigation-discover'" in cond
    assert "secrets." not in text and "GH_TOKEN" not in text and "gh api" not in text and "continue-on-error" not in text
    assert "workflow_dispatch" not in text and "id-token" not in text and "codespaces" not in text.lower().replace("no codespace", "")
    for step in job["steps"]:  # no event or comment text is interpolated into any shell command
        assert "github.event" not in step.get("run", "").replace("$GITHUB_EVENT_PATH", "")
    uploads = [st for st in job["steps"] if str(st.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(uploads) == 1 and uploads[0]["with"]["retention-days"] == 7
    runs = "\n".join(st.get("run", "") for st in job["steps"])
    steps = job["steps"]
    names = [st.get("uses", st.get("run", ""))[:40] for st in steps]
    py = next(i for i, st in enumerate(steps) if str(st.get("uses", "")).startswith("actions/setup-python@v7"))
    assert steps[py]["with"]["python-version"] == "3.11"  # repo convention; execution-service requires >=3.11
    assert "PyYAML==6.0.3" in steps[py + 1]["run"]  # same pin the governed workflow uses; only third-party import of the locator
    first_run = next(i for i, st in enumerate(steps) if "ai_navigation_actions_operation" in st.get("run", "") or "github_issue_comment_ingress" in st.get("run", ""))
    assert py + 1 < first_run and "python3" not in runs
    assert "--allowed-actor Blummer92" in runs and "ai_navigation_actions_operation" in runs and "github_issue_comment_ingress" in runs


def test_governed_invocation_workflow_excludes_new_comment_and_is_otherwise_unchanged():
    text = (WORKFLOWS / "agent-os-governed-invocation.yml").read_text()
    assert "github.event.comment.body != '/agent-os ai-navigation-discover'" in text


def test_module_has_no_network_subprocess_or_extra_write_surface():
    import ast

    src = pathlib.Path(op.__file__).read_text()
    tree = ast.parse(src)
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not mods & {"requests", "urllib", "subprocess", "socket", "http", "shutil"}
    assert src.count(".write_text(") == 1 and "open(" not in src and "os.system" not in src
    assert src.count("mkdir(") == 1  # both only inside main(), for the --output path
