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

from .catalog import load_catalog
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

BINDING_VERIFICATION_REQUEST_IDS = (
    VERIFICATION_REQUEST_ID,
    CANDY_BRANDING_VERIFICATION_REQUEST_ID,
)
_PHOTOGRAPHY_ALLOWED_ACTIONS = ("get_database", "get_page")
_ADDITIONAL_UNIT_ALLOWED_ACTIONS = ("get_data_source", "query_data_source")


def _verification_request_spec(
    request_id: str | None,
) -> tuple[int, str, tuple[str, ...]] | None:
    if request_id == VERIFICATION_REQUEST_ID:
        return (
            VERIFICATION_ISSUE_NUMBER,
            "photography-foundations",
            _PHOTOGRAPHY_ALLOWED_ACTIONS,
        )
    if request_id is None or not request_id.startswith("verify-") or not request_id.endswith("-binding"):
        return None

    canonical_unit_key = request_id.removeprefix("verify-").removesuffix("-binding")
    catalog = load_catalog()
    unit = catalog.canonical_unit(canonical_unit_key)
    if unit is None or unit.dispatchable or unit.verification_title is None:
        return None

    canonical_requests = [
        record
        for record in catalog.requests
        if record.request_class == "canonical-unit"
        and record.canonical_unit_key == canonical_unit_key
    ]
    if len(canonical_requests) != 1:
        return None
    return (
        canonical_requests[0].issue_number,
        canonical_unit_key,
        _ADDITIONAL_UNIT_ALLOWED_ACTIONS,
    )


def is_binding_verification_request_id(request_id: object) -> bool:
    """Return whether one finite request id is eligible for binding verification.

    The repository-owned catalog remains the allowlist. This helper intentionally
    derives eligibility from the same generic request spec used by admission so
    adding a staged unit never requires a second workflow routing list.
    """

    return isinstance(request_id, str) and _verification_request_spec(request_id) is not None


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
    """Admit only a finite repository-owned binding-verification request."""
    reason = "admitted"
    authorized = True
    issue_number: int | None = None
    request_id = (
        transport.get("notion_read_request_id_or_none")
        if isinstance(transport, Mapping)
        and isinstance(transport.get("notion_read_request_id_or_none"), str)
        else None
    )
    spec = _verification_request_spec(request_id)
    expected_issue, canonical_unit_key, allowed_actions = (
        spec if spec is not None else (None, None, ())
    )

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
    elif spec is None:
        reason, authorized = "verification-request-mismatch", False
    elif type(transport.get("issue_number")) is not int:
        reason, authorized = "issue-target-mismatch", False
    else:
        issue_number = int(transport["issue_number"])
        if issue_number != expected_issue:
            reason, authorized = "issue-target-mismatch", False

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "admitted" if authorized else "rejected",
        "reason_codes": [reason],
        "repository": expected_repository,
        "issue_number": issue_number,
        "request_id": request_id,
        "request_class": "binding-verification",
        "canonical_unit_key": canonical_unit_key,
        "allowed_read_actions": list(allowed_actions),
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



def _resolve_title_property_name(adapter: object, *, data_source_id: str) -> str:
    """Resolve the one title-typed property from the verified registry schema."""

    output = _execute_read(
        adapter,
        "get_data_source",
        data_source_id=data_source_id,
    )
    if _normalize_notion_id(output.get("id")) != _normalize_notion_id(data_source_id):
        raise NotionReadRequestError("canonical registry data source identity mismatch")

    properties = output.get("properties")
    if not isinstance(properties, Mapping):
        raise NotionReadRequestError("canonical registry schema is missing properties")

    title_properties = [
        name
        for name, metadata in properties.items()
        if isinstance(name, str)
        and name.strip()
        and isinstance(metadata, Mapping)
        and metadata.get("type") == "title"
    ]
    if len(title_properties) != 1:
        raise NotionReadRequestError(
            "canonical registry schema must expose exactly one title property"
        )
    return title_properties[0]


def _execute_registry_query(
    adapter: object,
    *,
    data_source_id: str,
    title_property_name: str,
    exact_title: str,
) -> list[dict[str, Any]]:
    """Query one verified registry source by one repository-owned exact title."""

    output = _execute_read(
        adapter,
        "query_data_source",
        data_source_id=data_source_id,
        filter={
            "property": title_property_name,
            "title": {"equals": exact_title},
        },
        page_size=2,
        max_pages=1,
        max_results=2,
    )
    results = output.get("results")
    if not isinstance(results, list) or any(not isinstance(item, Mapping) for item in results):
        raise NotionReadRequestError("canonical-unit verification returned malformed results")
    return [dict(item) for item in results]


