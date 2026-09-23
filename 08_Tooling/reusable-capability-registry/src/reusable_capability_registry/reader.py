from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
import re

import yaml
from yaml.nodes import MappingNode

from .models import CapabilityRecord

SUPPORTED_REGISTRY_VERSIONS = frozenset({"0.1.0"})
_CAPABILITY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQUIRED_FIELDS = frozenset({
    "capability_id", "name", "summary", "status", "canonical_paths",
    "public_interfaces", "owner_agent", "known_consumers", "tests",
    "keywords", "reuse_guidance", "side_effects",
})
_OPTIONAL_FIELDS = frozenset({
    "known_consumer_exemption", "supporting_agents", "deprecated_by", "inputs",
    "outputs", "extension_points", "invariants", "failure_modes",
    "compatibility", "documentation_handoff",
})
_ALLOWED_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS
_ALLOWED_STATUSES = frozenset({"active", "experimental", "deprecated", "replaced", "internal-only"})
_ALLOWED_TOP_LEVEL_FIELDS = frozenset({"registry_version", "capabilities"})
_MERGE_TAG = "tag:yaml.org,2002:merge"


class RegistryError(ValueError):
    """Base error for conservative registry failures."""


class RegistryFileError(RegistryError):
    pass


class RegistryFormatError(RegistryError):
    pass


class UnsupportedRegistryVersion(RegistryError):
    pass


class _DuplicateMappingKeyError(yaml.YAMLError):
    pass


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects duplicate explicitly authored keys."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)

        seen: set[tuple[str, Any]] = set()
        for key_node, _ in node.value:
            if key_node.tag == _MERGE_TAG:
                identity = ("merge", "<<")
                key_text = "<<"
            else:
                key = self.construct_object(key_node, deep=False)
                try:
                    hash(key)
                except TypeError:
                    # Preserve PyYAML's normal failure for unhashable mapping keys.
                    continue
                identity = ("key", key)
                key_text = str(key)

            if identity in seen:
                key_line = key_node.start_mark.line + 1
                mapping_line = node.start_mark.line + 1
                raise _DuplicateMappingKeyError(
                    f"duplicate YAML mapping key {key_text!r} at line {key_line} "
                    f"(mapping starts at line {mapping_line})"
                )
            seen.add(identity)

        return super().construct_mapping(node, deep=deep)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_registry_path() -> Path:
    return repository_root() / "04_Registry" / "reusable-capabilities.yml"


