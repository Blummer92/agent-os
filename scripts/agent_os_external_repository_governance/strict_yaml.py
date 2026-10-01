"""ERG strict YAML parsing (#581 owns executable strict-YAML validation).

Enforces the "Safe YAML and input bounds" section of the #580 standard:

- one UTF-8 document, at most 65,536 UTF-8 bytes;
- no directives, no anchors, no aliases, no merge keys, no custom tags;
- no duplicate mapping keys;
- mapping keys must be strings;
- scalar values must fit the JSON data model: only str/int/bool/null;
  fail closed on floats (including sexagesimal, non-finite), timestamps,
  binary values, and custom tags;
- nesting deeper than 12 levels fails closed;
- more than 100 items in any collection fails closed.

Parsing uses PyYAML (a declared validation runtime dependency) with a
fail-closed node walk. Consumer document text is untrusted data; it is
parsed, never executed.
"""

from __future__ import annotations

from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from yaml.tokens import DirectiveToken

MAX_UTF8_BYTES = 65_536
MAX_DEPTH = 12
MAX_COLLECTION_ITEMS = 100

_ALLOWED_SCALAR_TAGS = frozenset(
    {
        "tag:yaml.org,2002:str",
        "tag:yaml.org,2002:int",
        "tag:yaml.org,2002:bool",
        "tag:yaml.org,2002:null",
    }
)
_MERGE_TAG = "tag:yaml.org,2002:merge"


class ErgYAMLStrictError(ValueError):
    """A fail-closed strict-YAML violation (malformed input, not infrastructure)."""


def _fail(message: str, node: Any = None) -> ErgYAMLStrictError:
    if node is not None and hasattr(node, "start_mark"):
        mark = node.start_mark
        message = f"{message} (line {mark.line + 1}, column {mark.column + 1})"
    return ErgYAMLStrictError(message)


def _check_no_directives(text: str) -> None:
    try:
        tokens = list(yaml.scan(text))
    except yaml.YAMLError as exc:
        raise ErgYAMLStrictError(f"YAML syntax error: {exc}") from exc
    for token in tokens:
        if isinstance(token, DirectiveToken):
            raise ErgYAMLStrictError(
                f"YAML directives are not allowed (directive {token.name!r})"
            )


def _walk(node: Any, depth: int, seen_ids: set[int]) -> None:
    if depth > MAX_DEPTH:
        raise _fail(f"nesting deeper than {MAX_DEPTH} levels is not allowed", node)
    if id(node) in seen_ids:
        raise _fail("YAML aliases are not allowed", node)
    seen_ids.add(id(node))
    if getattr(node, "anchor", None):
        raise _fail("YAML anchors are not allowed", node)

    if isinstance(node, ScalarNode):
        if node.tag == _MERGE_TAG or node.value == "<<":
            raise _fail("YAML merge keys are not allowed", node)
        if node.tag not in _ALLOWED_SCALAR_TAGS:
            raise _fail(
                f"scalar tag {node.tag} is not allowed; only str/int/bool/null scalars "
                "fit the ERG JSON data model",
                node,
            )
        if node.tag == "tag:yaml.org,2002:int" and ":" in node.value:
            raise _fail("sexagesimal integer values are not allowed", node)
        return

    if isinstance(node, SequenceNode):
        if len(node.value) > MAX_COLLECTION_ITEMS:
            raise _fail(
                f"sequence has {len(node.value)} items; at most "
                f"{MAX_COLLECTION_ITEMS} are allowed",
                node,
            )
        for child in node.value:
            _walk(child, depth + 1, seen_ids)
        return

    if isinstance(node, MappingNode):
        if len(node.value) > MAX_COLLECTION_ITEMS:
            raise _fail(
                f"mapping has {len(node.value)} entries; at most "
                f"{MAX_COLLECTION_ITEMS} are allowed",
                node,
            )
        seen_keys: set[str] = set()
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise _fail("mapping keys must be strings", key_node)
            if key_node.value == "<<":
                raise _fail("YAML merge keys are not allowed", key_node)
            if key_node.value in seen_keys:
                raise _fail(
                    f"duplicate mapping key {key_node.value!r}", key_node
                )
            seen_keys.add(key_node.value)
            _walk(value_node, depth + 1, seen_ids)
        return

    raise _fail(f"unsupported YAML node {type(node).__name__}", node)


def strict_yaml_load(text: str) -> Any:
    """Parse one ERG YAML document under fail-closed strict rules.

    Raises :class:`ErgYAMLStrictError` for any contract violation.
    Returns the parsed document (str/int/bool/None/list/dict only).
    """
    if len(text.encode("utf-8")) > MAX_UTF8_BYTES:
        raise ErgYAMLStrictError(
            f"document is larger than {MAX_UTF8_BYTES} UTF-8 bytes"
        )
    _check_no_directives(text)
    try:
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError as exc:
        raise ErgYAMLStrictError(f"YAML syntax error: {exc}") from exc
    # An empty/whitespace-only file composes to zero documents; a document
    # that is only comments/whitespace composes to a single None node.
    if len(documents) != 1 or documents[0] is None:
        raise ErgYAMLStrictError(
            f"ERG YAML must be exactly one document; found {len(documents)}"
        )
    root = documents[0]
    _walk(root, 1, set())
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:  # pragma: no cover - walk already validated
        raise ErgYAMLStrictError(f"YAML construction error: {exc}") from exc
