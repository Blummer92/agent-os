"""One bounded live identity-verification seam for #2283 activation.

This module exists only to bootstrap the already-authorized catalog bindings.
It reuses the canonical #936 ``NotionReadOnlyAdapter`` and preserves the
original exact Photography Foundations bootstrap. #2816 additionally provides a pure helper for one finite exact-title lookup
inside the already-verified Canonical Digital Media Unit Registry for a
repository-declared unverified canonical unit. The helper returns identity
evidence only; this change does not route or execute that live query. Normal
curriculum/asset reads remain fail-closed until the verified identity is
deliberately bound in the catalog.

It does not query arbitrary data sources or properties, mutate Notion, write
Drive/classroom artifacts, broaden workspace access, or create a second Notion
client.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_os_notion_binding import NotionBindingError, build_read_task, new_read_adapter

from .models import INGRESS_REASON, SCHEMA_VERSION, NotionReadRequestError
from .runner import MAX_TRANSPORT_BYTES

VERIFICATION_REQUEST_ID = "verify-photography-foundations-bindings"
VERIFICATION_ISSUE_NUMBER = 2283

CANONICAL_REGISTRY_DATABASE_ID = "f7f22d33-e1ef-4932-b294-cbe39b24a39a"
CANONICAL_REGISTRY_TITLE = "Canonical Digital Media Unit Registry"
VISUAL_ASSET_LIBRARY_DATABASE_ID = "21783abc-55de-49a4-a87c-94656fff0400"
VISUAL_ASSET_LIBRARY_TITLE = "Visual Asset Library"
PHOTOGRAPHY_FOUNDATIONS_PAGE_ID = "3907ac78-3131-8129-8c73-cd9f6b8e8a7d"
CANDY_BRANDING_UNIT_KEY = "candy-branding"
CANDY_BRANDING_STABLE_ID = "canonical-unit-candy-branding"
CANDY_BRANDING_TITLE = "Candy Branding / Candy Brand Design"
CANDY_BRANDING_VERIFICATION_REQUEST_ID = "verify-candy-branding-binding"
CANDY_BRANDING_VERIFICATION_ISSUE_NUMBER = 2816

_ALLOWED_ACTIONS = ("get_database", "get_page")


def _normalize_notion_id(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("-", "").lower()


def admit_binding_verification_request(
    transport: object,
    *,
    expected_repository: str,
    expected_actor: str,
) -> dict[str, object]:
    """Admit only the exact owner-authorized #2283 bootstrap request."""

    reason = "admitted"
    authorized = True
    issue_number: int | None = None

    if not isinstance(transport, Mapping):
        reason, authorized = "transport-malformed", False
    elif transport.get("status") != "accepted":
        reason, authorized = "transport-not-accepted", False
    elif transport.get("reason") != INGRESS_REASON:
        reason, authorized = "transport-reason-mismatch", False
    elif any(
        transport.get(claim) is not False
        for claim in ("execution_authorized", "scheduler_invoked", "side_effects_performed")
    ):
        reason, authorized = "transport-claims-authority", False
    elif transport.get("repository") != expected_repository:
        reason, authorized = "repository-mismatch", False
    elif type(transport.get("run_attempt")) is not int or transport.get("run_attempt") != 1:
        reason, authorized = "run-attempt-replay", False
    elif transport.get("actor") != expected_actor:
        reason, authorized = "actor-not-allowed", False
    elif transport.get("notion_read_request_id_or_none") != VERIFICATION_REQUEST_ID:
        reason, authorized = "verification-request-mismatch", False
    elif type(transport.get("issue_number")) is not int:
        reason, authorized = "issue-target-mismatch", False
    else:
        issue_number = int(transport["issue_number"])
        if issue_number != VERIFICATION_ISSUE_NUMBER:
            reason, authorized = "issue-target-mismatch", False

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "admitted" if authorized else "rejected",
        "reason_codes": [reason],
        "repository": expected_repository,
        "issue_number": issue_number,
        "request_id": VERIFICATION_REQUEST_ID,
        "request_class": "binding-verification",
        "canonical_unit_key": "photography-foundations",
        "allowed_read_actions": list(_ALLOWED_ACTIONS),
        "secret_dispatch_authorized": authorized,
        "write_allowed": False,
        "production_authorized": False,
        "notion_write_reachable": False,
        "gce_required": False,
    }




