"""Prove the SDK never receives an executable callable.

The guarantee under test is structural: declarations go to the model, handlers
stay here, and nothing runs without an explicit Agent OS dispatch decision.
"""
from __future__ import annotations

import pytest

pytest.importorskip("google.genai", reason="requires the `genai` optional extra")
pytest.importorskip("pydantic", reason="requires the `genai` optional extra")

from google.genai import types  # noqa: E402

from instructional_materials_coach.genai_client import generate  # noqa: E402
from instructional_materials_coach.tools import (  # noqa: E402
    READ_ONLY,
    RegisteredTool,
    ToolAuthorizationError,
    ToolRegistry,
    assert_no_callable_in_tools,
)

PAGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"page_id": {"type": "STRING"}},
    "required": ["page_id"],
}


def read_notion_page(page_id: str) -> str:
    return f"contents of {page_id}"


def delete_notion_page(page_id: str) -> str:  # never registered
    raise AssertionError("a mutating handler must never be invoked")


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register_read_only_tool(
        name="read_notion_page",
        description="Read one Notion page.",
        parameters=PAGE_SCHEMA,
        handler=read_notion_page,
        allowed_systems={"notion"},
    )
    return reg


class FakeModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return "ok"


class FakeClient:
    def __init__(self):
        self.models = FakeModels()


# --- declaration / handler separation --------------------------------------


def test_sdk_config_contains_no_python_callable(registry):
    client = FakeClient()
    generate(client, contents="x", system_instruction="y", tools=registry.sdk_tools())
    config = client.models.calls[0]["config"]
    for tool in config.tools or []:
        assert not callable(tool)
        for declaration in tool.function_declarations or []:
            assert not callable(getattr(declaration, "handler", None))
            assert not hasattr(declaration, "__call__") or not callable(declaration)


def test_sdk_bound_tools_are_declarations_only(registry):
    sdk_tools = registry.sdk_tools()
    assert len(sdk_tools) == 1
    declarations = sdk_tools[0].function_declarations
    assert [d.name for d in declarations] == ["read_notion_page"]
    assert all(isinstance(d, types.FunctionDeclaration) for d in declarations)


def test_handlers_stay_private_to_the_registry(registry):
    """The handler is reachable from the registry, never from the SDK payload."""
    assert registry.get("read_notion_page").handler is read_notion_page
    serialized = registry.sdk_tools()[0].model_dump_json()
    assert "read_notion_page" in serialized  # the name travels
    assert "contents of" not in serialized  # the implementation does not


def test_arbitrary_callable_cannot_be_passed_directly():
    client = FakeClient()
    with pytest.raises(ToolAuthorizationError, match="raw callable"):
        generate(client, contents="x", system_instruction="y", tools=[read_notion_page])
    assert client.models.calls == [], "must refuse before dispatching"


def test_assert_no_callable_in_tools_rejects_bare_functions():
    with pytest.raises(ToolAuthorizationError):
        assert_no_callable_in_tools([delete_notion_page])


# --- registration policy ---------------------------------------------------


def test_mutating_tool_is_rejected_by_metadata():
    reg = ToolRegistry()
    with pytest.raises(ToolAuthorizationError, match="side_effects=False"):
        reg.register_read_only_tool(
            name="delete_notion_page",
            description="Delete a page.",
            parameters=PAGE_SCHEMA,
            handler=delete_notion_page,
            allowed_systems={"notion"},
            side_effects=True,
        )


def test_missing_metadata_is_rejected():
    reg = ToolRegistry()
    with pytest.raises(ToolAuthorizationError, match="allowed_systems"):
        reg.register_read_only_tool(
            name="read_notion_page",
            description="Read one Notion page.",
            parameters=PAGE_SCHEMA,
            handler=read_notion_page,
            allowed_systems=set(),
        )


