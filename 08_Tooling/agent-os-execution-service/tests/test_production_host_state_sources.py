from __future__ import annotations

import ast
import inspect

import agent_os_execution_service.handoff_publication as publication
import agent_os_execution_service.production_host_state_sources as sources


def test_production_source_surface_has_all_seven_slots():
    required = {
        "route_decision",
        "handoff",
        "checkpoint",
        "resume_plan",
        "candidate_packet",
        "runtime_configuration",
        "pilot_input",
    }
    assert required <= set(vars(sources.ProductionHostStateSources))


def test_production_sources_have_no_network_process_or_cloud_imports():
    tree = ast.parse(inspect.getsource(sources))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    forbidden = ("subprocess", "requests", "httpx", "github", "google.cloud", "paramiko")
    assert not [name for name in imports if name.startswith(forbidden)]


def test_restart_capsule_is_persisted_before_descriptor():
    source = inspect.getsource(publication.publish_governed_handoff)
    assert source.index("append_restart_capsule") < source.index(
        "persist_current_invocation_descriptor"
    )