def _execute_read(adapter: object, action: str, **payload: object) -> dict[str, Any]:
    execute = getattr(adapter, "execute", None)
    if not callable(execute):
        raise TypeError("adapter must expose execute(task)")

    task = build_read_task(
        task_id=f"agent-os-notion-binding-verification-{action}",
        workflow_id="agent-os-notion-binding-verification",
        owner="agent-os-notion-read-request",
        action=action,
        idempotency_key=f"agent-os-notion-binding-verification-{action}-{len(payload)}",
        payload={"action": action, **payload},
    )
    result = execute(task)
    if not isinstance(result, Mapping):
        raise NotionReadRequestError("Notion verification adapter returned malformed evidence")
    if result.get("status") != "success":
        message = result.get("message")
        raise NotionReadRequestError(
            f"Notion verification read failed: {message if isinstance(message, str) else 'unknown error'}"
        )
    output = result.get("output")
    if not isinstance(output, Mapping):
        raise NotionReadRequestError("Notion verification read returned malformed output")
    return dict(output)



def _execute_registry_query(
    adapter: object,
    *,
    data_source_id: str,
    exact_title: str,
) -> list[dict[str, Any]]:
    """Query one verified registry source by one repository-owned exact title."""

    output = _execute_read(
        adapter,
        "query_data_source",
        data_source_id=data_source_id,
        filter={"property": "Name", "title": {"equals": exact_title}},
        page_size=2,
        max_pages=1,
        max_results=2,
    )
    results = output.get("results")
    if not isinstance(results, list) or any(not isinstance(item, Mapping) for item in results):
        raise NotionReadRequestError("canonical-unit verification returned malformed results")
    return [dict(item) for item in results]


def verify_candy_branding_binding(
    adapter: object,
    *,
    canonical_registry_data_source_id: str,
    generated_at: str,
) -> dict[str, object]:
    """Discover one exact Candy Branding page identity without making it dispatchable."""

    if not isinstance(canonical_registry_data_source_id, str) or not canonical_registry_data_source_id.strip():
        raise NotionReadRequestError("canonical registry data source id is missing")

    matches = _execute_registry_query(
        adapter,
        data_source_id=canonical_registry_data_source_id.strip(),
        exact_title=CANDY_BRANDING_TITLE,
    )
    if len(matches) != 1:
        raise NotionReadRequestError("Candy Branding canonical-unit identity is missing or ambiguous")

    page = matches[0]
    page_id = page.get("id")
    if not isinstance(page_id, str) or not page_id.strip():
        raise NotionReadRequestError("Candy Branding canonical-unit page id is missing")
    if page.get("archived") is True or page.get("in_trash") is True:
        raise NotionReadRequestError("Candy Branding canonical page is archived or trashed")

    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": CANDY_BRANDING_VERIFICATION_REQUEST_ID,
        "dispatch_status": "completed",
        "dispatch_reason": "canonical-unit-binding-verification-complete",
        "canonical_unit": {
            "canonical_unit_key": CANDY_BRANDING_UNIT_KEY,
            "stable_id": CANDY_BRANDING_STABLE_ID,
            "provider_page_id": page_id.strip(),
            "verification_state": "verified-current",
        },
        "notion_writes_performed": False,
        "drive_writes_performed": False,
        "classroom_artifact_writes_performed": False,
        "gce_invoked": False,
        "generated_at": generated_at,
    }


