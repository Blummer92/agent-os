"""Contract regressions for ingress-origin Ready-recovery verification (#2410).

The verifier re-checks the fetched ingress run record and receipt artifact
against the dispatch inputs. Caller-supplied ids are correlation hints only:
every tampered, stale, mismatched, or unavailable record must fail closed.
The cross-consistency tests keep the verifier's hash constructions identical
to the parser and dispatch modules; drift must fail the suite, not weaken
verification.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for _candidate in (REPO_ROOT / "08_Tooling" / "workflow-scheduler" / "src", REPO_ROOT):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

from scripts.agent_os_ready_recovery_ingress import (  # noqa: E402
    compute_receipt_id,
    compute_trigger_id,
    verify_ingress_recovery,
)
from workflow_scheduler.governance.github_issue_comment_ingress import (  # noqa: E402
    _ready_recovery_trigger_id,
    admit_issue_comment_event,
)
from workflow_scheduler.governance.ready_recovery_dispatch import (  # noqa: E402
    PullRequestState,
    SourceRunState,
    WorkflowRunSummary,
    compute_receipt_id as dispatch_compute_receipt_id,
    execute_dispatch,
)

REPOSITORY = "Blummer92/agent-os"
OWNER = "Blummer92"
SERVICE = "chatgpt-codex-connector[bot]"
HEAD_SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_SHA = "b" * 40
OTHER_SHA = "d" * 40
WORKFLOW_ID = 314047915
GOVERNED_WORKFLOW_ID = 271828182
SOURCE_RUN_ID = 40150153359
INGRESS_RUN_ID = 40151280000
VALIDATION_RUN_ID = 40151280659
NOW = datetime(2026, 10, 25, 2, 0, 0, tzinfo=timezone.utc)


class _FakeClient:
    def get_pull_request(self, pr_number: int) -> PullRequestState:
        return PullRequestState(
            state="open",
            draft=False,
            base_ref="main",
            base_sha=MAIN_SHA,
            head_ref="agent/3723-example",
            head_sha=HEAD_SHA,
            head_repo_full_name=REPOSITORY,
        )

    def get_main_head_sha(self) -> str:
        return MAIN_SHA

    def get_source_run(self, run_id: int) -> SourceRunState:
        return SourceRunState(
            run_id=run_id,
            event="pull_request",
            status="completed",
            conclusion="action_required",
            head_sha=HEAD_SHA,
            head_branch="agent/3723-example",
            workflow_id=WORKFLOW_ID,
            workflow_path=".github/workflows/agent-os-validation.yml",
            pr_numbers=(3723,),
            jobs_total_count=0,
        )

    def get_validation_workflow_id(self) -> int:
        return WORKFLOW_ID

    def list_recovery_dispatch_runs(self) -> list[WorkflowRunSummary]:
        if not hasattr(self, "_called"):
            self._called = True
            return []
        return [
            WorkflowRunSummary(
                run_id=VALIDATION_RUN_ID,
                url=f"https://github.com/{REPOSITORY}/actions/runs/{VALIDATION_RUN_ID}",
                head_sha=WORKFLOW_SHA,
                title=f"agent-os-ready-recovery:3723:{HEAD_SHA}",
                created_at=NOW + timedelta(seconds=5),
                status="in_progress",
                conclusion=None,
            )
        ]

    def create_recovery_dispatch(self, **kwargs: object) -> None:
        return None


def genuine_fixtures() -> tuple[dict, dict, dict, dict]:
    """Build a genuine (run, receipt, transport, kwargs) set through the real
    parser and dispatch modules, exactly as the governed ingress job would."""
    body = (
        f"/agent-os recover-ready 3723 {HEAD_SHA} {MAIN_SHA} {WORKFLOW_SHA} {SOURCE_RUN_ID}"
    )
    event = {
        "action": "created",
        "repository": {"full_name": REPOSITORY},
        "issue": {"number": 2410},
        "comment": {"id": 7001, "body": body, "user": {"login": SERVICE}},
        "sender": {"login": SERVICE},
    }
    admitted = admit_issue_comment_event(
        event,
        expected_repository=REPOSITORY,
        allowed_actor=OWNER,
        run_attempt=1,
        ready_recovery_service_actor=SERVICE,
    )
    assert admitted.status == "accepted"
    transport = admitted.to_dict()
    receipt = execute_dispatch(
        transport,
        _FakeClient(),
        ingress_run_id=INGRESS_RUN_ID,
        dispatched_at=NOW,
        poll_attempts=3,
        poll_interval_seconds=0,
        sleeper=lambda s: None,
    )
    assert receipt["decision"] == "dispatched"
    run = {
        "id": INGRESS_RUN_ID,
        "workflow_id": GOVERNED_WORKFLOW_ID,
        "event": "issue_comment",
        "status": "completed",
        "conclusion": "success",
        "head_branch": "main",
        "head_sha": MAIN_SHA,
        "actor": {"login": SERVICE},
    }
    kwargs = dict(
        repository=REPOSITORY,
        pr_number=3723,
        expected_head_sha=HEAD_SHA,
        expected_main_sha=MAIN_SHA,
        expected_workflow_sha=WORKFLOW_SHA,
        source_run_id=SOURCE_RUN_ID,
        trigger_id=admitted.logical_trigger_id_or_none,
        ingress_run_id=INGRESS_RUN_ID,
        validation_run_id=VALIDATION_RUN_ID,
        governed_workflow_id=GOVERNED_WORKFLOW_ID,
        owner_login=OWNER,
        service_actor=SERVICE,
    )
    return run, receipt, transport, kwargs


def test_genuine_ingress_recovery_verifies() -> None:
    run, receipt, transport, kwargs = genuine_fixtures()
    assert verify_ingress_recovery(run, receipt, transport, **kwargs) == []


def test_verifier_rejects_each_tampered_record() -> None:
    cases: list[tuple[str, str]] = []

    def check(label: str, mutate, expected: str) -> None:
        run, receipt, transport, kwargs = genuine_fixtures()
        mutate(run, receipt, transport)
        reasons = verify_ingress_recovery(run, receipt, transport, **kwargs)
        assert expected in reasons, (label, reasons)
        cases.append((label, expected))

    check("run id", lambda r, c, t: r.update(id=INGRESS_RUN_ID + 1), "ingress-run-id-mismatch")
    check("run workflow", lambda r, c, t: r.update(workflow_id=1), "ingress-run-workflow-mismatch")
    check("run event", lambda r, c, t: r.update(event="workflow_dispatch"), "ingress-run-event-mismatch")
    check("run status", lambda r, c, t: r.update(status="in_progress"), "ingress-run-not-completed")
    check("run conclusion", lambda r, c, t: r.update(conclusion="failure"), "ingress-run-not-success")
    check("run branch", lambda r, c, t: r.update(head_branch="develop"), "ingress-run-branch-mismatch")
    check("run main", lambda r, c, t: r.update(head_sha=OTHER_SHA), "ingress-run-main-mismatch")
    check("run actor", lambda r, c, t: r.update(actor={"login": "mallory"}), "ingress-run-actor-not-allowed")
    check("transport reason", lambda r, c, t: t.update(reason="accepted-draft-validation-envelope"), "transport-reason-mismatch")
    check("transport pr", lambda r, c, t: t.update(ready_recovery_pr_number_or_none=9999), "transport-pr-mismatch")
    check("transport head", lambda r, c, t: t.update(ready_recovery_head_sha_or_none=OTHER_SHA), "transport-head-mismatch")
    check("transport main", lambda r, c, t: t.update(ready_recovery_main_sha_or_none=OTHER_SHA), "transport-main-mismatch")
    check("transport workflow", lambda r, c, t: t.update(ready_recovery_workflow_sha_or_none=OTHER_SHA), "transport-workflow-mismatch")
    check("transport source", lambda r, c, t: t.update(ready_recovery_source_run_id_or_none=1), "transport-source-run-mismatch")
    check("transport actor", lambda r, c, t: t.update(actor="mallory"), "transport-actor-mismatch")
    check("transport issue", lambda r, c, t: t.update(issue_number=2411), "trigger-id-recomputed-mismatch")
    check("receipt decision", lambda r, c, t: c.update(decision="blocked"), "receipt-decision-not-dispatched")
    check("receipt reasons", lambda r, c, t: c.update(reason_codes=["other"]), "receipt-reasons-mismatch")
    check("receipt run id", lambda r, c, t: c.update(run_id_or_none=1), "receipt-run-id-mismatch")
    check("receipt url", lambda r, c, t: c.update(run_url_or_none="https://example.invalid/1"), "receipt-run-url-mismatch")
    check("receipt schema", lambda r, c, t: c.update(schema_version="9.9"), "receipt-schema-mismatch")
    check("receipt executed flag", lambda r, c, t: c.update(validation_executed=True), "receipt-validation-executed-flag")
    # A field tampered without repairing the receipt id must fail the
    # content-derived identity check (and usually the binding check too).
    check("receipt id", lambda r, c, t: c.update(observed_head_sha=OTHER_SHA), "receipt-id-mismatch")
    assert len(cases) == 23


def test_verifier_rejects_non_object_records() -> None:
    _, receipt, transport, kwargs = genuine_fixtures()
    run, _, _, _ = genuine_fixtures()
    assert "ingress-run-not-object" in verify_ingress_recovery("x", receipt, transport, **kwargs)
    assert "ingress-receipt-not-object" in verify_ingress_recovery(run, "x", transport, **kwargs)
    assert "ingress-transport-not-object" in verify_ingress_recovery(run, receipt, "x", **kwargs)


def test_trigger_id_constructions_agree_across_modules() -> None:
    parser_id = _ready_recovery_trigger_id(
        REPOSITORY, 2410, 3723, HEAD_SHA, MAIN_SHA, WORKFLOW_SHA, SOURCE_RUN_ID
    )
    verifier_id = compute_trigger_id(
        repository=REPOSITORY,
        issue_number=2410,
        pr_number=3723,
        head_sha=HEAD_SHA,
        main_sha=MAIN_SHA,
        workflow_sha=WORKFLOW_SHA,
        source_run_id=SOURCE_RUN_ID,
    )
    assert parser_id == verifier_id
    assert parser_id.startswith("issue-comment-trigger:")


def test_receipt_id_constructions_agree_across_modules() -> None:
    _, receipt, _, _ = genuine_fixtures()
    assert dispatch_compute_receipt_id(receipt) == compute_receipt_id(receipt)
    assert receipt["receipt_id"] == compute_receipt_id(receipt)
    tampered = copy.deepcopy(receipt)
    tampered["decision"] = "blocked"
    assert compute_receipt_id(tampered) != receipt["receipt_id"]


def test_verifier_cli_accepts_genuine_and_rejects_tampered(tmp_path: Path) -> None:
    run, receipt, transport, kwargs = genuine_fixtures()
    script = REPO_ROOT / "scripts" / "agent_os_ready_recovery_ingress.py"
    paths = {}
    for name, payload in (("run", run), ("receipt", receipt), ("transport", transport)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    args = [
        sys.executable, str(script), "verify",
        "--run", str(paths["run"]),
        "--receipt", str(paths["receipt"]),
        "--transport", str(paths["transport"]),
        "--repository", REPOSITORY,
        "--pr-number", "3723",
        "--expected-head-sha", HEAD_SHA,
        "--expected-main-sha", MAIN_SHA,
        "--expected-workflow-sha", WORKFLOW_SHA,
        "--source-run-id", str(SOURCE_RUN_ID),
        "--trigger-id", kwargs["trigger_id"],
        "--ingress-run-id", str(INGRESS_RUN_ID),
        "--validation-run-id", str(VALIDATION_RUN_ID),
        "--governed-workflow-id", str(GOVERNED_WORKFLOW_ID),
        "--owner-login", OWNER,
        "--service-actor", SERVICE,
    ]
    assert subprocess.run(args, capture_output=True, text=True).returncode == 0
    tampered = copy.deepcopy(receipt)
    tampered["pr_number"] = 9999
    paths["receipt"].write_text(json.dumps(tampered), encoding="utf-8")
    failed = subprocess.run(args, capture_output=True, text=True)
    assert failed.returncode == 1
    assert "receipt-pr-mismatch" in failed.stderr