def _required_text(record: Mapping[str, Any], field: str, capability_id: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RegistryFormatError(f"{capability_id}: {field} must be a non-empty string")
    return value.strip()


def _optional_text(record: Mapping[str, Any], field: str, capability_id: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RegistryFormatError(f"{capability_id}: {field} must be a non-empty string when present")
    return value.strip()


def _text_tuple(record: Mapping[str, Any], field: str, capability_id: str, *, required: bool = False) -> tuple[str, ...]:
    value = record.get(field)
    if value is None and not required:
        return ()
    if not isinstance(value, list):
        raise RegistryFormatError(f"{capability_id}: {field} must be a list of strings")
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RegistryFormatError(f"{capability_id}: {field} must contain non-empty strings")
        trimmed = item.strip()
        if trimmed in seen:
            raise RegistryFormatError(f"{capability_id}: {field} contains duplicate value: {trimmed}")
        seen.add(trimmed)
        items.append(trimmed)
    return tuple(items)


def _parse_record(raw: Any) -> CapabilityRecord:
    if not isinstance(raw, Mapping):
        raise RegistryFormatError("each capability must be a mapping")
    raw_id = raw.get("capability_id", "<unknown>")
    capability_id = raw_id.strip() if isinstance(raw_id, str) else "<unknown>"
    missing = sorted(_REQUIRED_FIELDS - raw.keys())
    if missing:
        raise RegistryFormatError(f"{capability_id}: missing required fields: {', '.join(missing)}")
    unknown = sorted(set(raw) - _ALLOWED_FIELDS)
    if unknown:
        raise RegistryFormatError(f"{capability_id}: unsupported fields for registry 0.1.0: {', '.join(unknown)}")
    capability_id = _required_text(raw, "capability_id", capability_id)
    if not _CAPABILITY_ID_RE.fullmatch(capability_id):
        raise RegistryFormatError(f"{capability_id}: capability_id must be lowercase kebab-case")
    status = _required_text(raw, "status", capability_id)
    if status not in _ALLOWED_STATUSES:
        raise RegistryFormatError(f"{capability_id}: unsupported status: {status}")
    if status in {"deprecated", "replaced"} and not _optional_text(raw, "deprecated_by", capability_id):
        raise RegistryFormatError(f"{capability_id}: deprecated_by is required for status {status}")
    return CapabilityRecord(
        capability_id=capability_id,
        name=_required_text(raw, "name", capability_id),
        summary=_required_text(raw, "summary", capability_id),
        status=status,
        canonical_paths=_text_tuple(raw, "canonical_paths", capability_id, required=True),
        public_interfaces=_text_tuple(raw, "public_interfaces", capability_id, required=True),
        owner_agent=_required_text(raw, "owner_agent", capability_id),
        supporting_agents=_text_tuple(raw, "supporting_agents", capability_id),
        known_consumers=_text_tuple(raw, "known_consumers", capability_id, required=True),
        known_consumer_exemption=_optional_text(raw, "known_consumer_exemption", capability_id),
        tests=_text_tuple(raw, "tests", capability_id, required=True),
        keywords=_text_tuple(raw, "keywords", capability_id, required=True),
        reuse_guidance=_required_text(raw, "reuse_guidance", capability_id),
        side_effects=_text_tuple(raw, "side_effects", capability_id, required=True),
        inputs=_text_tuple(raw, "inputs", capability_id),
        outputs=_text_tuple(raw, "outputs", capability_id),
        extension_points=_text_tuple(raw, "extension_points", capability_id),
        invariants=_text_tuple(raw, "invariants", capability_id),
        failure_modes=_text_tuple(raw, "failure_modes", capability_id),
        compatibility=_text_tuple(raw, "compatibility", capability_id),
        documentation_handoff=_text_tuple(raw, "documentation_handoff", capability_id),
        deprecated_by=_optional_text(raw, "deprecated_by", capability_id),
    )


def normalize_keyword(value: str) -> str:
    return "-".join(value.strip().casefold().replace("_", "-").split())


class RegistryReader:
    def __init__(self, registry_path: str | Path | None = None) -> None:
        self.registry_path = Path(registry_path).resolve() if registry_path else default_registry_path()
        self._parse_count = 0
        self._index_build_count = 0
        self._records = self._load_records()
        self._by_id: dict[str, CapabilityRecord]
        self._indexes: dict[str, dict[str, tuple[CapabilityRecord, ...]]]
        self._build_indexes()

    @property
    def records(self) -> tuple[CapabilityRecord, ...]:
        return self._records

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def parse_count(self) -> int:
        return self._parse_count

    @property
    def index_build_count(self) -> int:
        return self._index_build_count

    @property
    def index_entry_counts(self) -> tuple[tuple[str, int], ...]:
        return tuple(sorted((field, len(index)) for field, index in self._indexes.items()))

    def _load_records(self) -> tuple[CapabilityRecord, ...]:
        self._parse_count += 1
        try:
            text = self.registry_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RegistryFileError(f"unable to read registry: {self.registry_path}") from exc
        try:
            document = yaml.load(text, Loader=_UniqueKeySafeLoader)
        except _DuplicateMappingKeyError as exc:
            raise RegistryFormatError(str(exc)) from exc
        except yaml.YAMLError as exc:
            raise RegistryFormatError("registry YAML is malformed") from exc
        if not isinstance(document, Mapping):
            raise RegistryFormatError("registry top level must be a mapping")
        unknown_top_level = sorted(set(document) - _ALLOWED_TOP_LEVEL_FIELDS)
        if unknown_top_level:
            raise RegistryFormatError(
                f"unsupported top-level registry keys for registry 0.1.0: {', '.join(unknown_top_level)}"
            )
        version = document.get("registry_version")
        if not isinstance(version, str):
            raise RegistryFormatError("registry_version must be a string")
        if version not in SUPPORTED_REGISTRY_VERSIONS:
            raise UnsupportedRegistryVersion(f"unsupported registry version: {version}")
        raw_capabilities = document.get("capabilities")
        if not isinstance(raw_capabilities, list):
            raise RegistryFormatError("capabilities must be a list")
        records = tuple(_parse_record(raw) for raw in raw_capabilities)
        ids = [record.capability_id for record in records]
        if len(ids) != len(set(ids)):
            raise RegistryFormatError("capability_id values must be unique")
        return tuple(sorted(records, key=lambda item: item.capability_id))

    def _build_indexes(self) -> None:
        self._index_build_count += 1
        self._by_id = {record.capability_id: record for record in self._records}
        mutable_indexes: dict[str, dict[str, list[CapabilityRecord]]] = {
            "keyword": {},
            "owner": {},
            "status": {},
            "canonical_path": {},
            "public_interface": {},
        }
        for record in self._records:
            for keyword in record.keywords:
                mutable_indexes["keyword"].setdefault(normalize_keyword(keyword), []).append(record)
            exact_values = {
                "owner": (record.owner_agent,),
                "status": (record.status,),
                "canonical_path": record.canonical_paths,
                "public_interface": record.public_interfaces,
            }
            for field, values in exact_values.items():
                for value in values:
                    mutable_indexes[field].setdefault(value, []).append(record)
        self._indexes = {
            field: {
                key: tuple(sorted(matches, key=lambda item: item.capability_id))
                for key, matches in values.items()
            }
            for field, values in mutable_indexes.items()
        }

    def by_id(self, capability_id: str) -> CapabilityRecord | None:
        return self._by_id.get(capability_id)

    def lookup(self, field: str, value: str) -> tuple[CapabilityRecord, ...]:
        try:
            index = self._indexes[field]
        except KeyError as exc:
            raise RegistryFormatError(f"unsupported lookup field: {field}") from exc
        key = normalize_keyword(value) if field == "keyword" else value
        return index.get(key, ())
