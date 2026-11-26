"""Fresh-process import, dependency, and actual module-entrypoint controls."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PKG = "scripts.agent_os_mission_reliability"
TESTS = "tests.agent_os_mission_reliability.test_2766_mission_reliability_measure"
STAMP = "2026-11-25T20:00:00Z"


def _run(code, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "PYTHONPATH")}
    return subprocess.run([sys.executable, "-B", "-c", code, *args], env=env,
                          text=True, capture_output=True, check=False, timeout=20)


@pytest.mark.parametrize("first", (PKG + ".cli", PKG + ".derive", PKG + ".github_source", TESTS))
def test_import_order_has_same_identity_and_no_path_or_token_side_effect(first):
    result = _run(f"""
import importlib, json, os, sys, urllib.request
sites = [ {PKG!r} + s for s in ('', '.__main__', '.args', '.cli', '.derive', '.github_source',
    '.delivery_metrics', '.errors', '.http_client', '.inputs', '.lifecycle_metrics',
    '.metrics', '.outcome_metrics', '.progress_metrics', '.report', '.service') ]
before = list(sys.path)
get = type(os.environ).get
def no_credential(self, key, default=None):
    assert key != 'GITHUB_TOKEN', 'import read credentials'
    return get(self, key, default)
def fail(*a, **k):
    raise AssertionError('import touched the network')
type(os.environ).get = no_credential
urllib.request.urlopen = fail
urllib.request.build_opener = fail
first = importlib.import_module({first!r})
for site in sites:
    assert importlib.import_module(site) is sys.modules[site]
assert before == sys.path
pkg = sys.modules[{PKG!r}]
assert first is sys.modules[{first!r}]
assert pkg.derive_mission_reliability is sys.modules[{PKG!r}+'.derive'].derive_mission_reliability
assert pkg.acquire_mission_records is sys.modules[{PKG!r}+'.github_source'].acquire_mission_records
report = pkg.derive_mission_reliability([{{'issue_number':1}}], window='same')
print(json.dumps([report['window'],len(report['metrics']),report['records_considered']]))
""")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["same", 15, 1]


def test_module_map_has_no_cycles_path_mutation_or_star_imports():
    directory = Path(*PKG.split("."))
    modules = {path.stem: path for path in directory.glob("*.py")}
    graph = {name: set() for name in modules}
    for name, path in modules.items():
        assert len(path.read_text().splitlines()) < 180
        for node in ast.walk(ast.parse(path.read_text())):
            assert not (isinstance(node, ast.Attribute) and node.attr == "path"
                        and isinstance(node.value, ast.Name) and node.value.id == "sys")
            if isinstance(node, ast.ImportFrom):
                assert not any(alias.name == "*" for alias in node.names)
                if node.level and node.module in modules:
                    graph[name].add(node.module)
    def visit(node, seen):
        assert node not in seen
        for child in graph[node]:
            visit(child, seen | {node})
    for module in graph:
        visit(module, set())


_COMMAND = """
import io, json, runpy, sys, urllib.request
target = sys.argv.pop(1)
class Response(io.BytesIO):
    headers = {'Content-Type': 'application/json'}
class Transport:
    def open(self, req, timeout):
        assert req.get_method() == 'GET'
        assert req.get_header('Authorization') is None
        if target == 'bad-body':
            return Response(b'not json')
        if req.full_url.split('?')[0].endswith('/pulls'):
            return Response(b'[]')
        return Response(b'{"number":1,"state":"open"}')
urllib.request.build_opener = lambda *args: Transport()
runpy.run_module('scripts.agent_os_mission_reliability', run_name='__main__')
"""


@pytest.mark.parametrize("mode,extra,code,outcome", [
    ("okay", [], 0, False),
    ("okay", ["--admitted", f"1:{STAMP}"], 0, True),
    ("okay", ["--admitted", f"2:{STAMP}"], 2, "outside_population"),
    ("okay", ["--admitted", "1:bad"], 2, "invalid_timestamp"),
    ("okay", ["--input", "missing.json"], 2, "invalid_arguments"),
    ("bad-body", [], 1, "invalid_json"),
])
def test_module_entrypoint_command_with_offline_transport(mode, extra, code, outcome):
    result = _run(_COMMAND, mode, "--owner", "owner", "--repo", "repo", "--issues", "1,1", *extra)
    assert result.returncode == code and not result.stderr
    data = json.loads(result.stdout)
    if code == 0:
        assert set(data) == {"records", "report"}
        assert data["records"]["frozen_issue_numbers"] == [1]
        assert data["records"]["records"][0]["admitted"] is outcome
    else:
        assert set(data) == {"error"} and data["error"]["code"] == outcome