def _verified_database(
    adapter: object,
    *,
    database_id: str,
    expected_title: str,
) -> dict[str, object]:
    output = _execute_read(adapter, "get_database", database_id=database_id)
    if _normalize_notion_id(output.get("id")) != _normalize_notion_id(database_id):
        raise NotionReadRequestError(f"{expected_title} database identity mismatch")
    if output.get("title") != expected_title:
        raise NotionReadRequestError(f"{expected_title} title mismatch")
    if output.get("archived") is True or output.get("in_trash") is True:
        raise NotionReadRequestError(f"{expected_title} is archived or trashed")

    raw_sources = output.get("data_sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise NotionReadRequestError(f"{expected_title} exposes no data source identity")
    sources = [item for item in raw_sources if isinstance(item, Mapping)]
    if len(sources) != len(raw_sources):
        raise NotionReadRequestError(f"{expected_title} data source evidence is malformed")

    if len(sources) == 1:
        selected = sources[0]
    else:
        named = [item for item in sources if item.get("name") == expected_title]
        if len(named) != 1:
            raise NotionReadRequestError(
                f"{expected_title} data source identity is ambiguous"
            )
        selected = named[0]

    data_source_id = selected.get("id")
    if not isinstance(data_source_id, str) or not data_source_id.strip():
        raise NotionReadRequestError(f"{expected_title} data source id is missing")

    return {
        "database_id": database_id,
        "title": expected_title,
        "data_source_id": data_source_id,
        "verification_state": "verified-current",
    }


def verify_live_bindings(adapter: object, *, generated_at: str) -> dict[str, object]:
    """Return sanitized current identities from exactly three live Notion reads."""

    canonical_registry = _verified_database(
        adapter,
        database_id=CANONICAL_REGISTRY_DATABASE_ID,
        expected_title=CANONICAL_REGISTRY_TITLE,
    )
    visual_asset_library = _verified_database(
        adapter,
        database_id=VISUAL_ASSET_LIBRARY_DATABASE_ID,
        expected_title=VISUAL_ASSET_LIBRARY_TITLE,
    )
    page = _execute_read(adapter, "get_page", page_id=PHOTOGRAPHY_FOUNDATIONS_PAGE_ID)
    if _normalize_notion_id(page.get("id")) != _normalize_notion_id(PHOTOGRAPHY_FOUNDATIONS_PAGE_ID):
        raise NotionReadRequestError("Photography Foundations page identity mismatch")
    if page.get("archived") is True or page.get("in_trash") is True:
        raise NotionReadRequestError("Photography Foundations canonical page is archived or trashed")

    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": VERIFICATION_REQUEST_ID,
        "dispatch_status": "completed",
        "dispatch_reason": "binding-verification-complete",
        "canonical_registry": canonical_registry,
        "visual_asset_library": visual_asset_library,
        "photography_foundations": {
            "provider_page_id": PHOTOGRAPHY_FOUNDATIONS_PAGE_ID,
            "verification_state": "verified-current",
        },
        "notion_writes_performed": False,
        "drive_writes_performed": False,
        "classroom_artifact_writes_performed": False,
        "gce_invoked": False,
        "generated_at": generated_at,
    }


def _read_transport(path: Path) -> object:
    if path.stat().st_size > MAX_TRANSPORT_BYTES:
        raise NotionReadRequestError("transport evidence exceeds byte bound")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-actor", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    transport = _read_transport(args.transport)
    admission = admit_binding_verification_request(
        transport,
        expected_repository=args.repository,
        expected_actor=args.allowed_actor,
    )
    if admission["secret_dispatch_authorized"] is not True:
        evidence: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "admission": admission,
            "dispatch_status": "blocked",
            "dispatch_reason": str(admission["reason_codes"][0]),
            "notion_writes_performed": False,
            "drive_writes_performed": False,
            "classroom_artifact_writes_performed": False,
            "gce_invoked": False,
            "generated_at": args.generated_at,
        }
    else:
        try:
            adapter = new_read_adapter()
        except NotionBindingError as exc:
            raise NotionReadRequestError(str(exc)) from exc
        evidence = {
            "admission": admission,
            **verify_live_bindings(adapter, generated_at=args.generated_at),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANONICAL_REGISTRY_DATABASE_ID",
    "CANDY_BRANDING_STABLE_ID",
    "CANDY_BRANDING_TITLE",
    "CANDY_BRANDING_UNIT_KEY",
    "CANDY_BRANDING_VERIFICATION_REQUEST_ID",
    "PHOTOGRAPHY_FOUNDATIONS_PAGE_ID",
    "VERIFICATION_REQUEST_ID",
    "VISUAL_ASSET_LIBRARY_DATABASE_ID",
    "admit_binding_verification_request",
    "verify_candy_branding_binding",
    "verify_live_bindings",
]
