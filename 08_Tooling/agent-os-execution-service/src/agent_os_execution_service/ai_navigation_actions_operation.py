"""Read-only Actions-side AI Navigation discovery operation and receipt (local candidate).

This is the *runner-side* half of the GitHub MCP -> GitHub Actions route. It is not wired
into any workflow, is not registered, and nothing here dispatches or authorizes execution.

What it composes (all existing owners, nothing duplicated):

* the low-trust comment envelope is parsed and owner-checked by the existing
  ``workflow_scheduler.governance.github_issue_comment_ingress``; this module only accepts
  that parser's ``transport`` result and re-checks repository, actor and issue binding;
* handoff lookup is the canonical ``discover_issue_handoff`` over a store root that comes
  only from the host environment (``AGENT_OS_CHECKPOINT_STORE_ROOT``); a missing, relative
  or non-store root refuses without calling the locator;
* the result is a bounded receipt bound to repository, issue, comment, run, attempt and
  source SHA, with an unkeyed self digest. ``verify_receipt`` checks well-formedness, canonical
  status/reason/count consistency and the binding; it cannot authenticate the producer.
  The receipt never carries a handoff id, only a presence flag.

``check_artifact_listing`` is a pure, currently UNUSED helper (not implemented: no caller, no
endpoint binding) that fails closed on an incomplete GitHub artifact listing; an artifact is
evidence, not a checkpoint store.

Wiring (local, unpublished): the ingress grammar ``/agent-os ai-navigation-discover`` (target issue =
the issue the owner commented on) and the workflow ``agent-os-ai-navigation-discover.yml`` call
``main`` below. Still missing, by design: a durable checkpoint store a GitHub-hosted runner can read
(none authorized), so a hosted run reports ``blocked`` with the named reason instead of a result.

Trust labels: the receipt digest proves internal consistency only. It is unkeyed, so it does not
authenticate the producer. Authenticity of a hosted receipt rests on retrieving it from the
workflow run itself (run id, workflow path and head SHA read from GitHub), not on the digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ENVELOPE_REASON = "accepted-ai-navigation-discover-envelope"
OPERATION = "ai-navigation-discover"
RECEIPT_SCHEMA = "agent-os.ai-navigation-actions-receipt"
RECEIPT_VERSION = "1.0"
STORE_ROOT_ENV = "AGENT_OS_CHECKPOINT_STORE_ROOT"

_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)
_SHA_RE = re.compile(r"[0-9a-f]{40}", re.ASCII)
_FALSE_FLAGS = (
    "execution_authorized", "github_writes_authorized", "merge_authorized",
    "scheduler_invoked", "side_effects_performed", "handoff_id_exposed",
)
_BINDING = ("repository", "issue_number", "comment_id", "run_id", "run_attempt", "source_sha", "actor")


class ActionsOperationRefused(ValueError):
    """The request was refused before any store access."""


def _digest(body: Mapping[str, Any]) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(RECEIPT_SCHEMA.encode() + b"\0" + raw).hexdigest()


def _require_int(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ActionsOperationRefused(f"{name} must be a positive integer")
    return value


def admit_transport(
    transport: object, *, expected_repository: str, allowed_actor: str,
    run_id: int, source_sha: str, owning_issue: int | None = None,
) -> dict[str, Any]:
    """Re-check the ingress transport; returns the binding. Refuses on any mismatch."""
    if not isinstance(transport, Mapping):
        raise ActionsOperationRefused("transport missing")
    if not _REPO_RE.fullmatch(expected_repository) or not _SHA_RE.fullmatch(source_sha):
        raise ActionsOperationRefused("expected repository or source sha malformed")
    if transport.get("status") != "accepted" or transport.get("reason") != ENVELOPE_REASON:
        raise ActionsOperationRefused("transport is not an accepted AI Navigation envelope")
    if transport.get("repository") != expected_repository:
        raise ActionsOperationRefused("repository mismatch")
    if transport.get("actor") != allowed_actor:
        raise ActionsOperationRefused("actor not allowed")
    if owning_issue is not None and transport.get("issue_number") != owning_issue:
        raise ActionsOperationRefused("issue is not the owning issue")
    issue = _require_int(transport.get("issue_number"), "issue_number")
    material = f"{expected_repository}\0{issue}\0{OPERATION}".encode("ascii")
    expected_trigger = "issue-comment-trigger:" + hashlib.sha256(material).hexdigest()
    if transport.get("logical_trigger_id_or_none") != expected_trigger:
        raise ActionsOperationRefused("logical trigger id does not match repository, issue and operation")
    return {
        "repository": expected_repository,
        "issue_number": issue,
        "comment_id": _require_int(transport.get("comment_id"), "comment_id"),
        "run_id": _require_int(run_id, "run_id"),
        "run_attempt": _require_int(transport.get("run_attempt"), "run_attempt"),
        "source_sha": source_sha,
        "actor": allowed_actor,
    }


def _receipt(binding: Mapping[str, Any], status: str, reasons: list[str], count: int | None,
             handoff_present: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_name": RECEIPT_SCHEMA, "schema_version": RECEIPT_VERSION,
        **{key: binding[key] for key in _BINDING},
        "status": status, "reason_codes": sorted(set(reasons)),
        "matching_descriptor_count": count, "handoff_present": handoff_present,
        **{flag: False for flag in _FALSE_FLAGS},
    }
    body["receipt_digest"] = _digest(body)
    return body


def run_readonly_discovery(binding: Mapping[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """One bounded read-only lookup. Never runs the locator without a host-configured store root."""
    raw = environ.get(STORE_ROOT_ENV)
    if raw is None or not str(raw).strip():
        return _receipt(binding, "blocked", ["store-root-not-configured"], None, False)
    root = Path(str(raw))
    if not root.is_absolute():
        return _receipt(binding, "blocked", ["store-root-not-absolute"], None, False)
    if not (root / "invocations").is_dir():
        return _receipt(binding, "blocked", ["store-root-has-no-invocations"], None, False)
    try:
        from scripts.agent_os_execution_checkpoint.handoff_discovery import discover_issue_handoff
    except ImportError:  # e.g. PyYAML missing from the interpreter: fail closed with a receipt, never a crash
        return _receipt(binding, "blocked", ["locator-dependency-unavailable"], None, False)

    result = discover_issue_handoff(
        root, repository=binding["repository"], issue_number=binding["issue_number"]
    )
    return _receipt(
        binding, result.status.value, [item.value for item in result.reason_codes],
        result.matching_descriptor_count, result.handoff_id is not None,
    )


_BLOCKED_REASONS = frozenset({
    "store-root-not-configured", "store-root-not-absolute",
    "store-root-has-no-invocations", "locator-dependency-unavailable",
})
_RECEIPT_KEYS = frozenset(
    {"schema_name", "schema_version", *_BINDING, "status", "reason_codes",
     "matching_descriptor_count", "handoff_present", "receipt_digest", *_FALSE_FLAGS}
)


def _is_int(value: object) -> bool:
    return type(value) is int


def _shape_ok(receipt: Mapping[str, Any]) -> str | None:
    """Canonical status/reason/count consistency (mirrors the locator's own result shapes).
    Returns a refusal reason or None. A recomputed digest cannot make a malformed receipt pass."""
    status, reasons, count = receipt.get("status"), receipt.get("reason_codes"), receipt.get("matching_descriptor_count")
    if type(reasons) is not list or len(reasons) != 1 or type(reasons[0]) is not str:
        return "reason-shape-invalid"  # the locator and this module each emit exactly one reason
    reason = reasons[0]
    if status not in ("found", "not-found", "needs-decision", "blocked"):
        return "status-unknown"
    if status == "found":
        ok = reason == "found" and count == 1 and _is_int(count) and receipt.get("handoff_present") is True
        return None if ok else "found-inconsistent"
    if receipt.get("handoff_present") is not False:
        return "non-found-exposes-handoff"
    if status == "not-found":
        return None if reason == "no-matching-descriptor" and _is_int(count) and count == 0 else "not-found-inconsistent"
    if status == "needs-decision":
        if reason in ("store-unavailable", "store-bound-exceeded"):
            ok = _is_int(count) and count == 0
        elif reason == "multiple-matching-descriptors":
            ok = _is_int(count) and count >= 2
        elif reason == "descriptor-integrity-unverified":
            ok = _is_int(count) and count >= 0
        else:
            ok = False
        return None if ok else "needs-decision-inconsistent"
    if status == "blocked":
        return None if reason in _BLOCKED_REASONS and count is None else "blocked-inconsistent"
    return "status-unknown"


def verify_receipt(receipt: object, *, expected_binding: Mapping[str, Any]) -> tuple[bool, str]:
    """Consistency and binding check a retriever can run. (ok, reason); any doubt is not ok.

    TRUST LABEL: the digest is unkeyed, so anyone can recompute it. A pass means the receipt is
    well-formed, canonically consistent and bound to the expected request. It does NOT show who
    produced it or that the runner actually ran. Authenticity would have to come from retrieving
    the receipt through the workflow run (run id, workflow path, head SHA read from GitHub); that
    retrieval is NOT implemented here and is unproven for ChatGPT's connector.
    """
    if not isinstance(receipt, Mapping):
        return False, "receipt-missing"
    if receipt.get("schema_name") != RECEIPT_SCHEMA or receipt.get("schema_version") != RECEIPT_VERSION:
        return False, "schema-mismatch"
    if set(receipt) != _RECEIPT_KEYS:
        return False, "unexpected-or-missing-fields"
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if receipt.get("receipt_digest") != _digest(body):
        return False, "digest-mismatch"
    for key in _BINDING:
        got, want = receipt.get(key), expected_binding.get(key)
        if got != want or type(got) is not type(want):
            return False, f"binding-mismatch:{key}"
    if any(receipt.get(flag) is not False for flag in _FALSE_FLAGS):
        return False, "authority-flag-not-false"
    bad = _shape_ok(receipt)
    return (False, bad) if bad else (True, "verified")


def check_artifact_listing(pages: object, *, per_page: int = 100) -> tuple[bool, str]:
    """Complete only if every page was read and the item count equals the reported total.

    NOT IMPLEMENTED beyond this pure check: nothing calls it, no endpoint or run binding is
    defined, and no artifact transport has been chosen. It exists so a future caller fails closed.
    """
    if not isinstance(pages, list) or not pages or not all(isinstance(p, Mapping) for p in pages):
        return False, "listing-missing"
    totals = {p.get("total_count") for p in pages}
    if len(totals) != 1 or type(next(iter(totals))) is not int:
        return False, "total-count-inconsistent"
    total = next(iter(totals))
    items = [p.get("artifacts") for p in pages]
    if not all(isinstance(i, list) for i in items):
        return False, "page-malformed"
    if any(len(i) > per_page for i in items) or any(len(i) < per_page for i in items[:-1]):
        return False, "page-size-inconsistent"
    if sum(len(i) for i in items) != total:
        return False, "listing-incomplete"
    ids = [a.get("id") for i in items for a in i if isinstance(a, Mapping)]
    if len(ids) != total or len(set(ids)) != total:
        return False, "artifact-ids-duplicate-or-missing"
    return True, "complete"


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Workflow entry. Always writes a receipt (exit 0) for a well-formed admitted request;
    a refused request writes nothing and exits 2."""
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.transport.stat().st_size > 65536:
            raise ActionsOperationRefused("transport exceeds byte bound")
        transport = json.loads(args.transport.read_text(encoding="utf-8"))
        binding = admit_transport(
            transport, expected_repository=args.repository, allowed_actor=args.allowed_actor,
            run_id=args.run_id, source_sha=args.source_sha,
        )
    except (ActionsOperationRefused, OSError, ValueError) as exc:
        print(f"refused: {type(exc).__name__}", file=sys.stderr)
        return 2
    receipt = run_readonly_discovery(binding, os.environ if environ is None else environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
