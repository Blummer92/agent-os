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
import io
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Protocol

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


# ---------------------------------------------------------------------------
# Bounded wait for ingress evidence (#3732 receipt-publication race).
#
# The governed ingress job dispatches validation BEFORE it publishes its
# receipt artifact, so validation may check before the evidence exists. The
# pre-repair admission fetched once and failed an otherwise authorized
# recovery with ingress-run-not-completed / artifact-count. The repair waits
# — only for the already-identified ingress run and its single receipt
# artifact, with fixed bounds — and then runs the full verification above.
# No smaller sequencing correction works: a pre-dispatch receipt cannot
# carry the correlated validation run id (it does not exist yet), the
# ingress side cannot delay GitHub starting the dispatched run, and
# retrying as a second attempt is still racy and consumes the budget.
# This is the same evaluator, with its inputs awaited — not a second
# evaluator, scheduler, queue, or store. While waiting it performs only
# GETs; it never dispatches another workflow.
# ---------------------------------------------------------------------------

PENDING_RUN_STATUSES = frozenset({"queued", "in_progress"})
DEFAULT_RUN_TIMEOUT_SECONDS = 300.0
DEFAULT_RUN_POLL_SECONDS = 10.0
DEFAULT_ARTIFACT_TIMEOUT_SECONDS = 60.0
DEFAULT_ARTIFACT_POLL_SECONDS = 5.0


class IngressEvidenceProvider(Protocol):
    """Read-only GitHub surface for waiting on ingress evidence."""

    def get_ingress_run(self, run_id: int) -> dict: ...

    def list_artifacts(self, run_id: int) -> list[dict]: ...

    def download_artifact(self, artifact_id: int) -> bytes: ...

    def get_pr_head_repo(self, pr_number: int) -> str: ...


class _GhError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _failure_reasons(code: str, exc: Exception) -> list[str]:
    detail = " ".join(str(exc).split())[:300]
    print(f"{code}: {type(exc).__name__}: {detail}", file=sys.stderr)
    status = getattr(exc, "status", None)
    if type(status) is int and 100 <= status <= 599:
        return [code, f"{code}-http-{status}"]
    return [code]


def _artifact_prefix(ingress_run_id: int) -> str:
    return f"agent-os-ready-recovery-{ingress_run_id}-"


