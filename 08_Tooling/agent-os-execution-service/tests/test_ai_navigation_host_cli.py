"""Local validation-only caller tests (local candidate; not registered or installed anywhere).

Real: argument handling, environment-location rules, composition from evidence, routing producer,
trusted host, pathway, registries, receipt/journal files.
Named doubles: the host bootstrap/resolver (no real checkpoint store or credentialed GitHub read),
authorization transport and route decision (as in the other navigation tests).
NOT exercised: the production bootstrap against a real checkpoint store and live GitHub.
"""
from __future__ import annotations

import ast
import io
import json
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from test_ai_navigation_pathway import nav
from test_ai_navigation_trusted_host import _comp, _parts, REG, CAPS
from test_ai_navigation_invocation_routing import _pair, _clock
import agent_os_execution_service.ai_navigation_host_cli as cli
from agent_os_execution_service.ai_navigation_trusted_host import DispatchJournal

NOW = _clock()
NOW_TEXT = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _env(tmp_path, **over):
    env = {cli.JOURNAL_DIR_ENV: str(tmp_path / "j"), cli.RECEIPT_PATH_ENV: str(tmp_path / "r" / "nav.jsonl"),
           cli.REGISTRY_DIR_ENV: str(REG), cli.CAPABILITY_REGISTRY_ENV: str(CAPS)}
    env.update(over)
    return {k: v for k, v in env.items() if v is not None}


def _setup():
    request, plan, descriptor, decision, plan_id = _pair()
    return request, plan, descriptor, plan_id, decision


def _evidence(decision):
    return SimpleNamespace(route_decision=decision, pilot_input="PILOT", runtime_configuration="CONFIG",
                           candidate_packet=SimpleNamespace())


def test_compose_binds_everything_from_evidence_and_trusted_inputs(tmp_path, monkeypatch):
    request, plan, descriptor, plan_id, decision = _setup()
    monkeypatch.setattr("scripts.agent_os_candidate_packet.models.candidate_packet_id", lambda p: "candidate-packet:x")
    comp = cli.compose_from_current_evidence(descriptor=descriptor, evidence=_evidence(decision),
                                             evaluated_at_moment=NOW, transport="TRANSPORT", environ=_env(tmp_path))
    assert comp.host.pilot_input == "PILOT" and comp.host.configuration == "CONFIG" and comp.host.cancelled() is False
    assert comp.invocation_id == descriptor.invocation_id and comp.operation == "validation-only"
    assert comp.candidate_packet_id == "candidate-packet:x" and comp.clock() == NOW and comp.transport == "TRANSPORT"
    routing = comp.routing_evidence_provider(request, plan)
    assert routing.workflow_runtime_identity == descriptor.workflow_runtime_identity
    assert comp.execute_read is None  # CKR6 read transport is not invented


@pytest.mark.parametrize("name", list(cli._REQUIRED_ENV))
def test_missing_or_relative_location_refuses_without_touching_host(tmp_path, name):
    for bad in (None, "", "relative/path"):
        called = []
        with pytest.raises(cli.NavigationCallerError):
            cli.build_composition_for_handoff("h", _env(tmp_path, **{name: bad}), bootstrap_factory=lambda h: called.append(h))
        assert called == []


def test_bootstrap_without_descriptor_or_failure_refuses(tmp_path):
    class MustNotRun:
        def __init__(self, **k): pytest.fail("resolver must not be built without a descriptor")
    with pytest.raises(cli.NavigationCallerError) as missing:
        cli.build_composition_for_handoff("h", _env(tmp_path), bootstrap_factory=lambda h: SimpleNamespace(runtime_request=None),
                                          resolver_class=MustNotRun)
    assert "no runtime request or invocation descriptor" in str(missing.value)
    def boom(h):
        raise OSError("store")
    with pytest.raises(cli.NavigationCallerError) as e:
        cli.build_composition_for_handoff("h", _env(tmp_path), bootstrap_factory=boom)
    assert "OSError" in str(e.value)


def test_resolver_failure_refuses_and_success_composes(tmp_path, monkeypatch):
    request, plan, descriptor, plan_id, decision = _setup()
    monkeypatch.setattr("scripts.agent_os_candidate_packet.models.candidate_packet_id", lambda p: "candidate-packet:x")
    bootstrap = SimpleNamespace(runtime_request=SimpleNamespace(invocation_descriptor=descriptor), sources="S",
                                authorization_transport="T", evaluated_at=NOW_TEXT)

    class Failing:
        def __init__(self, **k): pass
        def reacquire(self, d): raise RuntimeError("authorization non-current")

    class Good:
        seen = {}
        def __init__(self, **k): Good.seen = k
        def reacquire(self, d):
            assert d is descriptor
            return _evidence(decision)
    with pytest.raises(cli.NavigationCallerError):
        cli.build_composition_for_handoff("h", _env(tmp_path), bootstrap_factory=lambda h: bootstrap, resolver_class=Failing)
    comp = cli.build_composition_for_handoff("h", _env(tmp_path), bootstrap_factory=lambda h: bootstrap, resolver_class=Good)
    assert Good.seen == {"sources": "S", "authorization_transport": "T", "evaluated_at": NOW_TEXT}
    assert comp.clock() == NOW and comp.transport == "T"


