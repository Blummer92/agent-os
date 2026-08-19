"""Fixed read-only handoff-discovery entrypoint for Agent OS hosts (#1284).

This is the host-side half of the #1284 binding. It exists so an execution
interface that knows only a repository and an issue number can learn which
immutable ``executor-handoff:<sha256>`` already exists for that issue, without
the interface itself reading the canonical checkpoint store and without any
chat text, issue prose, branch name, or tool output being able to manufacture a
handoff identity.

The contract is deliberately the narrowest thing that can answer that question:

```text
--repository <owner/name> --issue-number <positive int>
-> canonical #1242 discover_issue_handoff(...)
-> bounded found | not-found | needs-decision projection on stdout
```

The checkpoint-store root is host composition, read from
``AGENT_OS_CHECKPOINT_STORE_ROOT``. It is never a command-line argument, so a
caller cannot point discovery at a store it chose. An unset or blank variable is
unavailable evidence, not a default path to invent.

This module never writes the store, never creates or persists a handoff, never
chooses between candidate descriptors, never acquires a lease, and never invokes
the Scheduler. A ``found`` answer is identity evidence only: it must still pass
the existing #1218 reconstruction/currentness/admission path before anything
executes.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Mapping, Sequence

from scripts.agent_os_execution_checkpoint.handoff_discovery import (
    HANDOFF_DISCOVERY_SCHEMA_NAME,
    HANDOFF_DISCOVERY_SCHEMA_VERSION,
    InvocationHandoffDiscoveryResult,
    discover_issue_handoff,
)

STORE_ROOT_ENV = "AGENT_OS_CHECKPOINT_STORE_ROOT"
STORE_NOT_CONFIGURED_REASON = "store-not-configured"
INVALID_REQUEST_REASON = "invalid-request"
MAX_ARGUMENT_BYTES = 512


class DiscoveryRequestError(ValueError):
    """Raised when argv is not exactly one canonical repository/issue pair."""


def parse_discovery_argv(argv: Sequence[str]) -> tuple[str, int]:
    """Accept exactly ``--repository <owner/name> --issue-number <positive>``.

    Nothing else is accepted: no store root, path, handoff, branch, flag,
    ordering variation, or extra token.
    """
    if type(argv) not in (list, tuple):
        raise TypeError("argv must be a list or tuple")
    if len(argv) != 4 or argv[0] != "--repository" or argv[2] != "--issue-number":
        raise DiscoveryRequestError(
            "expected exactly --repository <owner/name> --issue-number <positive int>"
        )
    repository = argv[1]
    raw_issue = argv[3]
    for value in (repository, raw_issue):
        if type(value) is not str or len(value.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise DiscoveryRequestError("arguments must be bounded text")
    if type(raw_issue) is not str or not raw_issue.isdigit():
        raise DiscoveryRequestError("issue number must be decimal digits")
    issue_number = int(raw_issue)
    if issue_number < 1:
        raise DiscoveryRequestError("issue number must be positive")
    # Repository syntax itself is validated by the canonical locator, which
    # raises for anything that is not owner/name. Re-implementing that check
    # here would create a second vocabulary for the same rule.
    return repository, issue_number


def resolve_store_root(environ: Mapping[str, str]) -> str | None:
    """Read the host-fixed checkpoint-store root, or ``None`` when unset."""
    value = environ.get(STORE_ROOT_ENV)
    if type(value) is not str or not value.strip():
        return None
    return value


def _projection(result: InvocationHandoffDiscoveryResult) -> dict[str, object]:
    return {
        "schema_name": result.schema_name,
        "schema_version": result.schema_version,
        "result_id": result.result_id,
        "status": result.status.value,
        "reason_codes": [item.value for item in result.reason_codes],
        "repository": result.repository,
        "issue_number": result.issue_number,
        "matching_descriptor_count": result.matching_descriptor_count,
        "handoff_id": result.handoff_id,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }


def _fail_closed(
    *,
    reason: str,
    repository: str | None,
    issue_number: int | None,
) -> dict[str, object]:
    """Return a bounded ``needs-decision`` projection with no handoff identity.

    Failures before the locator runs still answer in the same shape, so the
    transport has one result vocabulary to parse. ``result_id`` is absent
    because no canonical #1242 result was produced.
    """
    return {
        "schema_name": HANDOFF_DISCOVERY_SCHEMA_NAME,
        "schema_version": HANDOFF_DISCOVERY_SCHEMA_VERSION,
        "result_id": None,
        "status": "needs-decision",
        "reason_codes": [reason],
        "repository": repository,
        "issue_number": issue_number,
        "matching_descriptor_count": None,
        "handoff_id": None,
        "execution_authorized": False,
        "scheduler_invoked": False,
        "side_effects_performed": False,
    }


def run_handoff_discovery(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str],
) -> str:
    """Resolve one repository/issue pair to bounded canonical discovery JSON."""
    try:
        repository, issue_number = parse_discovery_argv(argv)
    except (DiscoveryRequestError, TypeError):
        return json.dumps(
            _fail_closed(
                reason=INVALID_REQUEST_REASON, repository=None, issue_number=None
            ),
            sort_keys=True,
            separators=(",", ":"),
        )

    store_root = resolve_store_root(environ)
    if store_root is None:
        return json.dumps(
            _fail_closed(
                reason=STORE_NOT_CONFIGURED_REASON,
                repository=repository,
                issue_number=issue_number,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )

    try:
        result = discover_issue_handoff(
            store_root, repository=repository, issue_number=issue_number
        )
    except (TypeError, ValueError):
        # A malformed repository never becomes a store scan or a guess.
        return json.dumps(
            _fail_closed(
                reason=INVALID_REQUEST_REASON,
                repository=None,
                issue_number=issue_number,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
    return json.dumps(
        _projection(result), sort_keys=True, separators=(",", ":")
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI path: print exactly one bounded discovery projection to stdout."""
    if argv is None:
        argv = sys.argv[1:]
    print(run_handoff_discovery(argv, environ=os.environ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