def _extract_zip_evidence(data: bytes) -> tuple[dict | None, dict | None]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            receipt = json.loads(zf.read("receipt.json"))
            transport = json.loads(zf.read("transport.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        return None, None
    if not isinstance(receipt, dict) or not isinstance(transport, dict):
        return None, None
    return receipt, transport


def wait_and_verify_ingress(
    provider: IngressEvidenceProvider,
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
    run_timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS,
    run_poll_seconds: float = DEFAULT_RUN_POLL_SECONDS,
    artifact_timeout_seconds: float = DEFAULT_ARTIFACT_TIMEOUT_SECONDS,
    artifact_poll_seconds: float = DEFAULT_ARTIFACT_POLL_SECONDS,
    sleeper=time.sleep,
    monotonic=time.monotonic,
) -> tuple[str, list[str]]:
    """Wait for identified ingress evidence, then verify it in full.

    Returns ("verified", []) on success, otherwise ("failed", reasons).
    Pending evidence (run queued/in_progress, artifact not yet listed) is
    awaited up to the fixed bounds; terminal evidence (completed run with
    a non-success conclusion, duplicate artifacts) fails immediately
    without consuming the wait budget; provider failures fail closed at
    once. The two-attempt recovery limit is untouched: it is counted by
    the validation workflow after this function returns.
    """
    # Phase 1: wait for the identified ingress run to reach a terminal state.
    run_deadline = monotonic() + run_timeout_seconds
    run: dict | None = None
    while True:
        try:
            run = provider.get_ingress_run(ingress_run_id)
        except Exception as exc:  # provider failure: fail closed, never wait it out
            return "failed", _failure_reasons("ingress-evidence-lookup-failed", exc)
        status = run.get("status")
        if status == "completed":
            break
        if status not in PENDING_RUN_STATUSES:
            return "failed", ["ingress-run-status-unknown"]
        if monotonic() >= run_deadline:
            return "failed", ["ingress-run-wait-timeout"]
        sleeper(min(run_poll_seconds, max(0.0, run_deadline - monotonic())))
    assert run is not None
    if run.get("conclusion") != "success":
        return "failed", ["ingress-run-not-success"]

    # Phase 2: wait for exactly one matching receipt artifact. The upload
    # precedes job completion, so a completed run normally already has it;
    # the grace period covers artifact-listing consistency only. Duplicates
    # can never resolve by waiting (artifacts are immutable), so they fail
    # immediately, as does a run that never produces the artifact.
    artifact_deadline = monotonic() + artifact_timeout_seconds
    artifact_id: int | None = None
    while True:
        try:
            artifacts = provider.list_artifacts(ingress_run_id)
        except Exception as exc:
            return "failed", _failure_reasons("ingress-evidence-lookup-failed", exc)
        prefix = _artifact_prefix(ingress_run_id)
        matches = [a for a in artifacts
                   if isinstance(a, dict) and str(a.get("name", "")).startswith(prefix)]
        if len(matches) == 1:
            artifact_id = matches[0].get("id")
            break
        if len(matches) > 1:
            return "failed", ["ingress-artifact-duplicate"]
        if monotonic() >= artifact_deadline:
            return "failed", ["ingress-artifact-missing"]
        sleeper(min(artifact_poll_seconds, max(0.0, artifact_deadline - monotonic())))
    if type(artifact_id) is not int:
        return "failed", ["ingress-artifact-missing"]
    try:
        data = provider.download_artifact(artifact_id)
    except Exception as exc:
        return "failed", _failure_reasons("ingress-evidence-lookup-failed", exc)
    receipt, transport = _extract_zip_evidence(data)
    if receipt is None or transport is None:
        return "failed", ["ingress-receipt-incomplete"]

    # Phase 3: full revalidation of every trusted-transport binding, exactly
    # as the pre-repair admission did. Nothing about the wait weakens this.
    reasons = verify_ingress_recovery(
        run, receipt, transport,
        repository=repository, pr_number=pr_number,
        expected_head_sha=expected_head_sha, expected_main_sha=expected_main_sha,
        expected_workflow_sha=expected_workflow_sha, source_run_id=source_run_id,
        trigger_id=trigger_id, ingress_run_id=ingress_run_id,
        validation_run_id=validation_run_id,
        governed_workflow_id=governed_workflow_id, owner_login=owner_login,
        service_actor=service_actor,
    )
    if reasons:
        return "failed", reasons

    # Fork check, previously a workflow-shell step after verification; same
    # position here (after verification, before admission succeeds).
    try:
        head_repo = provider.get_pr_head_repo(pr_number)
    except Exception as exc:
        return "failed", _failure_reasons("ingress-evidence-lookup-failed", exc)
    if head_repo != repository:
        return "failed", ["ingress-fork-not-supported"]
    return "verified", []


class GhEvidenceProvider:
    """`gh api` backed provider; the only place network calls live."""

    def __init__(self, repository: str) -> None:
        self._repository = repository

    def _gh_json(self, *args: str) -> object:
        proc = subprocess.run(["gh", "api", *args], capture_output=True, timeout=120)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace")
            match = re.search(r"HTTP (\d{3})", stderr)
            raise _GhError(
                f"gh api {' '.join(args)} failed with exit {proc.returncode}: {stderr[:300]}",
                int(match.group(1)) if match else None,
            )
        return json.loads(proc.stdout.decode("utf-8"))

    def get_ingress_run(self, run_id: int) -> dict:
        data = self._gh_json(f"repos/{self._repository}/actions/runs/{run_id}")
        if not isinstance(data, dict):
            raise _GhError("ingress run record is not an object")
        return data

    def list_artifacts(self, run_id: int) -> list[dict]:
        data = self._gh_json(
            f"repos/{self._repository}/actions/runs/{run_id}/artifacts?per_page=100")
        if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
            raise _GhError("artifact listing has an unexpected shape")
        return data["artifacts"]

    def download_artifact(self, artifact_id: int) -> bytes:
        proc = subprocess.run(
            ["gh", "api", f"repos/{self._repository}/actions/artifacts/{artifact_id}/zip"],
            capture_output=True, timeout=120)
        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", "replace")
            match = re.search(r"HTTP (\d{3})", stderr)
            raise _GhError(
                f"gh api artifact download failed with exit {proc.returncode}: {stderr[:300]}",
                int(match.group(1)) if match else None,
            )
        return proc.stdout

    def get_pr_head_repo(self, pr_number: int) -> str:
        data = self._gh_json(f"repos/{self._repository}/pulls/{pr_number}")
        if not isinstance(data, dict):
            raise _GhError("pull request record is not an object")
        head = data.get("head")
        repo = head.get("repo") if isinstance(head, dict) else None
        full_name = repo.get("full_name") if isinstance(repo, dict) else None
        if type(full_name) is not str:
            raise _GhError("pull request head repository is missing")
        return full_name


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
    wait = sub.add_parser("wait-and-verify")
    wait.add_argument("--repository", required=True)
    wait.add_argument("--pr-number", type=int, required=True)
    wait.add_argument("--expected-head-sha", required=True)
    wait.add_argument("--expected-main-sha", required=True)
    wait.add_argument("--expected-workflow-sha", required=True)
    wait.add_argument("--source-run-id", type=int, required=True)
    wait.add_argument("--trigger-id", required=True)
    wait.add_argument("--ingress-run-id", type=int, required=True)
    wait.add_argument("--validation-run-id", type=int, required=True)
    wait.add_argument("--governed-workflow-id", type=int, required=True)
    wait.add_argument("--owner-login", required=True)
    wait.add_argument("--service-actor", required=True)
    wait.add_argument("--run-timeout", type=float, default=DEFAULT_RUN_TIMEOUT_SECONDS)
    wait.add_argument("--run-interval", type=float, default=DEFAULT_RUN_POLL_SECONDS)
    wait.add_argument("--artifact-timeout", type=float, default=DEFAULT_ARTIFACT_TIMEOUT_SECONDS)
    wait.add_argument("--artifact-interval", type=float, default=DEFAULT_ARTIFACT_POLL_SECONDS)
    args = parser.parse_args(argv)
    if args.command == "wait-and-verify":
        outcome, reasons = wait_and_verify_ingress(
            GhEvidenceProvider(args.repository),
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
            run_timeout_seconds=args.run_timeout,
            run_poll_seconds=args.run_interval,
            artifact_timeout_seconds=args.artifact_timeout,
            artifact_poll_seconds=args.artifact_interval,
        )
        if outcome != "verified":
            print(f"ingress recovery verification failed: {','.join(reasons)}", file=sys.stderr)
            return 1
        print("ingress recovery verified")
        return 0
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
