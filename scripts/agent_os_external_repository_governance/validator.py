"""ERG2 offline validator — the single ERG validator entry path (#581).

Consumes the #580 contract (shared standard + Draft 2020-12 schemas in
``03_Templates/``) instead of redefining it. Deterministic, offline,
bounded, and fail-closed. Policy outcomes (``pass``/``warning``/``fail``/
``manual-review``) are distinguishable from ``infrastructure-error``: the
latter means trusted evidence could not be produced and is never converted.

Do not create alternate validators for the same ERG contract; extend this
entry path.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import paths as _paths
from .models import (
    ErgCheck,
    ErgValidationReport,
    ErgVerdict,
    report_from_checks,
)
from .strict_yaml import ErgYAMLStrictError, strict_yaml_load

_PROFILE_SCHEMA_REL = Path("03_Templates/external-repository-profile.v1alpha1.schema.json")
_REGISTRY_SCHEMA_REL = Path("03_Templates/external-repository-registry.v1alpha1.schema.json")

_EVALUATED = (
    "strict-yaml-input-bounds",
    "contract-identity",
    "schema-conformance",
    "declared-path-safety",
    "registry-admission-policy",
)
_NOT_EVALUATED = (
    "consumer-repository-behavior",
    "live-runtime-state",
    "network-or-github-state",
    "declared-document-existence",
    "approval-or-readiness",
)


class ErgSchemaUnavailableError(Exception):
    """The #580 schemas could not be loaded (infrastructure, not policy)."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=2)
def _load_schema(relative: str, schema_dir: str | None) -> dict[str, Any]:
    base = Path(schema_dir) if schema_dir else _repo_root()
    path = base / relative
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErgSchemaUnavailableError(f"cannot load ERG schema {path}: {exc}") from exc


