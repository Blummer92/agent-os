"""Execute source workflow shell steps against fixture gh, without cloud effects.

This covers YAML conditions and real CLI/evidence/gate integration locally;
it does not emulate the GitHub service or qualify live Codespaces SSH.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

from workflow_scheduler.governance.dev_validation import build_dev_validation_request
from workflow_scheduler.governance.dev_validation_codespaces import _failure

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/agent-os-governed-invocation.yml"
NAME, SHA, BRANCH = "fixture-current-codespace", "a" * 40, "agent/retirement-test"
REPOSITORY = "Blummer92/agent-os"
CLOUD = {"Authenticate bounded Agent OS transport", "Install Google Cloud CLI",
         "Invoke exact governed GCE control path"}
HOST = "Install and verify bounded"  # The unquoted YAML hash suffix is a comment.


def _condition(expression, outputs, failed=False):
    if expression is None:
        return not failed
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    always = "always()" in expression
    expression = expression.replace("always()", "True")
    expression = re.sub(r"steps\.([a-z_]+)\.outputs\.([a-z_]+)",
                        lambda m: repr(outputs.get(m[1], {}).get(m[2], "")), expression)
    node = ast.parse(expression.replace("&&", " and ").replace("||", " or "), mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Compare,
               ast.Eq, ast.NotEq, ast.Constant, ast.Load)
    assert all(isinstance(item, allowed) for item in ast.walk(node))
    return (always or not failed) and bool(eval(compile(node, "workflow-if", "eval"), {"__builtins__": {}}))


def _steps():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["ingress"]["steps"]


def _pipeline(tmp_path, operation="dev", scenario="success", actor="Blummer92"):
    profile = "semantic-ownership-advisory" if scenario == "unsupported" else "remote-validation-suite"
    if operation == "install":
        # The retired owner host-install comment on #1238, attempt 1.
        body = "/agent-os install-host-runtime"
        issue_number = 1238
    else:
        body = "/agent-os discover" if operation == "discovery" else f"/agent-os dev-validate {BRANCH} {SHA} {profile}"
        issue_number = 2931
    event = {"action": "created", "repository": {"full_name": REPOSITORY},
             "issue": {"number": issue_number}, "comment": {"id": 1, "body": body,
             "user": {"login": actor}}, "sender": {"login": actor}}
    (tmp_path / "event.json").write_text(json.dumps(event))
    request = build_dev_validation_request(repository=REPOSITORY, issue_number=2931,
                                          branch=BRANCH, source_sha=SHA, validation_id=profile)
    payload = _failure(request, "validation-passed", NAME)
    payload.update(status="success", exit_code=0, cleanup_complete=True,
                   environment_health_evidence_id="sha256:" + "b" * 64)
    if scenario == "stale-sha":
        payload.update(status="needs-decision", reason_codes=["branch-head-mismatch"], exit_code=None)
    if scenario == "mismatched":
        payload["tested_sha"] = "c" * 40
    if operation == "discovery":
        payload = {"schema_version": "1.0", "repository": REPOSITORY, "issue_number": 2931,
                   "status": "needs-decision", "reason_codes": ["codespaces-discovery-store-unavailable"],
                   "handoff_id": None, "result_id": None, "matching_descriptor_count": 0,
                   "execution_authorized": False, "scheduler_invoked": False,
                   "side_effects_performed": False}
    (tmp_path / "provider.json").write_text(json.dumps({"scenario": scenario, "operation": operation, "payload": payload}))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n" + r'''
import json,os,sys
from pathlib import Path
c=json.loads(Path(os.environ["PROVIDER_FIXTURE"]).read_text())
with open(os.environ["PROVIDER_CALLS"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\n")
if sys.argv[1]=="api":
    if c["scenario"]=="permission-denied":
        sys.stderr.write("HTTP 403: forbidden");sys.exit(1)
    item={"name":"fixture-current-codespace","state":"Shutdown" if c["scenario"]=="unavailable" else "Available",
          "repository":{"full_name":"Blummer92/agent-os"},"owner":{"login":"Blummer92"}}
    print(json.dumps({"total_count":1,"codespaces":[item]}));sys.exit(0)
assert sys.argv[1:3]==["codespace","ssh"]
if c["scenario"]=="ssh-failure":
    sys.stderr.write("error connecting to codespace: timed out while waiting for the codespace to start");sys.exit(1)
if c["scenario"]=="malformed":
    print("unframed response");sys.exit(0)
kind="DISCOVERY" if c["operation"]=="discovery" else "DEV-VALIDATION"
print("===AGENT-OS-CODESPACES-"+kind+"-JSON-BEGIN===")
print(json.dumps(c["payload"]))
print("===AGENT-OS-CODESPACES-"+kind+"-JSON-END===")
''')
    gh.chmod(0o755)
    gcloud = bin_dir / "gcloud"
    gcloud.write_text("#!/bin/sh\necho UNEXPECTED_CLOUD_EXECUTION >&2\nexit 97\n")
    gcloud.chmod(0o755)
    env = {"PATH": str(bin_dir) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.defpath,
           "PYTHONPATH": os.environ.get("PYTHONPATH", ""), "GH_TOKEN": "fixture-only",
           "RUNNER_TEMP": str(tmp_path), "GITHUB_EVENT_PATH": str(tmp_path / "event.json"),
           "GITHUB_REPOSITORY": REPOSITORY, "GITHUB_RUN_ATTEMPT": "1",
           "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
           "PROVIDER_FIXTURE": str(tmp_path / "provider.json"), "PROVIDER_CALLS": str(tmp_path / "calls.jsonl"),
           "COMMENT_BODY": body, "COMMENT_USER_ID": "32861845", "ISSUE_NUMBER": "2931",
           "REPOSITORY_ID": "1289370915", "EVENT_NAME": "issue_comment", "REF_NAME": "refs/heads/main",
           "WORKFLOW_REF": REPOSITORY + "/.github/workflows/agent-os-governed-invocation.yml@refs/heads/main"}
    outputs, entered, failed = {}, [], False
    for index, step in enumerate(_steps()):
        if not _condition(step.get("if"), outputs, failed):
            continue
        name = step["name"]
        entered.append(name)
        if "uses" in step or name in CLOUD or name == HOST:
            continue  # Record eligibility, never run a cloud or host operation.
        output = tmp_path / f"output-{index}"
        completed = subprocess.run(("bash", "-e", "-c", step["run"]), cwd=ROOT,
                                   env={**env, "GITHUB_OUTPUT": str(output)},
                                   capture_output=True, text=True, timeout=30)
        assert "UNEXPECTED_CLOUD_EXECUTION" not in completed.stderr
        if step.get("id"):
            outputs[step["id"]] = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
        if completed.returncode:
            assert name == "Enforce developer-validation result gate", completed.stderr
            failed = True
    evidence = tmp_path / "agent-os-ingress"
    result = json.loads((evidence / "result.json").read_text())
    calls = (tmp_path / "calls.jsonl").read_text().splitlines() if (tmp_path / "calls.jsonl").exists() else []
    return result, entered, failed, calls, evidence


@pytest.mark.parametrize("scenario", ["success", "unavailable", "permission-denied", "stale-sha",
                                     "mismatched", "unsupported", "ssh-failure", "malformed"])
def test_dev_validation_shell_pipeline_never_falls_back(tmp_path, scenario):
    result, entered, failed, calls, _ = _pipeline(tmp_path, scenario=scenario)
    assert not CLOUD.intersection(entered) and HOST not in entered
    assert "Attempt Codespaces discovery" not in entered
    evidence = result["dev_validation"]
    assert evidence["tested_sha"] == SHA
    assert failed is (scenario != "success")
    assert evidence["status"] == ("success" if scenario == "success" else "needs-decision")
    assert sum(json.loads(call)[:2] == ["codespace", "ssh"] for call in calls) <= 1
    if scenario == "unsupported":
        assert evidence["reason_codes"] == ["codespaces-profile-not-qualified"] and calls == []
    if scenario == "ssh-failure":
        assert evidence["ssh_exit_code"] == 1
        assert evidence["reason_codes"] == ["dev-validation-codespaces-ssh-failed"]


@pytest.mark.parametrize("scenario", ["success", "unavailable", "permission-denied", "ssh-failure", "malformed"])
def test_discovery_shell_pipeline_preserves_its_own_blocker(tmp_path, scenario):
    result, entered, _, _, evidence = _pipeline(tmp_path, operation="discovery", scenario=scenario)
    assert not CLOUD.intersection(entered) and HOST not in entered
    assert result == json.loads((evidence / "codespaces-discovery-result.json").read_text())
    assert result["codespaces_capable"] is False
    assert result["discovery"]["status"] == "needs-decision"
    assert result["discovery"]["reason_codes"] != ["discovery-gce-unavailable"]


def test_unauthorized_ingress_never_contacts_provider(tmp_path):
    result, entered, _, calls, _ = _pipeline(tmp_path, actor="untrusted-actor")
    assert result["dispatch_status"] == "blocked"
    assert not CLOUD.intersection(entered) and calls == []


def test_no_host_install_step_or_cloud_shortcut_remains() -> None:
    """GCE Wave 1 retired the host-install activation branch: no classifier
    step, no install step, no VM start, and no host-install GCP shortcut.
    The GCE control path still requires an accepted, specifically GCE-routed
    envelope (positive control below)."""
    steps = _steps()
    assert not any(step.get("id") == "host_install" for step in steps)
    assert not any(
        str(step.get("name", "")).startswith("Install and verify bounded")
        for step in steps
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "host_install" not in text
    assert "install-host-runtime" not in text
    assert "gcloud compute instances start" not in text
    outputs = {"transport": {"accepted": "true"}, "route": {"preferred": "gce"}}
    by_name = {step["name"]: step for step in steps}
    assert all(_condition(by_name[name]["if"], outputs) for name in CLOUD)
    outputs = {"transport": {"accepted": "true"}, "route": {"preferred": "codespaces"}}
    assert not any(_condition(by_name[name]["if"], outputs) for name in CLOUD)


def test_former_host_install_comment_is_ignored_with_no_cloud_step(tmp_path):
    """The original owner install comment on #1238 (attempt 1) now flows
    through canonical low-trust ingress, is ignored with a bounded blocked
    result, and enters no cloud or host step."""
    result, entered, failed, calls, _ = _pipeline(tmp_path, operation="install")
    assert not CLOUD.intersection(entered)
    assert not any(name.startswith("Install and verify bounded") for name in entered)
    assert result["dispatch_status"] == "blocked"
    assert result["dispatch_reason"] == "malformed-trigger"
    assert result["execution_authorized"] is False
    assert result["scheduler_invoked"] is False
    assert result["side_effects_performed"] is False
    assert result["transport"]["status"] == "ignored"
    assert result["transport"]["reason"] == "malformed-trigger"
    assert result["transport"]["logical_trigger_id_or_none"] is None
    assert failed is False  # the dev-validation gate is not-applicable here
    assert calls == []


def test_fallback_output_cannot_activate_cloud_steps():
    for step in _steps():
        if step["name"] not in CLOUD:
            continue
        for preferred in ("codespaces", "none", ""):
            outputs = {"transport": {"accepted": "true"},
                       "route": {"preferred": preferred, "gce_fallback_allowed": "true"}}
            assert not _condition(step["if"], outputs)


@pytest.mark.parametrize("change", [None, ("COMMENT_USER_ID", "1"), ("ISSUE_NUMBER", "2931"),
                                    ("REPOSITORY_ID", "1"), ("REF_NAME", "refs/heads/agent/test"),
                                    ("WORKFLOW_REF", "untrusted"), ("GITHUB_RUN_ATTEMPT", "2"),
                                    ("COMMENT_BODY", "/agent-os discover"),
                                    ("COMMENT_BODY", "/agent-os install-host-runtime --force"),
                                    ("COMMENT_BODY", "/agent-os install-host-runtime ")])
def test_former_host_install_envelope_is_never_admitted(change):
    """GCE Wave 1: the host_install classifier step is gone. The former owner
    install envelope — exact or varied — is ignored by canonical ingress and
    cannot produce a trigger identity. Rerun is blocked at the ingress gate."""
    from workflow_scheduler.governance.github_issue_comment_ingress import (
        admit_issue_comment_event,
    )

    env = {"COMMENT_BODY": "/agent-os install-host-runtime", "COMMENT_USER_ID": "32861845",
           "ISSUE_NUMBER": "1238", "REPOSITORY_ID": "1289370915", "EVENT_NAME": "issue_comment",
           "REF_NAME": "refs/heads/main",
           "WORKFLOW_REF": REPOSITORY + "/.github/workflows/agent-os-governed-invocation.yml@refs/heads/main"}
    if change is not None:
        env[change[0]] = change[1]
    event = {"action": "created", "repository": {"full_name": REPOSITORY},
             "issue": {"number": int(env["ISSUE_NUMBER"])},
             "comment": {"id": 1, "body": env["COMMENT_BODY"],
                         "user": {"login": "Blummer92" if env["COMMENT_USER_ID"] == "32861845" else "mallory"}},
             "sender": {"login": "Blummer92" if env["COMMENT_USER_ID"] == "32861845" else "mallory"}}
    result = admit_issue_comment_event(
        event, expected_repository=REPOSITORY, allowed_actor="Blummer92",
        run_attempt=int(env["GITHUB_RUN_ATTEMPT"]) if change == ("GITHUB_RUN_ATTEMPT", "2") else 1,
    )
    assert result.execution_authorized is False
    assert result.scheduler_invoked is False
    assert result.side_effects_performed is False
    if change == ("COMMENT_BODY", "/agent-os discover"):
        # Control case: a different, still-live command is accepted normally.
        assert (result.status, result.reason) == ("accepted", "accepted-discovery-envelope")
    else:
        assert result.logical_trigger_id_or_none is None
    if change == ("GITHUB_RUN_ATTEMPT", "2"):
        assert (result.status, result.reason) == ("blocked", "workflow-rerun")
    elif change == ("COMMENT_USER_ID", "1"):
        assert (result.status, result.reason) == ("blocked", "actor-not-allowed")
    elif change != ("COMMENT_BODY", "/agent-os discover"):
        assert (result.status, result.reason) == ("ignored", "malformed-trigger")
