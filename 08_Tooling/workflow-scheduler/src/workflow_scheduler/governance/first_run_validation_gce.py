"""Fixed GitHub-to-GCE first-run validation transport for #1972/#2431.

The transport carries exactly one immutable selector: the 40-hex candidate SHA
from ``/agent-os validate-first-run <candidate-sha>``. Repository and issue
identity come from the trusted GitHub event envelope, never from comment text.

This module reuses the existing #1217 GCE lifecycle adapter. A stopped host is
started at most once and waited to RUNNING before the fixed validation probe.
It defines no argv surface, second transport, retry, Scheduler admission,
publication path, or independent shutdown authority.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Mapping

from .gce_control_path import VmState
from .gce_gcloud_adapter import (
    GcloudCommandError,
    GcloudIapAdapter,
    RESOURCE,
    _ingress_from_file,
    _policy,
)
from .github_issue_comment_ingress import IssueCommentIngressResult

FIRST_RUN_TRANSPORT_SCHEMA_VERSION = "1.0"
FIRST_RUN_ACCEPTED_REASON = "accepted-first-run-validation-envelope"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)


def _failure(
    reason: str,
    *,
    repository: str,
    issue_number: object,
    candidate_sha: object,
    status: str = "needs-decision",
    host_started: bool = False,
) -> dict[str, object]:
    """One bounded non-authorizing first-run transport envelope."""
    return {
        "schema_version": FIRST_RUN_TRANSPORT_SCHEMA_VERSION,
        "status": status,
        "reason_codes": [reason],
        "repository": repository,
        "issue_number": issue_number,
        "candidate_sha": candidate_sha,
        "host_started": host_started,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "publication_invoked": False,
        "execution_lease_acquired": False,
        "resume_invoked": False,
        "shutdown_issued": False,
        "retry_attempted": False,
        "merge_authorized": False,
        "github_writes_authorized": False,
        "side_effects_performed": host_started,
    }


def execute_first_run_validation_transport(
    ingress: IssueCommentIngressResult,
    *,
    claims: Mapping[str, object],
    adapter: GcloudIapAdapter,
) -> dict[str, object]:
    """Route one accepted first-run envelope to the fixed host operation only."""
    if type(ingress) is not IssueCommentIngressResult:
        raise TypeError("ingress must be exact IssueCommentIngressResult")
    if ingress.status != "accepted" or ingress.reason != FIRST_RUN_ACCEPTED_REASON:
        raise ValueError("first-run validation requires accepted canonical ingress evidence")
    if ingress.run_attempt != 1:
        raise ValueError("workflow reruns cannot perform first-run validation")
    if (
        ingress.handoff_id_or_none is not None
        or ingress.source_capsule_id_or_none is not None
        or ingress.dev_validation_id_or_none is not None
        or ingress.notion_read_request_id_or_none is not None
    ):
        raise ValueError("first-run validation must not carry another operation identity")
    if ingress.issue_number is None or ingress.logical_trigger_id_or_none is None:
        raise ValueError("first-run validation ingress identity incomplete")

    repository = ingress.repository
    issue_number = ingress.issue_number
    candidate_sha = ingress.first_run_candidate_sha_or_none
    if type(candidate_sha) is not str or _SHA40_RE.fullmatch(candidate_sha) is None:
        return {
            "first_run_validation": _failure(
                "first-run-candidate-sha-invalid",
                repository=repository,
                issue_number=issue_number,
                candidate_sha=candidate_sha if type(candidate_sha) is str else None,
                status="blocked",
            )
        }

    bounds = {
        "repository": repository,
        "issue_number": issue_number,
        "candidate_sha": candidate_sha,
    }
    if not _policy().accepts(claims):
        return {"first_run_validation": _failure("claims-rejected", status="blocked", **bounds)}

    initial_state = adapter.observe_state(RESOURCE)
    host_started = False
    if initial_state is VmState.STOPPED:
        if adapter.start(RESOURCE) is not True:
            return {"first_run_validation": _failure("vm-start-failed", **bounds)}
        host_started = True
        state = adapter.wait_until_running(RESOURCE)
    else:
        state = initial_state
    if state is not VmState.RUNNING:
        return {
            "first_run_validation": _failure(
                "host-not-running", host_started=host_started, **bounds
            )
        }
    if not adapter.probe_first_run_validation_ready(RESOURCE):
        return {
            "first_run_validation": _failure(
                "first-run-validation-entrypoint-unavailable",
                host_started=host_started,
                **bounds,
            )
        }
    try:
        evidence = adapter.validate_first_run(
            RESOURCE,
            repository=repository,
            issue_number=issue_number,
            candidate_sha=candidate_sha,
        )
    except GcloudCommandError:
        return {
            "first_run_validation": _failure(
                "first-run-validation-host-failed", host_started=host_started, **bounds
            )
        }
    evidence = dict(evidence)
    evidence["host_started"] = host_started
    return {
        "first_run_validation": evidence,
        "logical_trigger_id": ingress.logical_trigger_id_or_none,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("repository", "repository-owner", "workflow-ref", "ref", "audience"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    claims = {
        "repository": args.repository,
        "repository_owner": args.repository_owner,
        "workflow_ref": args.workflow_ref,
        "ref": args.ref,
        "aud": args.audience,
    }
    evidence = execute_first_run_validation_transport(
        _ingress_from_file(args.transport), claims=claims, adapter=GcloudIapAdapter()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


__all__ = ["execute_first_run_validation_transport"]

if __name__ == "__main__":
    raise SystemExit(main())