def _run(argv, builder, env=None):
    out = io.StringIO()
    code = cli.main(argv, environ=env, composition_builder=builder, stdout=out)
    return code, json.loads(out.getvalue())


def test_main_usage_and_unreadable_work_file_refuse(tmp_path):
    for argv in ([], ["--handoff-id", "h"], ["--work", "f", "--handoff-id", "h"], ["--handoff-id", "h", "--work", str(tmp_path / "missing")]):
        code, out = _run(argv, lambda h: pytest.fail("must not compose"))
        assert code == 2 and not out["execution_attempted"]
    bad = tmp_path / "w.json"; bad.write_text("{not json")
    code, out = _run(["--handoff-id", "h", "--work", str(bad)], lambda h: pytest.fail("must not compose"))
    assert code == 2


def test_main_composition_refusal_and_unexpected_error_never_dispatch(tmp_path):
    work = tmp_path / "w.json"; work.write_text("{}")
    def refuse(h): raise cli.NavigationCallerError("no store")
    def explode(h): raise KeyError("x")
    assert _run(["--handoff-id", "h", "--work", str(work)], refuse)[0] == 2
    code, out = _run(["--handoff-id", "h", "--work", str(work)], explode)
    assert code == 2 and out["reason_codes"][0] == "host-composition-error" and not out["execution_attempted"]


def test_main_end_to_end_completes_once_then_refuses_replay(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    work = tmp_path / "w.json"; work.write_text(json.dumps(payload))
    argv = ["--handoff-id", "h", "--work", str(work)]
    code, out = _run(argv, lambda h: comp)
    assert code == 0 and out["status"] == "completed" and out["execution_attempted"] and out["receipt_persisted"]
    calls = []
    monkeypatch.setattr(nav, "compose_and_run_validation", lambda **k: calls.append(1))
    code2, out2 = _run(argv, lambda h: comp)
    assert code2 == 2 and out2["reason_codes"][0] == "dispatch-already-recorded" and calls == []


def test_main_payload_cannot_carry_routing_or_authorization(tmp_path, monkeypatch):
    payload, comp = _comp(tmp_path, monkeypatch, payload_parts=_parts())
    for key in ("routing_evidence", "authorization", "evaluated_at"):
        work = tmp_path / f"{key}.json"; work.write_text(json.dumps({**payload, key: {"x": 1}}))
        code, out = _run(["--handoff-id", "h", "--work", str(work)], lambda h: comp)
        assert code == 2 and not out["execution_attempted"]


def test_module_is_local_only_no_network_scripts_or_fixture_defaults():
    src = pathlib.Path(cli.__file__).read_text()
    tree = ast.parse(src)
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not mods & {"subprocess", "socket", "urllib", "http", "requests", "shutil"}
    assert "tests" not in " ".join(mods) and "test_" not in src.replace("test_environment", "")
    root = pathlib.Path(cli.__file__).parents[2]
    assert "ai_navigation_host_cli" not in (root / "pyproject.toml").read_text()  # not a registered console script


def test_exit_code_requires_a_persisted_receipt(tmp_path, monkeypatch):
    work = tmp_path / "w.json"; work.write_text("{}")
    monkeypatch.setattr(cli, "run_trusted_host_navigation", lambda p, c: {"status": "completed", "receipt_persisted": False})
    assert _run(["--handoff-id", "h", "--work", str(work)], lambda h: object())[0] == 2
    monkeypatch.setattr(cli, "run_trusted_host_navigation", lambda p, c: {"status": "completed", "receipt_persisted": True})
    assert _run(["--handoff-id", "h", "--work", str(work)], lambda h: object())[0] == 0


def test_cli_routing_provider_uses_the_bootstrap_moment_for_expiry(tmp_path, monkeypatch):
    from datetime import timedelta
    from agent_os_execution_service.models import parse_canonical_utc
    request, plan, descriptor, plan_id, decision = _setup()
    monkeypatch.setattr("scripts.agent_os_candidate_packet.models.candidate_packet_id", lambda p: "candidate-packet:x")
    late = parse_canonical_utc(decision.expires_at) + timedelta(seconds=1)
    comp = cli.compose_from_current_evidence(descriptor=descriptor, evidence=_evidence(decision),
                                             evaluated_at_moment=late, transport="T", environ=_env(tmp_path))
    assert comp.routing_evidence_provider(request, plan) is None


def test_composition_failure_reports_class_chain_but_never_messages(tmp_path):
    def boom(h):
        try:
            raise FileNotFoundError("/secret/store/path token-ABC123")
        except FileNotFoundError as root:
            raise RuntimeError("outer message token-XYZ789") from root
    with pytest.raises(cli.NavigationCallerError) as e:
        cli.build_composition_for_handoff("h", _env(tmp_path), bootstrap_factory=boom)
    text = str(e.value)
    assert "RuntimeError <- FileNotFoundError" in text
    assert "secret" not in text and "ABC123" not in text and "XYZ789" not in text


def test_failure_chain_is_bounded_and_cycle_safe():
    a, b = RuntimeError("a"), ValueError("b")
    a.__cause__, b.__cause__ = b, a
    assert cli._failure_chain(a) == "RuntimeError <- ValueError"
