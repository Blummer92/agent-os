#!/usr/bin/env python3
"""Independent verification of an ingress-origin Ready-recovery dispatch (#2410).

The validation workflow calls this from its candidate step after fetching,
through the GitHub API, the ingress run record and the ingress receipt
artifact. Caller-supplied ids prove nothing on their own: every binding is
re-checked here against those fetched records, and both content-derived
identities (the logical trigger id and the receipt id) are recomputed.

A forged, stale, mismatched, duplicated, or unavailable record fails closed.
The direct owner-dispatch rule is untouched: this verifier only runs when the
dispatch carries ingress correlation inputs, and a dispatch without them
still requires the repository-owner actor.

The two hash constructions below duplicate the ingress parser
(``workflow_scheduler.governance.github_issue_comment_ingress``) and the
dispatch module (``workflow_scheduler.governance.ready_recovery_dispatch``).
They must stay identical; the cross-consistency tests in
``tests/test_agent_os_ready_recovery_ingress.py`` import both sides and
assert agreement, so a drift fails the suite rather than silently weakening
verification.

Exit 0 means verified. Exit 1 prints fail-closed reason codes to stderr.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

RECEIPT_SCHEMA_VERSION = "1.0"
OPERATION = "ready-recovery-validation"
VALIDATION_WORKFLOW_FILE = "agent-os-validation.yml"
EXPECTED_TRANSPORT_REASON = "accepted-ready-recovery-envelope"
RECEIPT_MARKER_PREFIX = "agent-os-ready-recovery-receipt:"


def compute_trigger_id(
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
    head_sha: str,
    main_sha: str,
    workflow_sha: str,
    source_run_id: int,
) -> str:
    material = (
        f"{repository}\0{issue_number}\0recover-ready\0{pr_number}\0"
        f"{head_sha}\0{main_sha}\0{workflow_sha}\0{source_run_id}"
    ).encode("ascii")
    return f"issue-comment-trigger:{hashlib.sha256(material).hexdigest()}"


def compute_receipt_id(receipt: dict) -> str:
    core = {key: value for key, value in receipt.items() if key != "receipt_id"}
    material = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return f"{RECEIPT_MARKER_PREFIX}{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def verify_ingress_recovery(
    run: object,
    receipt: object,
    transport: object,
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    expected_main_sha: str,
    expected_workflow_sha: str,
    source_run_id: int,
    trigger_id: str,
    ingress_run_id: int,
    validation_run_id: int,
    governed_workflow_id: int,
    owner_login: str,
    service_actor: str,
) -> list[str]:
    """Return fail-closed reason codes; an empty list means verified."""
    reasons: list[str] = []
    if not isinstance(run, dict):
        return ["ingress-run-not-object"]
    if not isinstance(receipt, dict):
        return ["ingress-receipt-not-object"]
    if not isinstance(transport, dict):
        return ["ingress-transport-not-object"]

    # --- Ingress run record (fetched from GitHub, not caller-supplied) ---
    if run.get("id") != ingress_run_id:
        reasons.append("ingress-run-id-mismatch")
    if run.get("workflow_id") != governed_workflow_id:
        reasons.append("ingress-run-workflow-mismatch")
    if run.get("event") != "issue_comment":
        reasons.append("ingress-run-event-mismatch")
    if run.get("status") != "completed":
        reasons.append("ingress-run-not-completed")
    if run.get("conclusion") != "success":
        reasons.append("ingress-run-not-success")
    if run.get("head_branch") != "main":
        reasons.append("ingress-run-branch-mismatch")
    if run.get("head_sha") != expected_main_sha:
        reasons.append("ingress-run-main-mismatch")
    run_actor = run.get("actor")
    run_actor_login = run_actor.get("login") if isinstance(run_actor, dict) else None
    if run_actor_login not in {owner_login, service_actor}:
        reasons.append("ingress-run-actor-not-allowed")

    # --- Transport envelope (from the ingress artifact) ---
    if transport.get("status") != "accepted":
        reasons.append("transport-not-accepted")
    if transport.get("reason") != EXPECTED_TRANSPORT_REASON:
        reasons.append("transport-reason-mismatch")
    if transport.get("repository") != repository:
        reasons.append("transport-repository-mismatch")
    issue_number = transport.get("issue_number")
    if type(issue_number) is not int or issue_number < 1:
        reasons.append("transport-issue-invalid")
        issue_number = None
    if transport.get("comment_id") is None or type(transport.get("comment_id")) is not int:
        reasons.append("transport-comment-invalid")
    if transport.get("actor") != run_actor_login:
        reasons.append("transport-actor-mismatch")
    if transport.get("logical_trigger_id_or_none") != trigger_id:
        reasons.append("transport-trigger-mismatch")
    if transport.get("ready_recovery_pr_number_or_none") != pr_number:
        reasons.append("transport-pr-mismatch")
    if transport.get("ready_recovery_head_sha_or_none") != expected_head_sha:
        reasons.append("transport-head-mismatch")
    if transport.get("ready_recovery_main_sha_or_none") != expected_main_sha:
        reasons.append("transport-main-mismatch")
    if transport.get("ready_recovery_workflow_sha_or_none") != expected_workflow_sha:
        reasons.append("transport-workflow-mismatch")
    if transport.get("ready_recovery_source_run_id_or_none") != source_run_id:
        reasons.append("transport-source-run-mismatch")
    if issue_number is not None:
        recomputed = compute_trigger_id(
            repository=repository,
            issue_number=issue_number,
            pr_number=pr_number,
            head_sha=expected_head_sha,
            main_sha=expected_main_sha,
            workflow_sha=expected_workflow_sha,
            source_run_id=source_run_id,
        )
        if recomputed != trigger_id:
            reasons.append("trigger-id-recomputed-mismatch")

    # --- Receipt (from the ingress artifact) ---
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        reasons.append("receipt-schema-mismatch")
    if receipt.get("operation") != OPERATION:
        reasons.append("receipt-operation-mismatch")
    if receipt.get("workflow") != VALIDATION_WORKFLOW_FILE:
        reasons.append("receipt-workflow-mismatch")
    if receipt.get("repository") != repository:
        reasons.append("receipt-repository-mismatch")
    if receipt.get("issue_number") != transport.get("issue_number"):
        reasons.append("receipt-issue-mismatch")
    if receipt.get("comment_id") != transport.get("comment_id"):
        reasons.append("receipt-comment-mismatch")
    if receipt.get("actor") != transport.get("actor"):
        reasons.append("receipt-actor-mismatch")
    if receipt.get("trigger_id") != trigger_id:
        reasons.append("receipt-trigger-mismatch")
    if receipt.get("ingress_trigger_id") != trigger_id:
        reasons.append("receipt-ingress-trigger-mismatch")
    if receipt.get("ingress_run_id") != ingress_run_id:
        reasons.append("receipt-ingress-run-mismatch")
    if receipt.get("pr_number") != pr_number:
        reasons.append("receipt-pr-mismatch")
    if receipt.get("expected_head_sha") != expected_head_sha:
        reasons.append("receipt-head-mismatch")
    if receipt.get("observed_head_sha") != expected_head_sha:
        reasons.append("receipt-observed-head-mismatch")
    if receipt.get("expected_main_sha") != expected_main_sha:
        reasons.append("receipt-main-mismatch")
    if receipt.get("expected_workflow_sha") != expected_workflow_sha:
        reasons.append("receipt-workflow-sha-mismatch")
    if receipt.get("source_validation_run_id") != source_run_id:
        reasons.append("receipt-source-run-mismatch")
    if receipt.get("decision") != "dispatched":
        reasons.append("receipt-decision-not-dispatched")
    if receipt.get("reason_codes") != ["dispatch-correlated"]:
        reasons.append("receipt-reasons-mismatch")
    if receipt.get("run_id_or_none") != validation_run_id:
        reasons.append("receipt-run-id-mismatch")
    expected_url = f"https://github.com/{repository}/actions/runs/{validation_run_id}"
    if receipt.get("run_url_or_none") != expected_url:
        reasons.append("receipt-run-url-mismatch")
    if receipt.get("validation_executed") is not False:
        reasons.append("receipt-validation-executed-flag")
    if receipt.get("receipt_id") != compute_receipt_id(receipt):
        reasons.append("receipt-id-mismatch")
    return reasons


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--run", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--transport", type=Path, required=True)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--pr-number", type=int, required=True)
    verify.add_argument("--expected-head-sha", required=True)
    verify.add_argument("--expected-main-sha", required=True)
    verify.add_argument("--expected-workflow-sha", required=True)
    verify.add_argument("--source-run-id", type=int, required=True)
    verify.add_argument("--trigger-id", required=True)
    verify.add_argument("--ingress-run-id", type=int, required=True)
    verify.add_argument("--validation-run-id", type=int, required=True)
    verify.add_argument("--governed-workflow-id", type=int, required=True)
    verify.add_argument("--owner-login", required=True)
    verify.add_argument("--service-actor", required=True)
    args = parser.parse_args(argv)
    reasons = verify_ingress_recovery(
        _load_json(args.run),
        _load_json(args.receipt),
        _load_json(args.transport),
        repository=args.repository,
        pr_number=args.pr_number,
        expected_head_sha=args.expected_head_sha,
        expected_main_sha=args.expected_main_sha,
        expected_workflow_sha=args.expected_workflow_sha,
        source_run_id=args.source_run_id,
        trigger_id=args.trigger_id,
        ingress_run_id=args.ingress_run_id,
        validation_run_id=args.validation_run_id,
        governed_workflow_id=args.governed_workflow_id,
        owner_login=args.owner_login,
        service_actor=args.service_actor,
    )
    if reasons:
        print(f"ingress recovery verification failed: {','.join(reasons)}", file=sys.stderr)
        return 1
    print("ingress recovery verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
