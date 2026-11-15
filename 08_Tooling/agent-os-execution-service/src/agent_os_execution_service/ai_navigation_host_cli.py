"""Local validation-only caller for the AI Navigation trusted host (local candidate).

Run as ``python -m agent_os_execution_service.ai_navigation_host_cli --handoff-id ID --work FILE``.
It is not a console script, is not registered anywhere, and installing the package
does not run it. It composes the *existing* canonical host owners for one durable
handoff and then calls ``run_trusted_host_navigation`` exactly once:

* host state, runtime request and descriptor: ``build_production_host_bootstrap_for_handoff``
  (the same composition governed resume uses; it needs the host environment and, when
  it reads authorization, a credentialed GitHub read transport supplied by that owner);
* current evidence (route decision, handoff, checkpoint, resume plan, candidate packet,
  runtime configuration, dependency readiness, owner authorization, pilot input):
  ``CanonicalCurrentInvocationResolver.reacquire``;
* routing ids: ``invocation_routing_evidence_provider`` over that same evidence.

Nothing is defaulted or invented: host locations come only from required environment
variables, a missing or inconsistent input refuses, and no fixture, in-memory transport
or placeholder is used on this path. Authorization is validation-only; mutation, merge,
publication and GitHub writes are not reachable. A CKR6 read transport is not supplied,
so knowledge-material work refuses at that stage (named gap, not defaulted).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .ai_navigation_invocation_routing import invocation_routing_evidence_provider
from .ai_navigation_pathway import FileReceiptSink, NavigationExecutionHost
from .ai_navigation_trusted_host import DispatchJournal, TrustedHostComposition, run_trusted_host_navigation

JOURNAL_DIR_ENV = "AOS_AI_NAV_JOURNAL_DIR"
RECEIPT_PATH_ENV = "AOS_AI_NAV_RECEIPT_PATH"
REGISTRY_DIR_ENV = "AOS_AI_NAV_REGISTRY_DIR"
CAPABILITY_REGISTRY_ENV = "AOS_AI_NAV_CAPABILITY_REGISTRY"
_REQUIRED_ENV = (JOURNAL_DIR_ENV, RECEIPT_PATH_ENV, REGISTRY_DIR_ENV, CAPABILITY_REGISTRY_ENV)

EXIT_COMPLETED = 0
EXIT_REFUSED = 2


class NavigationCallerError(RuntimeError):
    """The trusted composition could not be built safely; nothing was dispatched."""


def _absolute(environ: Mapping[str, str], name: str) -> Path:
    raw = environ.get(name)
    if raw is None or not str(raw).strip():
        raise NavigationCallerError(f"{name} must be set to an absolute host path; no default is invented")
    path = Path(str(raw))
    if not path.is_absolute():
        raise NavigationCallerError(f"{name} must be an absolute path")
    return path


def _failure_chain(exc: BaseException) -> str:
    """Exception class names only (outermost to root cause); never messages, paths or values."""
    names: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(names) < 6:
        seen.add(id(current))
        names.append(type(current).__name__)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return " <- ".join(names)


def compose_from_current_evidence(
    *,
    descriptor: Any,
    evidence: Any,
    evaluated_at_moment: datetime,
    transport: Any,
    environ: Mapping[str, str],
    execute_read: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> TrustedHostComposition:
    """Pure composition from already-reacquired canonical evidence."""
    from scripts.agent_os_candidate_packet.models import candidate_packet_id

    locations = {name: _absolute(environ, name) for name in _REQUIRED_ENV}
    route_decision = evidence.route_decision
    host = NavigationExecutionHost(
        pilot_input=evidence.pilot_input,
        configuration=evidence.runtime_configuration,
        cancelled=lambda: False,  # same host-owned "no cancellation requested" as the production factory
    )
    return TrustedHostComposition(
        clock=lambda: evaluated_at_moment,
        transport=transport,
        candidate_packet_id=candidate_packet_id(evidence.candidate_packet),
        invocation_id=descriptor.invocation_id,
        operation=route_decision.requested_operation,
        host=host,
        routing_evidence_provider=invocation_routing_evidence_provider(
            descriptor, lambda _d: route_decision, clock=lambda: evaluated_at_moment
        ),
        registry_dir=locations[REGISTRY_DIR_ENV],
        capability_registry_path=locations[CAPABILITY_REGISTRY_ENV],
        receipt_sink=FileReceiptSink(locations[RECEIPT_PATH_ENV]),
        journal=DispatchJournal(locations[JOURNAL_DIR_ENV]),
        execute_read=execute_read,
    )


def build_composition_for_handoff(
    handoff_id: str,
    environ: Mapping[str, str] | None = None,
    *,
    bootstrap_factory: Callable[..., Any] | None = None,
    resolver_class: Any = None,
) -> TrustedHostComposition:
    environ = os.environ if environ is None else environ
    for name in _REQUIRED_ENV:  # fail before touching any host source
        _absolute(environ, name)
    from .current_invocation_resolver import CanonicalCurrentInvocationResolver
    from .models import parse_canonical_utc
    from .production_governed_resume_factory import build_production_host_bootstrap_for_handoff

    factory = bootstrap_factory or build_production_host_bootstrap_for_handoff
    resolver_class = resolver_class or CanonicalCurrentInvocationResolver
    try:
        bootstrap = factory(handoff_id)
        runtime_request = getattr(bootstrap, "runtime_request", None)
        descriptor = getattr(runtime_request, "invocation_descriptor", None)
        if descriptor is None:
            raise NavigationCallerError("host bootstrap has no runtime request or invocation descriptor for this handoff")
        evidence = resolver_class(
            sources=bootstrap.sources,
            authorization_transport=bootstrap.authorization_transport,
            evaluated_at=bootstrap.evaluated_at,
        ).reacquire(descriptor)
        return compose_from_current_evidence(
            descriptor=descriptor,
            evidence=evidence,
            evaluated_at_moment=parse_canonical_utc(bootstrap.evaluated_at),
            transport=bootstrap.authorization_transport,
            environ=environ,
        )
    except NavigationCallerError:
        raise
    except Exception as exc:  # noqa: BLE001 - every composition failure refuses, none dispatches
        raise NavigationCallerError(f"host composition failed closed: {_failure_chain(exc)}") from exc


def _refusal(reason: str, *extra: str) -> dict[str, Any]:
    return {
        "status": "request-rejected",
        "execution_attempted": False,
        "receipt_persisted": False,
        "reason_codes": [reason, *extra],
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    composition_builder: Callable[[str], TrustedHostComposition] | None = None,
    stdout: Any = None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out = stdout or sys.stdout
    handoff_id = work_path = None
    try:
        if len(argv) != 4 or argv[0] != "--handoff-id" or argv[2] != "--work":
            raise NavigationCallerError("usage: --handoff-id ID --work FILE")
        handoff_id, work_path = argv[1], argv[3]
        try:
            payload = json.loads(Path(work_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise NavigationCallerError(f"work file unreadable: {type(exc).__name__}") from exc
        builder = composition_builder or (lambda hid: build_composition_for_handoff(hid, environ))
        composition = builder(handoff_id)
        result = run_trusted_host_navigation(payload, composition)
    except NavigationCallerError as exc:
        result = _refusal("host-composition-refused", str(exc))
    except Exception as exc:  # noqa: BLE001
        result = _refusal("host-composition-error", type(exc).__name__)
    print(json.dumps(result, sort_keys=True, default=str), file=out)
    ok = result.get("status") == "completed" and bool(result.get("receipt_persisted"))
    return EXIT_COMPLETED if ok else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