def verify_additional_unit_binding(
    adapter: object,
    *,
    canonical_unit_key: str,
    canonical_registry_data_source_id: str,
    generated_at: str,
) -> dict[str, object]:
    """Discover one finite catalog-declared unit identity without promoting it."""

    catalog = load_catalog()
    unit = catalog.canonical_unit(canonical_unit_key)
    if unit is None or unit.dispatchable or unit.verification_title is None:
        raise NotionReadRequestError("canonical unit is not eligible for binding verification")

    canonical_requests = [
        record
        for record in catalog.requests
        if record.request_class == "canonical-unit"
        and record.canonical_unit_key == canonical_unit_key
    ]
    if len(canonical_requests) != 1:
        raise NotionReadRequestError("canonical unit verification request is missing or ambiguous")

    if not isinstance(canonical_registry_data_source_id, str) or not canonical_registry_data_source_id.strip():
        raise NotionReadRequestError("canonical registry data source id is missing")

    data_source_id = canonical_registry_data_source_id.strip()
    title_property_name = _resolve_title_property_name(
        adapter,
        data_source_id=data_source_id,
    )
    matches = _execute_registry_query(
        adapter,
        data_source_id=data_source_id,
        title_property_name=title_property_name,
        exact_title=unit.verification_title,
    )
    if len(matches) != 1:
        raise NotionReadRequestError("canonical-unit identity is missing or ambiguous")

    page = matches[0]
    page_id = page.get("id")
    if not isinstance(page_id, str) or not page_id.strip():
        raise NotionReadRequestError("canonical-unit page id is missing")
    if page.get("archived") is True or page.get("in_trash") is True:
        raise NotionReadRequestError("canonical page is archived or trashed")

    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": f"verify-{canonical_unit_key}-binding",
        "dispatch_status": "completed",
        "dispatch_reason": "canonical-unit-binding-verification-complete",
        "canonical_unit": {
            "canonical_unit_key": unit.canonical_unit_key,
            "stable_id": unit.stable_id,
            "provider_page_id": page_id.strip(),
            "verification_state": "verified-current",
        },
        "notion_writes_performed": False,
        "drive_writes_performed": False,
        "classroom_artifact_writes_performed": False,
        "gce_invoked": False,
        "generated_at": generated_at,
    }


def verify_candy_branding_binding(
    adapter: object,
    *,
    canonical_registry_data_source_id: str,
    generated_at: str,
) -> dict[str, object]:
    """Compatibility wrapper for the first #2816 additional-unit verifier."""

    return verify_additional_unit_binding(
        adapter,
        canonical_unit_key=CANDY_BRANDING_UNIT_KEY,
        canonical_registry_data_source_id=canonical_registry_data_source_id,
        generated_at=generated_at,
    )


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
        if admission.get("request_id") == VERIFICATION_REQUEST_ID:
            result = verify_live_bindings(adapter, generated_at=args.generated_at)
        else:
            canonical_source = load_catalog().source("canonical-unit")
            if canonical_source is None or not canonical_source.dispatchable or canonical_source.data_source_id is None:
                raise NotionReadRequestError("canonical registry source binding is not verified-current")
            canonical_unit_key = admission.get("canonical_unit_key")
            if not isinstance(canonical_unit_key, str):
                raise NotionReadRequestError("binding verification canonical unit key is missing")
            result = verify_additional_unit_binding(
                adapter,
                canonical_unit_key=canonical_unit_key,
                canonical_registry_data_source_id=canonical_source.data_source_id,
                generated_at=args.generated_at,
            )
        evidence = {"admission": admission, **result}

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
    "BINDING_VERIFICATION_REQUEST_IDS",
    "is_binding_verification_request_id",
    "CANONICAL_REGISTRY_DATABASE_ID",
    "CANDY_BRANDING_STABLE_ID",
    "CANDY_BRANDING_TITLE",
    "CANDY_BRANDING_UNIT_KEY",
    "CANDY_BRANDING_VERIFICATION_REQUEST_ID",
    "PHOTOGRAPHY_FOUNDATIONS_PAGE_ID",
    "VERIFICATION_REQUEST_ID",
    "VISUAL_ASSET_LIBRARY_DATABASE_ID",
    "admit_binding_verification_request",
    "verify_additional_unit_binding",
    "verify_candy_branding_binding",
    "verify_live_bindings",
]
