"""Tests for the #3689 Pyan3 advisory runner.

Graph-logic tests run offline with stub visitors; integration tests use the
real pinned Pyan3 on deterministic fixtures and skip when it is not installed.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.pyan3_advisory import (
    VERSION,
    _classify,
    _import_cycles,
    _safe_detail,
    _strongly_connected,
    scan,
)


def test_safe_detail_redacts_host_paths_and_secrets() -> None:
    detail = _safe_detail(
        OSError(13, "Permission denied", "/home/runner/token.json")
    )
    assert "/home/runner" not in detail
    assert "[path]" in detail
    secret = _safe_detail(ValueError("token=abc123secret"))
    assert "abc123secret" not in secret


class _FakeNode:
    __hash__ = object.__hash__

    def __init__(self, namespace, name, flavor, defined, filename, lineno, decorated):
        self.namespace = namespace
        self.name = name
        self.flavor = flavor
        self.defined = defined
        self.filename = filename
        self.ast_node = SimpleNamespace(
            lineno=lineno, decorator_list=[object()] if decorated else [])


def _node(namespace, name, flavor="Flavor.FUNCTION", defined=True, filename="pkg/a.py",
          lineno=1, decorated=False):
    return _FakeNode(namespace, name, flavor, defined, filename, lineno, decorated)


class _Visitor:
    def __init__(self, nodes, uses):
        self.nodes = {}
        for node in nodes:
            self.nodes.setdefault(node.name, []).append(node)
        self.uses_edges = uses
        self.defines_edges = {}


def _patch_visitor(monkeypatch, visitor=None, exc=None):
    def fake(files, root):
        if exc is not None:
            raise exc
        return visitor

    monkeypatch.setattr("scripts.pyan3_advisory._make_visitor", fake)


def _write_pkg(root: Path) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text(
        "import importlib\nimport pkg.b as b\nfrom pkg.b import helper as h\n\n"
        "def main():\n    b.work()\n    h()\n    helper_local()\n    unknown_dynamic()\n\n"
        "def helper_local():\n    return 42\n\n"
        "def unused_fn():\n    return 'nobody'\n\n"
        "def dynamic_caller():\n    mod = importlib.import_module('pkg.b')\n    return mod.work2()\n\n"
        "def cycle_x():\n    return cycle_y()\n\n"
        "def cycle_y():\n    return cycle_x()\n\n"
        "def test_only_target():\n    return 'tests only'\n\n"
        "REGISTRY = {}\n"
        "def register(fn):\n    REGISTRY[fn.__name__] = fn\n    return fn\n\n"
        "@register\ndef plugin_entry():\n    return 'registered'\n",
        encoding="utf-8")
    (root / "pkg" / "b.py").write_text(
        "import pkg.a as a\n\n"
        "def work():\n    return helper()\n\n"
        "def helper():\n    return work2()\n\n"
        "def work2():\n    return a is not None\n",
        encoding="utf-8")
    (root / "tests" / "test_a.py").write_text(
        "import pkg.a as a\n\ndef test_target():\n    assert a.test_only_target()\n",
        encoding="utf-8")


# --- pure graph logic (no Pyan3 required) ---

def test_scc_finds_cycle_self_loop_and_ignores_acyclic():
    graph = {"a": {"b"}, "b": {"a"}, "c": {"c"}, "d": {"a"}, "e": set()}
    assert _strongly_connected(graph) == [["a", "b"], ["c"]]


def test_import_cycles_from_ast(tmp_path):
    _write_pkg(tmp_path)
    files = sorted(tmp_path.rglob("*.py"))
    assert _import_cycles(tmp_path, files) == [["pkg.a", "pkg.b"]]


def test_classify_candidate_test_only_and_exclusions():
    nodes = [
        {"id": "pkg.a.used", "kind": "function", "file": "pkg/a.py", "line": 1, "decorated": False},
        {"id": "pkg.a.tested", "kind": "function", "file": "pkg/a.py", "line": 2, "decorated": False},
        {"id": "pkg.a.orphan", "kind": "function", "file": "pkg/a.py", "line": 3, "decorated": False},
        {"id": "pkg.a.plugin", "kind": "function", "file": "pkg/a.py", "line": 4, "decorated": True},
        {"id": "pkg.a.main", "kind": "function", "file": "pkg/a.py", "line": 5, "decorated": False},
        {"id": "tests.test_a.t", "kind": "function", "file": "tests/test_a.py", "line": 1, "decorated": False},
    ]
    edges = [
        {"from": "pkg.a.used", "to": "pkg.a.used", "type": "uses"},
        {"from": "pkg.a.main", "to": "pkg.a.used", "type": "uses"},
        {"from": "tests.test_a.t", "to": "pkg.a.tested", "type": "uses"},
    ]
    candidates, test_only, decorated = _classify(nodes, edges)
    assert [c["id"] for c in candidates] == ["pkg.a.orphan"]
    assert [t["id"] for t in test_only] == ["pkg.a.tested"]
    assert decorated == 1


def test_scan_scanner_failure_is_evidence_not_fatal(tmp_path, monkeypatch):
    _write_pkg(tmp_path)
    _patch_visitor(monkeypatch, exc=RuntimeError("boom"))
    result = scan(tmp_path, tmp_path / "out", sha="a" * 40, scope=("pkg", "tests"))
    assert result["status"] == "scanner-error"
    assert "boom" in result["detail"]
    assert json.loads((tmp_path / "out" / "pyan3-advisory.json").read_text())["status"] == "scanner-error"
    assert (tmp_path / "out" / "pyan3-advisory.md").exists()


def test_scan_missing_tool_is_scanner_error(tmp_path, monkeypatch):
    _write_pkg(tmp_path)
    _patch_visitor(monkeypatch, exc=ImportError("No module named 'pyan'"))
    result = scan(tmp_path, tmp_path / "out", sha="b" * 40, scope=("pkg", "tests"))
    assert result["status"] == "scanner-error"


def test_scan_truncates_large_candidate_set(tmp_path, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    nodes = [_node("pkg.a", f"fn{i}", filename=str(tmp_path / "pkg" / "a.py")) for i in range(105)]
    _patch_visitor(monkeypatch, visitor=_Visitor(nodes, {}))
    result = scan(tmp_path, tmp_path / "out", sha="c" * 40, scope=("pkg",))
    assert result["candidate_count"] == 105
    assert len(result["candidates"]) == 100
    assert result["candidates_truncated"]


def test_scan_stub_graph_edges_and_unresolved(tmp_path, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    caller = _node("pkg.a", "main", filename=str(tmp_path / "pkg" / "a.py"))
    callee = _node("pkg.a", "work", filename=str(tmp_path / "pkg" / "a.py"))
    ghost = _node("*", "mystery", flavor="Flavor.UNKNOWN", defined=False)
    _patch_visitor(monkeypatch, visitor=_Visitor([caller, callee], {caller: {callee, ghost}}))
    result = scan(tmp_path, tmp_path / "out", sha="d" * 40, scope=("pkg",))
    assert result["status"] == "ok"
    assert result["edge_count"] == 1
    assert result["unresolved"] == [{"from": "pkg.a.main", "target": "*.mystery"}]
    assert result["version"] == VERSION
    assert result["head_sha"] == "d" * 40


def test_scan_dedupes_bare_unresolved_duplicate_of_resolved_edge(tmp_path, monkeypatch):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    caller = _node("pkg.a", "main", filename=str(tmp_path / "pkg" / "a.py"))
    callee = _node("pkg.a", "work", filename=str(tmp_path / "pkg" / "a.py"))
    bare_dup = _node(None, "work", flavor="Flavor.UNKNOWN", defined=False)
    bare_kept = _node(None, "other", flavor="Flavor.UNKNOWN", defined=False)
    _patch_visitor(monkeypatch, visitor=_Visitor([caller, callee], {caller: {callee, bare_dup, bare_kept}}))
    result = scan(tmp_path, tmp_path / "out", sha="f" * 40, scope=("pkg",))
    assert result["unresolved"] == [{"from": "pkg.a.main", "target": "other"}]
    assert result["unresolved_count"] == 1


# --- real Pyan3 integration on deterministic fixtures ---

def test_real_pyan_fixture_end_to_end(tmp_path):
    pytest.importorskip("pyan", reason="pyan3 not installed in this environment")
    from importlib.metadata import version

    if version("pyan3") != VERSION:
        pytest.skip(f"pinned pyan3 {VERSION} not installed")
    _write_pkg(tmp_path)
    result = scan(tmp_path, tmp_path / "out", sha="e" * 40, scope=("pkg", "tests"))
    assert result["status"] == "ok"
    assert result["file_count"] == 3
    graph = json.loads((tmp_path / "out" / "raw" / "pyan3-graph.json").read_text())
    edge_pairs = {(e["from"], e["to"]) for e in graph["edges"]}
    # direct call and import alias both resolve to real edges
    assert ("pkg.a.main", "pkg.b.work") in edge_pairs
    assert ("pkg.a.main", "pkg.b.helper") in edge_pairs
    assert ("pkg.a.main", "pkg.a.helper_local") in edge_pairs
    # cycles: import cycle and call cycle are distinct findings
    assert result["import_cycles"] == [["pkg.a", "pkg.b"]]
    assert ["pkg.a.cycle_x", "pkg.a.cycle_y"] in result["call_cycles"]
    # unresolved dynamic/unresolvable calls are recorded, not hidden
    targets = {u["target"] for u in result["unresolved"]}
    assert "unknown_dynamic" in targets
    assert result["unresolved_count"] >= 2
    # disconnected candidate, test-only reference, decorated plugin are distinct
    candidate_ids = {c["id"] for c in result["candidates"]}
    assert "pkg.a.unused_fn" in candidate_ids
    assert "pkg.a.test_only_target" not in candidate_ids
    assert "pkg.a.plugin_entry" not in candidate_ids
    assert [t["id"] for t in result["test_only_referenced"]] == ["pkg.a.test_only_target"]
    assert result["decorated_excluded_count"] == 1
    # advisory language: candidates are never asserted unreachable
    assert "not proof of runtime unreachability" in result["limitations"]
    report = (tmp_path / "out" / "pyan3-advisory.md").read_text()
    assert "#1729" in report