def test_unknown_access_mode_is_rejected():
    with pytest.raises(ToolAuthorizationError, match="unknown access mode"):
        RegisteredTool(
            name="x",
            declaration=types.FunctionDeclaration(name="x", description="d", parameters={}),
            handler=read_notion_page,
            access_mode="read-write",
            allowed_systems=frozenset({"notion"}),
            side_effects=False,
        )


def test_contradictory_metadata_is_rejected():
    with pytest.raises(ToolAuthorizationError):
        RegisteredTool(
            name="x",
            declaration=types.FunctionDeclaration(name="mismatched", description="d", parameters={}),
            handler=read_notion_page,
            access_mode=READ_ONLY,
            allowed_systems=frozenset({"notion"}),
            side_effects=False,
        )


def test_duplicate_declaration_cannot_weaken_registration(registry):
    with pytest.raises(ToolAuthorizationError, match="cannot"):
        registry.register_read_only_tool(
            name="read_notion_page",
            description="Read one Notion page.",
            parameters=PAGE_SCHEMA,
            handler=delete_notion_page,  # swapped handler
            allowed_systems={"notion"},
        )
    assert registry.get("read_notion_page").handler is read_notion_page


def test_identical_reregistration_is_idempotent(registry):
    registry.register_read_only_tool(
        name="read_notion_page",
        description="Read one Notion page.",
        parameters=PAGE_SCHEMA,
        handler=read_notion_page,
        allowed_systems={"notion"},
    )
    assert registry.names() == frozenset({"read_notion_page"})


def test_wrapped_tool_retains_registered_policy(registry):
    """Re-fetching does not launder the policy into something weaker."""
    tool = registry.get("read_notion_page")
    assert tool.access_mode == READ_ONLY
    assert tool.side_effects is False
    with pytest.raises(Exception):
        tool.side_effects = True  # frozen


# --- call validation and dispatch ------------------------------------------


def test_model_tool_name_must_match_a_registration(registry):
    assert registry.validate_call("read_notion_page", {"page_id": "p1"}).name == "read_notion_page"


def test_unknown_tool_name_fails_closed(registry):
    with pytest.raises(ToolAuthorizationError, match="not registered"):
        registry.validate_call("delete_notion_page", {"page_id": "p1"})


def test_extra_arguments_fail_schema_validation(registry):
    with pytest.raises(ToolAuthorizationError, match="unexpected arguments"):
        registry.validate_call("read_notion_page", {"page_id": "p1", "force": True})


def test_missing_required_argument_fails_schema_validation(registry):
    with pytest.raises(ToolAuthorizationError, match="missing required arguments"):
        registry.validate_call("read_notion_page", {})


def test_function_call_response_executes_nothing():
    """Receiving and validating a model function call runs no handler."""
    ran = []

    def spy(page_id: str) -> str:
        ran.append(page_id)
        return "should not happen"

    reg = ToolRegistry()
    reg.register_read_only_tool(
        name="read_notion_page",
        description="Read one Notion page.",
        parameters=PAGE_SCHEMA,
        handler=spy,
        allowed_systems={"notion"},
    )

    call = types.FunctionCall(name="read_notion_page", args={"page_id": "p1"})
    reg.validate_call(call.name, call.args)

    assert ran == [], "validating a model function call must not invoke the handler"
    reg.dispatch(call.name, call.args)
    assert ran == ["p1"], "only an explicit dispatch runs the handler"


def test_execution_requires_explicit_dispatcher_call(registry):
    assert registry.dispatch("read_notion_page", {"page_id": "p1"}) == "contents of p1"


def test_dispatcher_rechecks_read_only_authorization(registry):
    """Authorization is re-verified at dispatch, not trusted from registration."""
    tool = registry.get("read_notion_page")
    # Bypass the frozen dataclass to simulate post-registration policy drift.
    object.__setattr__(tool, "side_effects", True)
    with pytest.raises(ToolAuthorizationError, match="not authorized read-only"):
        registry.dispatch("read_notion_page", {"page_id": "p1"})
