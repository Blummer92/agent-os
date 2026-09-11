"""Load and strictly validate the repository-owned #2283 read catalog.

The catalog is the only place a request slug becomes a curriculum/asset source
identity. Comment text never reaches this module, so no arbitrary Notion id,
URL, property name, filter, or workspace-wide target can enter the path.

Loading is fail-closed: a malformed catalog raises rather than degrading to a
partially trusted vocabulary.
"""

from __future__ import annotations

import json
from pathlib import Path

from instructional_workflow_contracts.current_curriculum_state import UNIT_STATUSES

from .models import (
    PUBLIC_PROJECTABLE_CONTENT_CLASSES,
    REQUEST_CLASSES,
    SCHEMA_VERSION,
    VERIFIED_STATE,
    CanonicalUnitBinding,
    NotionReadCatalog,
    NotionReadRequestError,
    NotionReadRequestRecord,
    NotionReadSource,
    looks_like_notion_id,
)

CATALOG_PATH = Path(__file__).with_name("notion_read_catalog.json")

_MAX_CATALOG_BYTES = 64 * 1024
_ALLOWED_VERIFICATION_STATES = frozenset({"unverified", VERIFIED_STATE})
_SLUG_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def load_catalog(path: Path | None = None) -> NotionReadCatalog:
    """Return the validated repository-owned catalog."""
    target = path or CATALOG_PATH
    if target.stat().st_size > _MAX_CATALOG_BYTES:
        raise NotionReadRequestError("catalog exceeds bounded size")
    return parse_catalog(json.loads(target.read_text(encoding="utf-8")))


def parse_catalog(payload: object) -> NotionReadCatalog:
    """Validate one catalog payload without any repository or network I/O."""
    if type(payload) is not dict:
        raise NotionReadRequestError("catalog must be an object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise NotionReadRequestError("catalog schema version drift")

    repository = _text(payload.get("repository"), "catalog repository")
    if repository.count("/") != 1 or any(not part for part in repository.split("/")):
        raise NotionReadRequestError("catalog repository must use owner/name syntax")

    credential_env_var = _text(
        payload.get("credential_env_var"), "catalog credential_env_var"
    )

    canonical_units = tuple(
        _canonical_unit(item) for item in _list(payload.get("canonical_units"), "canonical_units")
    )
    sources = tuple(_source(item) for item in _list(payload.get("sources"), "sources"))
    requests = tuple(_request(item) for item in _list(payload.get("requests"), "requests"))

    _reject_duplicates(
        [unit.canonical_unit_key for unit in canonical_units], "canonical unit key"
    )
    _reject_duplicates([source.logical_source for source in sources], "logical source")
    _reject_duplicates([record.request_id for record in requests], "request id")

    known_units = {unit.canonical_unit_key for unit in canonical_units}
    for record in requests:
        if record.canonical_unit_key not in known_units:
            raise NotionReadRequestError(
                f"request {record.request_id!r} names an unknown canonical unit"
            )

    return NotionReadCatalog(
        schema_version=SCHEMA_VERSION,
        repository=repository,
        credential_env_var=credential_env_var,
        requests=requests,
        sources=sources,
        canonical_units=canonical_units,
    )


def _canonical_unit(value: object) -> CanonicalUnitBinding:
    item = _object(value, "canonical unit")
    unit_status = _text(item.get("unit_status"), "canonical unit unit_status")
    # Reuse the canonical #973 status vocabulary rather than defining a second one.
    if unit_status not in UNIT_STATUSES:
        raise NotionReadRequestError(f"unsupported canonical unit status: {unit_status!r}")
    return CanonicalUnitBinding(
        canonical_unit_key=_slug(item.get("canonical_unit_key"), "canonical_unit_key"),
        stable_id=_text(item.get("stable_id"), "canonical unit stable_id"),
        unit_status=unit_status,
        provider_page_id=_optional_identity(item.get("provider_page_id"), "provider_page_id"),
        verification_state=_verification_state(item.get("verification_state")),
        content_class=_content_class(item.get("content_class")),
    )


def _source(value: object) -> NotionReadSource:
    item = _object(value, "source")
    return NotionReadSource(
        logical_source=_slug(item.get("logical_source"), "logical_source"),
        display_name=_text(item.get("display_name"), "source display_name"),
        data_source_id=_optional_identity(item.get("data_source_id"), "data_source_id"),
        verification_state=_verification_state(item.get("verification_state")),
        content_class=_content_class(item.get("content_class")),
    )


def _request(value: object) -> NotionReadRequestRecord:
    item = _object(value, "request")
    request_class = _text(item.get("request_class"), "request_class")
    if request_class not in REQUEST_CLASSES:
        raise NotionReadRequestError(f"unknown request class: {request_class!r}")
    issue_number = item.get("issue_number")
    if type(issue_number) is not int or issue_number < 1:
        raise NotionReadRequestError("request issue_number must be a positive integer")
    return NotionReadRequestRecord(
        request_id=_slug(item.get("request_id"), "request_id"),
        request_class=request_class,
        canonical_unit_key=_slug(item.get("canonical_unit_key"), "canonical_unit_key"),
        issue_number=issue_number,
    )


def _verification_state(value: object) -> str:
    state = _text(value, "verification_state")
    if state not in _ALLOWED_VERIFICATION_STATES:
        raise NotionReadRequestError(f"unknown verification state: {state!r}")
    return state


def _content_class(value: object) -> str:
    content_class = _text(value, "content_class")
    # A source whose declared class is not public-projectable can never be bound
    # here at all; the structural constraint is enforced at load time, not by
    # inspecting result text later.
    if content_class not in PUBLIC_PROJECTABLE_CONTENT_CLASSES:
        raise NotionReadRequestError(
            f"content class is not public-projectable: {content_class!r}"
        )
    return content_class


def _optional_identity(value: object, label: str) -> str | None:
    """Accept only an explicit unbound marker or a bounded opaque identity."""
    if value is None:
        return None
    identity = _text(value, label)
    if len(identity) > 64 or any(character.isspace() for character in identity):
        raise NotionReadRequestError(f"{label} must be one bounded identity")
    if "/" in identity or ":" in identity:
        raise NotionReadRequestError(f"{label} must not carry a URL or scheme")
    return identity


def _slug(value: object, label: str) -> str:
    slug = _text(value, label)
    if not 3 <= len(slug) <= 63:
        raise NotionReadRequestError(f"{label} must be 3-63 characters")
    if set(slug) - _SLUG_CHARS:
        raise NotionReadRequestError(f"{label} must be a lowercase slug")
    if slug.startswith("-") or slug.endswith("-") or "--" in slug:
        raise NotionReadRequestError(f"{label} has malformed slug separators")
    # A Notion id is lowercase hex and would otherwise satisfy the slug grammar.
    # Refusing the shape here stops a provider target from ever being registered
    # as a request identity in the first place.
    if looks_like_notion_id(slug):
        raise NotionReadRequestError(f"{label} must not be a Notion identity")
    return slug


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise NotionReadRequestError(f"missing required {label}")
    return value.strip()


def _object(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict:
        raise NotionReadRequestError(f"{label} entry must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if type(value) is not list or not value:
        raise NotionReadRequestError(f"catalog {label} must be a non-empty array")
    return value


def _reject_duplicates(values: list[str], label: str) -> None:
    if len(set(values)) != len(values):
        raise NotionReadRequestError(f"catalog has a duplicate {label}")


__all__ = ["CATALOG_PATH", "load_catalog", "parse_catalog"]
