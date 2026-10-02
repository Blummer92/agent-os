"""Codespaces-first transport route resolution for #2931.

This module decides which provider transport an accepted governed invocation
should consume, from the operation's capability requirements — instead of the
ingress unconditionally entering ``gce_gcloud_adapter``.

Route selection follows the #2299 / #2300 split:

- Codespaces is preferred for ordinary developer-loop operations (discovery,
  developer validation, bounded diagnostics) when a current/capable Codespace
  is selected from live evidence.
- GCE remains the required transport for concrete VM-only capabilities:
  #759 containment, Scheduler/unattended execution, fixed service identity,
  runtime inspection against the fixed host, first-run validation,
  ruleset administration, first-publication activation, and PPUX projection.

The resolver is a pure function of the accepted ingress envelope. It performs
no network access, starts no transport, and manufactures no authority: a
``codespaces`` preference still requires the Codespaces adapter to select a
current surface from live evidence, otherwise the workflow falls back through
the existing GCE path. When no capable authorized route exists, the resolver
returns ``preferred="none"`` so the caller fails closed with one explicit
bounded blocker.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"

# Envelopes whose operations are ordinary developer-loop work: Codespaces is
# preferred when a current/capable surface is selected, GCE remains the
# fallback when Codespaces evidence is stale, unavailable, or insufficient.
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
            "gce_fallback_allowed": True,
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
