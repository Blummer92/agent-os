"""Shared, fail-closed loading and cross-reference helpers for LP contract registries.

Every LP registry under ``04_Registry/`` pairs a machine-readable YAML file with
one or more normative Markdown standards. The same structural guarantees apply to
all of them: no YAML anchors, merge keys, custom tags, or duplicate keys; only
exact built-in types; a stable canonical serialization; no generic governed
status keys; and a two-way match between registry ``normative_id`` references and
Markdown anchors.

These helpers exist so each LP registry test asserts its own domain rules instead
of restating the shared mechanics. They are test-only support and perform no
network, subprocess, or filesystem writes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

import yaml
from yaml.nodes import MappingNode

ROOT = Path(__file__).resolve().parents[1]

EXACT_TYPES = (dict, list, str, int, bool, type(None))
FORBIDDEN_GOVERNED_KEYS = frozenset({"status", "ready", "approved", "authorized"})
MAX_NESTING_DEPTH = 20

_ANCHOR_RE = re.compile(r"^#{2,3} ([a-z0-9]+(?:-[a-z0-9]+)*)$", flags=re.MULTILINE)
_YAML_ANCHOR_RE = re.compile(r"(^|\s)(?:&|\*)[A-Za-z0-9_-]+")
_YAML_MERGE_RE = re.compile(r"(^|\s)<<\s*:", flags=re.MULTILINE)
_YAML_TAG_RE = re.compile(r"(^|\s)![A-Za-z]")


class UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of silently winning last."""


def _construct_mapping(loader: UniqueKeyLoader, node: MappingNode, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def validate_exact_types(value: Any, *, depth: int = 0) -> None:
    """Reject timestamps, floats, sets, and any other non-exact YAML type."""
    if depth > MAX_NESTING_DEPTH:
        raise ValueError("unexpected nesting depth")
    if type(value) not in EXACT_TYPES:
        raise ValueError(f"unsupported YAML type: {type(value).__name__}")
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise ValueError("mapping keys must be exact strings")
            validate_exact_types(nested, depth=depth + 1)
    elif type(value) is list:
        for nested in value:
            validate_exact_types(nested, depth=depth + 1)


def load_yaml_text(text: str) -> dict:
    """Load a registry document from text, failing closed on unsafe YAML features."""
    if _YAML_ANCHOR_RE.search(text):
        raise ValueError("YAML anchors and aliases are forbidden")
    if _YAML_MERGE_RE.search(text):
        raise ValueError("YAML merge keys are forbidden")
    if _YAML_TAG_RE.search(text):
        raise ValueError("custom YAML tags are forbidden")
    loaded = yaml.load(text, Loader=UniqueKeyLoader)
    if type(loaded) is not dict:
        raise ValueError("registry must be an exact mapping")
    validate_exact_types(loaded)
    return loaded


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def load_registry(relative_path: str) -> dict:
    return load_yaml_text(read_text(relative_path))


def markdown_anchors(relative_paths: Iterable[str]) -> tuple[str, ...]:
    """Collect ``### kebab-case`` anchors across one or more Markdown standards.

    Raises when the same anchor is defined twice, within or across files, so a
    normative reference always resolves to exactly one definition.
    """
    anchors: list[str] = []
    for relative_path in relative_paths:
        anchors.extend(_ANCHOR_RE.findall(read_text(relative_path)))
    if len(anchors) != len(set(anchors)):
        raise ValueError("duplicate Markdown anchor")
    return tuple(anchors)


def collect_values(document: Any, key: str) -> list[str]:
    """Collect every value stored under ``key`` anywhere in the document."""
    found: list[str] = []
    if type(document) is dict:
        for nested_key, nested in document.items():
            if nested_key == key and type(nested) is str:
                found.append(nested)
            else:
                found.extend(collect_values(nested, key))
    elif type(document) is list:
        for nested in document:
            found.extend(collect_values(nested, key))
    return found


def assert_normative_ids_match_anchors(document: dict, relative_paths: Iterable[str]) -> None:
    """Require a two-way match: every reference resolves, every anchor is referenced."""
    referenced = collect_values(document, "normative_id")
    anchors = markdown_anchors(relative_paths)
    unresolved = sorted(set(referenced) - set(anchors))
    unreferenced = sorted(set(anchors) - set(referenced))
    assert not unresolved, f"normative_id without a Markdown anchor: {unresolved}"
    assert not unreferenced, f"Markdown anchor never referenced by the registry: {unreferenced}"


def assert_no_forbidden_governed_keys(document: Any) -> None:
    """Reject generic ``status``/``ready``/``approved``/``authorized`` keys.

    Historical literals remain valid as values, but no container disables
    governed-key validation for its descendants.
    """
    if type(document) is dict:
        for key, nested in document.items():
            if key in FORBIDDEN_GOVERNED_KEYS:
                raise AssertionError(f"forbidden governed key: {key}")
            assert_no_forbidden_governed_keys(nested)
    elif type(document) is list:
        for nested in document:
            assert_no_forbidden_governed_keys(nested)


def assert_canonical_serialization_is_stable(document: dict) -> None:
    """A round trip through canonical YAML must reproduce byte-identical output."""
    first = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    second = yaml.safe_dump(load_yaml_text(first), sort_keys=False, allow_unicode=True)
    assert first == second


def assert_contract_identity(document: dict, *, registry_name: str) -> None:
    """Every LP registry shares the same identity and versioning preamble."""
    assert document["registry_name"] == registry_name
    assert document["contract_version"] == "1.0"
    assert type(document["record_revision"]) is int
    assert document["record_revision"] >= 1


def assert_standards_exist(relative_paths: Iterable[str]) -> None:
    for relative_path in relative_paths:
        assert (ROOT / relative_path).is_file(), f"missing standard: {relative_path}"