def load_erg_schemas(schema_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """Load the #580 contract schemas. Keys: ``profile``, ``registry``."""
    return {
        "profile": _load_schema(str(_PROFILE_SCHEMA_REL), schema_dir),
        "registry": _load_schema(str(_REGISTRY_SCHEMA_REL), schema_dir),
    }


# ---------------------------------------------------------------------------
# Bounded schema-driven conformance.
#
# Interprets exactly the Draft 2020-12 keywords used by the two #580 schemas,
# driven by the loaded schema documents themselves. This is ERG-specific
# contract conformance, not a generic schema framework: unknown keywords are
# ignored because the schemas are fixed and versioned by #580.
# ---------------------------------------------------------------------------


def _pointer(base: str, key: str) -> str:
    escaped = key.replace("~", "~0").replace("/", "~1")
    return f"{base}/{escaped}" if base else f"/{escaped}"


def _type_matches(value: Any, name: str) -> bool:
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    return False  # unknown type name: fail closed at the call site


def _check(
    value: Any, schema: dict[str, Any], defs: dict[str, Any], pointer: str
) -> list[str]:
    violations: list[str] = []

    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            violations.append(f"{pointer or '/'}: unsupported $ref {ref!r}")
            return violations
        name = ref[len("#/$defs/") :]
        if name not in defs:
            violations.append(f"{pointer or '/'}: unknown $defs reference {name!r}")
            return violations
        return _check(value, defs[name], defs, pointer)

    expected = schema.get("type")
    if expected is not None:
        names = [expected] if isinstance(expected, str) else list(expected)
        if not any(_type_matches(value, name) for name in names):
            violations.append(
                f"{pointer or '/'}: expected type {expected}, got "
                f"{type(value).__name__}"
            )
            return violations  # further keyword checks assume the type

    if "const" in schema and value != schema["const"]:
        violations.append(f"{pointer or '/'}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        violations.append(
            f"{pointer or '/'}: {value!r} is not one of {schema['enum']!r}"
        )

    if isinstance(value, dict):
        for required_key in schema.get("required", ()):  # schema order: required first
            if required_key not in value:
                violations.append(f"{pointer or '/'}: missing required property {required_key!r}")
        properties: dict[str, Any] = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key in value:  # document order is deterministic
            child = _pointer(pointer, key)
            if key in properties:
                violations.extend(_check(value[key], properties[key], defs, child))
            elif additional is False:
                violations.append(f"{child}: unknown field {key!r} fails closed")
            elif isinstance(additional, dict):
                violations.extend(_check(value[key], additional, defs, child))
        names_schema = schema.get("propertyNames")
        if names_schema:
            for key in value:
                violations.extend(_check(key, names_schema, defs, _pointer(pointer, key)))
        for bound, word in (("minProperties", "fewer"), ("maxProperties", "more")):
            if bound in schema:
                limit = schema[bound]
                if (len(value) < limit) if word == "fewer" else (len(value) > limit):
                    violations.append(
                        f"{pointer or '/'}: has {word} than {bound}={limit} properties"
                    )

    if isinstance(value, list):
        items_schema = schema.get("items")
        for index, item in enumerate(value):
            if items_schema is not None:
                violations.extend(_check(item, items_schema, defs, f"{pointer or '/'}/{index}"))
        for bound, word in (("minItems", "fewer"), ("maxItems", "more")):
            if bound in schema:
                limit = schema[bound]
                if (len(value) < limit) if word == "fewer" else (len(value) > limit):
                    violations.append(
                        f"{pointer or '/'}: has {word} than {bound}={limit} items"
                    )
        if schema.get("uniqueItems"):
            seen: list[Any] = []
            for item in value:
                if item in seen:
                    violations.append(f"{pointer or '/'}: duplicate array item {item!r}")
                    break
                seen.append(item)

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            violations.append(
                f"{pointer or '/'}: shorter than minLength={schema['minLength']}"
            )
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            violations.append(
                f"{pointer or '/'}: longer than maxLength={schema['maxLength']}"
            )
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            violations.append(f"{pointer or '/'}: does not match required pattern")

    for subschema in schema.get("allOf", ()):
        if "if" in subschema:
            if not _check(value, subschema["if"], defs, pointer):
                violations.extend(_check(value, subschema.get("then", {}), defs, pointer))

    return violations


def _schema_conformance(
    document: Any, schema: dict[str, Any]
) -> list[str]:
    return _check(document, schema, schema.get("$defs", {}), "")


# ---------------------------------------------------------------------------
# Contract identity + ERG policy checks
# ---------------------------------------------------------------------------


def _contract_consts(schema: dict[str, Any]) -> tuple[Any, Any]:
    props = schema.get("properties", {})
    return (
        props.get("apiVersion", {}).get("const"),
        props.get("kind", {}).get("const"),
    )


def _check_profile_policy(
    document: dict[str, Any],
    profile_schema: dict[str, Any],
    repo_root: Path | None,
) -> list[ErgCheck]:
    pattern = profile_schema["$defs"]["safeRelativePath"]["pattern"]
    findings: list[str] = []
    docs = document.get("governanceDocuments")
    if isinstance(docs, dict):
        for role in sorted(docs):
            findings.extend(
                _paths.check_declared_path(
                    docs[role],
                    schema_pattern=pattern,
                    repo_root=repo_root,
                    location=f"/governanceDocuments/{role}",
                )
            )
    return [
        ErgCheck(
            name="declared-path-safety",
            verdict=ErgVerdict.FAIL if findings else ErgVerdict.PASS,
            detail=(
                "one or more declared governance-document paths are unsafe"
                if findings
                else "all declared governance-document paths are safe"
            ),
            evidence=tuple(findings),
        )
    ]


def _check_registry_policy(
    document: dict[str, Any],
    registry_schema: dict[str, Any],
    repo_root: Path | None,
) -> list[ErgCheck]:
    pattern = registry_schema["$defs"]["safeRelativePath"]["pattern"]
    findings: list[str] = []
    records = document.get("repositories")
    if not isinstance(records, list):
        return []
    # Pass 1: identity and declared paths. Alias checks run in a second pass
    # against the complete identity sets so a collision is reported no matter
    # whether the alias or the repository it collides with comes first.
    seen_ids: dict[str, int] = {}
    seen_repos: dict[str, int] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        label = f"/repositories/{index}"
        registry_id = record.get("registryId")
        if isinstance(registry_id, str):
            if registry_id in seen_ids:
                findings.append(
                    f"{label}: duplicate registryId {registry_id!r} "
                    f"(first at /repositories/{seen_ids[registry_id]})"
                )
            else:
                seen_ids[registry_id] = index
        repository = record.get("repository")
        if isinstance(repository, str):
            if repository in seen_repos:
                findings.append(
                    f"{label}: duplicate repository {repository!r} "
                    f"(first at /repositories/{seen_repos[repository]})"
                )
            else:
                seen_repos[repository] = index
        profile_path = record.get("profilePath")
        if profile_path is not None:
            findings.extend(
                _paths.check_declared_path(
                    profile_path,
                    schema_pattern=pattern,
                    repo_root=repo_root,
                    location=f"{label}/profilePath",
                )
            )
    # Pass 2: alias collisions against complete identity sets.
    alias_owners: dict[str, int] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        label = f"/repositories/{index}"
        repository = record.get("repository")
        aliases = record.get("aliases")
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            if alias == repository:
                findings.append(
                    f"{label}: alias {alias!r} duplicates the record's own repository"
                )
            elif alias in alias_owners:
                findings.append(
                    f"{label}: alias {alias!r} collides with an alias of "
                    f"/repositories/{alias_owners[alias]}"
                )
            elif alias in seen_repos and seen_repos[alias] != index:
                findings.append(
                    f"{label}: alias {alias!r} collides with the repository of "
                    f"/repositories/{seen_repos[alias]}"
                )
            else:
                alias_owners.setdefault(alias, index)
    return [
        ErgCheck(
            name="registry-admission-policy",
            verdict=ErgVerdict.FAIL if findings else ErgVerdict.PASS,
            detail=(
                "one or more registry admission-policy violations"
                if findings
                else "registry admission policy holds (stable ids, identity, lifecycle)"
            ),
            evidence=tuple(findings),
        )
    ]


# ---------------------------------------------------------------------------
# Single entry path
# ---------------------------------------------------------------------------


def validate_erg_document(
    text: str,
    *,
    source: str,
    repo_root: str | Path | None = None,
    schema_dir: str | Path | None = None,
) -> ErgValidationReport:
    """Validate one ERG document (consumer profile or central registry).

    The single ERG validator entry path. Deterministic, offline, bounded,
    fail-closed. ``repo_root`` enables executable symlink-containment checks
    for declared paths; ``None`` skips only that check. Returns an
    evidence-only report; the report authorizes nothing.
    """
    root = Path(repo_root) if repo_root is not None else None
    try:
        schemas = load_erg_schemas(schema_dir)
    except ErgSchemaUnavailableError as exc:
        return report_from_checks(
            subject=source,
            document_kind=None,
            contract_version=None,
            checks=[
                ErgCheck(
                    name="schema-availability",
                    verdict=ErgVerdict.INFRASTRUCTURE_ERROR,
                    detail=str(exc),
                )
            ],
            evaluated=(),
            not_evaluated=_NOT_EVALUATED,
        )

    try:
        document = strict_yaml_load(text)
    except ErgYAMLStrictError as exc:
        return report_from_checks(
            subject=source,
            document_kind=None,
            contract_version=None,
            checks=[
                ErgCheck(
                    name="strict-yaml-input-bounds",
                    verdict=ErgVerdict.FAIL,
                    detail=f"malformed input fails closed: {exc}",
                )
            ],
            evaluated=_EVALUATED,
            not_evaluated=_NOT_EVALUATED,
        )

    checks: list[ErgCheck] = [
        ErgCheck(
            name="strict-yaml-input-bounds",
            verdict=ErgVerdict.PASS,
            detail="one UTF-8 document within size/depth/collection bounds; "
            "no directives, anchors, aliases, merge keys, custom tags, "
            "duplicate keys, or non-JSON-model scalars",
        )
    ]

    if not isinstance(document, dict):
        checks.append(
            ErgCheck(
                name="contract-identity",
                verdict=ErgVerdict.FAIL,
                detail="ERG document must be a mapping",
            )
        )
        return report_from_checks(
            subject=source,
            document_kind=None,
            contract_version=None,
            checks=checks,
            evaluated=_EVALUATED,
            not_evaluated=_NOT_EVALUATED,
        )

    api_version = document.get("apiVersion")
    kind = document.get("kind")
    matched: tuple[str, dict[str, Any]] | None = None
    for name, schema in schemas.items():
        const_version, const_kind = _contract_consts(schema)
        if api_version == const_version and kind == const_kind:
            matched = (name, schema)
            break
    if matched is None:
        supported = sorted(
            f"{_contract_consts(s)[0]}/{_contract_consts(s)[1]}"
            for s in schemas.values()
        )
        checks.append(
            ErgCheck(
                name="contract-identity",
                verdict=ErgVerdict.FAIL,
                detail=(
                    f"unsupported apiVersion/kind {api_version!r}/{kind!r}; "
                    f"supported: {', '.join(supported)}"
                ),
            )
        )
        return report_from_checks(
            subject=source,
            document_kind=kind if isinstance(kind, str) else None,
            contract_version=api_version if isinstance(api_version, str) else None,
            checks=checks,
            evaluated=_EVALUATED,
            not_evaluated=_NOT_EVALUATED,
        )

    schema_name, schema = matched
    checks.append(
        ErgCheck(
            name="contract-identity",
            verdict=ErgVerdict.PASS,
            detail=f"recognized {kind} {api_version} (contract issue #580)",
        )
    )

    violations = _schema_conformance(document, schema)
    checks.append(
        ErgCheck(
            name="schema-conformance",
            verdict=ErgVerdict.FAIL if violations else ErgVerdict.PASS,
            detail=(
                f"{len(violations)} schema-conformance violation(s)"
                if violations
                else "document conforms to the #580 schema"
            ),
            evidence=tuple(violations),
        )
    )

    try:
        if schema_name == "profile":
            checks.extend(_check_profile_policy(document, schema, root))
        else:
            checks.extend(_check_registry_policy(document, schema, root))
    except OSError as exc:
        # Declared-path containment could not be evaluated at the OS level
        # (e.g. unreadable repository root). That is an infrastructure
        # failure, never a policy fail: trusted evidence could not be
        # produced, so it must not convert to pass/warning/fail.
        return report_from_checks(
            subject=source,
            document_kind=None,
            contract_version=None,
            checks=[
                ErgCheck(
                    name="declared-path-safety",
                    verdict=ErgVerdict.INFRASTRUCTURE_ERROR,
                    detail=f"path containment could not be evaluated: {exc}",
                )
            ],
            evaluated=(),
            not_evaluated=_NOT_EVALUATED,
        )

    return report_from_checks(
        subject=source,
        document_kind=kind,
        contract_version=api_version,
        checks=checks,
        evaluated=_EVALUATED,
        not_evaluated=_NOT_EVALUATED,
    )
