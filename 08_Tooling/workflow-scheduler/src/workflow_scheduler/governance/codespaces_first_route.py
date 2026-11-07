"""Resolve the existing governed invocation transport without provider fallback.

Discovery, developer validation, and diagnostics are Codespaces-only. A missing,
stale, unauthorized, or incapable Codespace produces bounded failure evidence;
it never grants an alternate GCE attempt. Unsupported validation profiles remain
blocked until separately qualified. This implements the Codespaces-first owner
decision on #3333 (2026-10-14); #3102 still owns permanent GCE decommission.

Explicit fixed-host envelopes retain their existing GCE boundary. Selection is
non-authorizing: each adapter still owns identity, currentness, and capability
checks. The retained false fallback field preserves the route evidence schema.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# Ordinary developer-loop requests never inherit VM transport authority.
CODESPACES_PREFERRED_REASONS = frozenset(
    {
        "accepted-discovery-envelope",
        "accepted-dev-validation-envelope",
        "accepted-codespaces-diagnostic-envelope",
    }
)

# Envelopes bound to concrete VM-only capabilities under #2300. These never
# prefer Codespaces; the GCE transport is required until the capability
# itself is retired or migrated by its own handoff.
#
# NOTE (#3101/PR #3233): first-run validation was retired — no transport can
# perform it anymore. "accepted-first-run-validation-envelope" is deliberately
# absent here, so it resolves to preferred="none" (route-unknown-envelope) and
# the governed invocation workflow fails closed instead of routing the envelope
# to a transport that can no longer carry it.
GCE_REQUIRED_REASONS = {
    "accepted-runtime-inspection-envelope": "gce-required-fixed-host",
    "accepted-ruleset-admin-envelope": "gce-required-ruleset-admin",
    "accepted-first-publication-activation-envelope": "gce-required-activation",
    "accepted-ppux-projection-envelope": "gce-required-ppux-projection",
    "accepted-notion-read-envelope": "gce-required-notion-read",
    # Generic handoff envelopes execute through the governed GCE control path
    # (Scheduler invocation included) until the #3101 retirement handoffs
    # remove that capability through their own bounded change requests.
    "accepted-envelope": "gce-required-governed-control",
}


def resolve_ingress_route(transport: dict[str, Any]) -> dict[str, Any]:
    """Resolve the preferred provider transport for an ingress envelope.

    Returns a route dict with ``preferred`` ("codespaces", "gce", or "none"),
    ``gce_fallback_allowed``, and ``reason_codes``. Non-accepted or unknown
    envelopes resolve to ``preferred="none"`` so the caller fails closed.
    """
    reason = transport.get("reason")
    status = transport.get("status")

    if status != "accepted" or not isinstance(reason, str):
        return {
            "schema_version": SCHEMA_VERSION,
            "preferred": "none",
            "gce_fallback_allowed": False,
            "reason_codes": ["route-no-accepted-envelope"],
            "operation": transport.get("operation"),
        }

    if reason in CODESPACES_PREFERRED_REASONS:
        return {
            "schema_version": SCHEMA_VERSION,
            "preferred": "codespaces",
            "gce_fallback_allowed": False,
            "reason_codes": ["codespaces-first-ordinary-operation"],
            "operation": transport.get("operation"),
        }

    gce_reason = GCE_REQUIRED_REASONS.get(reason)
    if gce_reason is not None:
        return {
            "schema_version": SCHEMA_VERSION,
            "preferred": "gce",
            "gce_fallback_allowed": False,
            "reason_codes": [gce_reason],
            "operation": transport.get("operation"),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "preferred": "none",
        "gce_fallback_allowed": False,
        "reason_codes": ["route-unknown-envelope"],
        "operation": transport.get("operation"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--route-output", type=Path, required=True)
    args = parser.parse_args(argv)
    transport = json.loads(args.transport.read_text(encoding="utf-8"))
    route = resolve_ingress_route(transport)
    args.route_output.parent.mkdir(parents=True, exist_ok=True)
    args.route_output.write_text(
        json.dumps(route, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(route, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
