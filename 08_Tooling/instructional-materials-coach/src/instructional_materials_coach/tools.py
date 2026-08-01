"""Deny-by-default tool authorization: declarations to the model, handlers to us.

The SDK never receives an executable Python callable. It receives inert
`FunctionDeclaration` objects describing name, description, and input schema.
Handlers stay in this registry, and nothing runs until Agent OS makes an
explicit dispatch decision.

That ordering is the safety control. It is stronger than disabling automatic
function calling, because the SDK cannot invoke what it does not possess --
see `00_Governance/architecture-decisions/adr-0004-model-invocation-boundary.md`.

Flow:
    1. register_read_only_tool(...)     -- handler + immutable metadata, here
    2. sdk_tools(registry)              -- declarations only, to the model
    3. model returns function-call parts
    4. validate_call(...)               -- name and arguments checked
    5. dispatch(...)                    -- explicit, re-authorizes, then runs
"""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Mapping

from google.genai import types

READ_ONLY = "read-only"
_PERMITTED_ACCESS_MODES = frozenset({READ_ONLY})


class ToolAuthorizationError(RuntimeError):
    """Raised when a tool is not provably authorized as read-only."""


@dataclasses.dataclass(frozen=True)
class RegisteredTool:
    """A handler plus immutable authorization metadata.

    `declaration` is what the model sees. `handler` never leaves this process
    boundary and is never passed to the SDK.
    """

    name: str
    declaration: types.FunctionDeclaration
    handler: Callable[..., Any]
    access_mode: str
    allowed_systems: frozenset[str]
    side_effects: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ToolAuthorizationError("Tool name is required.")
        if self.declaration.name != self.name:
            raise ToolAuthorizationError(
                f"Declaration name {self.declaration.name!r} does not match tool name {self.name!r}."
            )
        if self.access_mode not in _PERMITTED_ACCESS_MODES:
            raise ToolAuthorizationError(
                f"Tool {self.name!r} declares unknown access mode {self.access_mode!r}; "
                f"only {sorted(_PERMITTED_ACCESS_MODES)} is permitted."
            )
        if self.side_effects is not False:
            raise ToolAuthorizationError(
                f"Tool {self.name!r} must declare side_effects=False exactly."
            )
        if not self.allowed_systems:
            raise ToolAuthorizationError(
                f"Tool {self.name!r} declares no allowed_systems; metadata is incomplete."
            )
        if not callable(self.handler):
            raise ToolAuthorizationError(f"Tool {self.name!r} has no callable handler.")


class ToolRegistry:
    """Deny-by-default registry. Only what is registered here is model-visible."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register_read_only_tool(
        self,
        *,
        name: str,
        description: str,
        parameters: Mapping[str, Any],
        handler: Callable[..., Any],
        allowed_systems: frozenset[str] | set[str],
        side_effects: bool = False,
    ) -> RegisteredTool:
        """Register a read-only handler and build its inert declaration."""
        declaration = types.FunctionDeclaration(
            name=name, description=description, parameters=dict(parameters)
        )
        tool = RegisteredTool(
            name=name,
            declaration=declaration,
            handler=handler,
            access_mode=READ_ONLY,
            allowed_systems=frozenset(allowed_systems),
            side_effects=side_effects,
        )
        existing = self._tools.get(name)
        if existing is not None and existing != tool:
            raise ToolAuthorizationError(
                f"Tool {name!r} is already registered; a duplicate registration cannot "
                "replace or weaken an existing policy."
            )
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> RegisteredTool:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolAuthorizationError(
                f"Tool {name!r} is not registered; unregistered tools fail closed."
            )
        return tool

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def declarations(self) -> list[types.FunctionDeclaration]:
        """Inert declarations only -- safe to hand to the SDK."""
        return [tool.declaration for tool in self._tools.values()]

    def sdk_tools(self) -> list[types.Tool]:
        """The only supported way to build SDK tools. Contains no callable."""
        declarations = self.declarations()
        if not declarations:
            return []
        return [types.Tool(function_declarations=declarations)]

    def validate_call(self, name: str, args: Mapping[str, Any] | None) -> RegisteredTool:
        """Check a model-requested call against its registration. Fails closed."""
        tool = self.get(name)
        supplied = dict(args or {})
        schema = tool.declaration.parameters or {}
        properties = _schema_properties(schema)
        required = set(_schema_required(schema))

        unknown = set(supplied) - set(properties)
        if unknown:
            raise ToolAuthorizationError(
                f"Tool {name!r} received unexpected arguments: {sorted(unknown)}."
            )
        missing = required - set(supplied)
        if missing:
            raise ToolAuthorizationError(
                f"Tool {name!r} is missing required arguments: {sorted(missing)}."
            )
        return tool

    def dispatch(self, name: str, args: Mapping[str, Any] | None = None) -> Any:
        """Explicit Agent OS decision to run a handler.

        Nothing else in this package invokes a handler. Authorization is
        re-checked here rather than trusted from registration time.
        """
        tool = self.validate_call(name, args)
        if tool.access_mode != READ_ONLY or tool.side_effects is not False:
            raise ToolAuthorizationError(
                f"Tool {name!r} is not authorized read-only at dispatch time."
            )
        return tool.handler(**dict(args or {}))


def _schema_properties(schema: Any) -> Mapping[str, Any]:
    """Read `properties` from either a plain dict or an SDK `types.Schema`.

    The SDK normalizes the dict passed at registration into a `Schema` object,
    so both shapes reach this code depending on the call path.
    """
    props = schema.get("properties") if isinstance(schema, Mapping) else getattr(schema, "properties", None)
    return props if isinstance(props, Mapping) else {}


def _schema_required(schema: Any) -> list[str]:
    required = schema.get("required") if isinstance(schema, Mapping) else getattr(schema, "required", None)
    return list(required) if isinstance(required, list) else []


def assert_no_callable_in_tools(tools: Any) -> None:
    """Guard: refuse to send anything callable to the SDK."""
    for tool in tools or []:
        if callable(tool):
            raise ToolAuthorizationError(
                "A raw callable was passed as an SDK tool. Register it with "
                "ToolRegistry.register_read_only_tool() and send declarations only."
            )
        for declaration in getattr(tool, "function_declarations", None) or []:
            if callable(getattr(declaration, "handler", None)):
                raise ToolAuthorizationError(
                    "A declaration carries an executable handler; declarations must be inert."
                )
