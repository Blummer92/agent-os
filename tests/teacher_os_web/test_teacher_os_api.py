"""Teacher OS loopback API (#2801): trust boundary, fail-closed admission, real-process contract.

Every data record used here is SYNTHETIC (see ``fixture_api``) and every
admission is a TEST-ONLY object. Nothing in this file is live Notion evidence.
The production server is exercised as a real process to prove that, with no
canonical Teacher OS admission class, it refuses every read.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from .fixture_api import (
    UNIT_COLOR,
    UNIT_DRAFT,
    UNIT_EMPTY,
    UNIT_FOREIGN,
    UNIT_REVIEW,
    UNIT_TYPE,
    StubExecutor,
    build_api,
    synthetic_test_admission,
    teacher_os_api,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER = REPO_ROOT / "08_Tooling" / "teacher-os-web" / "server" / "teacher_os_api.py"
FIXTURE = Path(__file__).with_name("fixture_api.py")
PORT = 8790
SECRET = "s" * 43
WEB_ORIGIN = "http://127.0.0.1:4175"
UNITS = "/api/teacher-os/units"


def lessons_path(unit_id: str) -> str:
    return f"{UNITS}/{unit_id}/lessons"


def headers(**extra: str) -> dict[str, str]:
    base = {"Host": f"127.0.0.1:{PORT}", "Authorization": f"Bearer {SECRET}", "Accept": "application/json"}
    base.update(extra)
    return {k: v for k, v in base.items() if v is not None}


class CountingAdmission:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def __call__(self):
        self.calls += 1
        return self.value


@pytest.fixture
def api():
    stub = StubExecutor()
    admission = CountingAdmission(synthetic_test_admission())
    built, _ = build_api(PORT, SECRET, {WEB_ORIGIN}, stub=stub, admission=admission)
    return built, stub, admission


# --------------------------------------------------------------- trust boundary
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def test_only_get_is_served(api, method):
    built, stub, admission = api
    status, body = built.handle(method, UNITS, headers(), 0)
    assert (status, body["reason_code"]) == (405, "method-not-allowed")
    assert admission.calls == stub.factory_calls == 0


@pytest.mark.parametrize("auth", [None, "", "Bearer", "Bearer ", f"bearer {SECRET}", f"Basic {SECRET}", "Bearer " + "s" * 42, "Bearer " + "s" * 44, f"Bearer {SECRET} "])
def test_unauthenticated_requests_are_refused_before_admission_or_executor(api, auth):
    built, stub, admission = api
    status, body = built.handle("GET", UNITS, headers(Authorization=auth), 0)
    assert (status, body) == (401, {"schema_version": body["schema_version"], "result_kind": "agent-os-teacher-os-read-result", "status": "error", "reason_code": "unauthenticated"})
    assert admission.calls == stub.factory_calls == 0 and stub.calls == []


@pytest.mark.parametrize("host", [None, "evil.example", "evil.example:8790", "127.0.0.1", "127.0.0.1:9999", "0.0.0.0:8790", "[::1]:8790"])
def test_host_header_must_name_this_loopback_listener(api, host):
    built, stub, admission = api
    status, body = built.handle("GET", UNITS, headers(Host=host), 0)
    assert (status, body["reason_code"]) == (403, "host-not-allowed")
    assert admission.calls == stub.factory_calls == 0


@pytest.mark.parametrize("extra", [
    {"Origin": "http://127.0.0.1:3000"}, {"Origin": "https://evil.example"}, {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
])
def test_cross_site_requests_are_refused(api, extra):
    built, stub, admission = api
    status, body = built.handle("GET", UNITS, headers(**extra), 0)
    assert (status, body["reason_code"]) == (403, "origin-not-allowed")
    assert admission.calls == stub.factory_calls == 0


def test_same_origin_browser_request_through_the_vite_origin_is_accepted(api):
    built, _, _ = api
    status, body = built.handle("GET", UNITS, headers(Origin=WEB_ORIGIN, **{"Sec-Fetch-Site": "same-origin"}), 0)
    assert status == 200 and body["status"] == "ok"


@pytest.mark.parametrize("path", [
    "/api/teacher-os/units?limit=5", "/api/teacher-os/units/%2e%2e/lessons", "/api/teacher-os/units/../units",
    f"/api/teacher-os/units/{UNIT_COLOR.upper()}/lessons", f"/api/teacher-os/units/{UNIT_COLOR.replace('-', '')}/lessons",
    "/api/teacher-os/units/not-a-uuid/lessons", f"/api/teacher-os/units/{UNIT_COLOR}/lessons/extra",
    f"/api/teacher-os/units/{UNIT_COLOR}", "/api/teacher-os/units/" + "a" * 200,
])
def test_malformed_paths_are_rejected_before_admission(api, path):
    built, stub, admission = api
    status, body = built.handle("GET", path, headers(), 0)
    assert status == 400 and body["reason_code"] == "invalid-request"
    assert admission.calls == stub.factory_calls == 0


def test_unknown_route_is_not_found_and_body_is_refused(api):
    built, stub, admission = api
    assert built.handle("GET", "/api/other", headers(), 0)[1]["reason_code"] == "not-found"
    assert built.handle("GET", UNITS, headers(), 5)[1]["reason_code"] == "invalid-request"
    assert built.handle("GET", UNITS, headers(**{"Transfer-Encoding": "chunked"}), 0)[1]["reason_code"] == "invalid-request"
    assert admission.calls == stub.factory_calls == 0


def test_read_budget_limits_requests(api):
    built, _, _ = api
    built.budget = teacher_os_api.ReadBudget(limit=2, window=60, clock=lambda: 0.0)
    assert [built.handle("GET", UNITS, headers(), 0)[0] for _ in range(3)] == [200, 200, 429]


def test_short_or_missing_session_secret_refuses_to_construct():
    for bad in ("", "short", None):
        with pytest.raises(ValueError):
            teacher_os_api.TeacherOsApi(session_secret=bad, port=PORT)
    with pytest.raises(ValueError):
        teacher_os_api.TeacherOsApi(session_secret=SECRET, port=PORT, allowed_origins=frozenset({"https://evil.example"}))


# --------------------------------------------------------------- admission
def test_production_admission_provider_has_no_canonical_teacher_os_class():
    assert teacher_os_api.canonical_teacher_os_admission() is None


@pytest.mark.parametrize("admission", [
    None,
    "admitted",
    teacher_os_api.NotionReadAdmission(status="rejected", reason_codes=("x",), repository="Blummer92/agent-os", secret_dispatch_authorized=False),
    teacher_os_api.NotionReadAdmission(status="admitted", reason_codes=("admitted",), repository="Blummer92/agent-os", secret_dispatch_authorized=True, required_logical_sources=("canonical-unit",)),
    teacher_os_api.NotionReadAdmission(status="admitted", reason_codes=("admitted",), repository="Blummer92/agent-os", secret_dispatch_authorized=True, canonical_unit_key="photography", required_logical_sources=("canonical-unit", "daily-generation-packet")),
])
def test_missing_or_wrong_scope_admission_is_unavailable_and_never_builds_the_executor(admission):
    stub = StubExecutor()
    built, _ = build_api(PORT, SECRET, stub=stub, admission=lambda: admission)
    for path in (UNITS, lessons_path(UNIT_COLOR)):
        status, body = built.handle("GET", path, headers(), 0)
        assert (status, body["status"], body["reason_code"]) == (503, "unavailable", "admission-required")
    assert stub.factory_calls == 0 and stub.calls == []


def test_production_server_policy_never_reaches_the_live_factory():
    calls = []
    built = teacher_os_api.TeacherOsApi(session_secret=SECRET, port=PORT, factory_provider=lambda: calls.append("factory") or (lambda: None))
    status, body = built.handle("GET", UNITS, headers(), 0)
    assert (status, body["reason_code"]) == (503, "admission-required") and calls == []


# --------------------------------------------------------------- governed reads (synthetic)
def test_units_lists_only_active_unreviewed_units_with_provenance(api):
    built, stub, _ = api
    status, body = built.handle("GET", UNITS, headers(), 0)
    assert status == 200 and body["status"] == "ok"
    ids = [u["unit_id"] for u in body["units"]]
    assert set(ids) == {UNIT_COLOR, UNIT_TYPE, UNIT_EMPTY, UNIT_FOREIGN}
    assert UNIT_DRAFT not in ids and UNIT_REVIEW not in ids
    assert body["source"] == {"logical_source": "canonical-unit", "display_name": "Canonical Digital Media Unit Registry", "verification_state": "verified-current", "access": "read-only"}
    assert body["generated_at"].endswith("Z") and stub.factory_calls == 1


def test_lessons_project_only_the_governed_fields(api):
    built, _, _ = api
    status, body = built.handle("GET", lessons_path(UNIT_COLOR), headers(), 0)
    assert status == 200 and body["status"] == "ok" and len(body["lessons"]) == 3
    assert body["unit"]["unit_id"] == UNIT_COLOR
    for lesson in body["lessons"]:
        assert set(lesson) == {"daily_learning_target", "daily_focus", "key_vocabulary", "canonical_unit", "source_evidence", "day_lesson_number", "record_url"}
    assert "internal planning text" not in json.dumps(body)
    assert body["lessons"][2]["daily_learning_target"] is None  # empty is never invented


@pytest.mark.parametrize("unit,expected", [
    (UNIT_DRAFT, (404, "unit-not-approved")), (UNIT_REVIEW, (404, "unit-not-approved")),
    ("5e0c0000-0000-4000-8000-00000000dead", (404, "unit-not-approved")),
    (UNIT_FOREIGN, (502, "read-failed")),
])
def test_unapproved_unknown_and_foreign_unit_reads_fail_closed(api, unit, expected):
    built, stub, _ = api
    status, body = built.handle("GET", lessons_path(unit), headers(), 0)
    assert (status, body["reason_code"]) == expected
    assert "lessons" not in body and "Synthetic focus" not in json.dumps(body)
    lesson_queries = [c for c in stub.calls if c.get("filter")]
    if expected[1] == "unit-not-approved":
        assert lesson_queries == []  # never queried lessons for an unapproved unit


def test_approved_unit_without_lessons_is_empty_not_filled(api):
    built, _, _ = api
    status, body = built.handle("GET", lessons_path(UNIT_EMPTY), headers(), 0)
    assert status == 200 and body["status"] == "empty" and body["lessons"] == []


def test_executor_failure_is_a_closed_error_without_provider_text():
    class Boom(StubExecutor):
        def execute(self, payload):
            raise RuntimeError("provider said: secret-ish detail")

    built, _ = build_api(PORT, SECRET, stub=Boom())
    status, body = built.handle("GET", UNITS, headers(), 0)
    assert (status, body["reason_code"]) == (502, "read-failed") and "secret-ish" not in json.dumps(body)


# --------------------------------------------------------------- real process
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(script: Path, port: int, secret: str | None, *extra: str) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if k != teacher_os_api.SECRET_ENV}
    if secret is not None:
        env[teacher_os_api.SECRET_ENV] = secret
    proc = subprocess.Popen([sys.executable, "-I", str(script), "--port", str(port), *extra], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            return proc
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return proc
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise AssertionError("server did not start")


def _get(port: int, path: str, **hdrs: str):
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=hdrs)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), json.loads(exc.read())


def _stop(proc: subprocess.Popen) -> str:
    proc.terminate()
    try:
        _, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    return err


def test_production_server_process_refuses_without_secret():
    port = _free_port()
    proc = _start(SERVER, port, None)
    assert proc.wait(timeout=20) == 2
    assert "refusing to start" in proc.stderr.read()


def test_failed_startup_prints_the_variable_name_never_the_secret_value():
    # CodeQL thread PRRT_kwDOTNo9I86z3DPP: the refusal line names the
    # environment VARIABLE; the canary below is a full-length secret value
    # that must never appear in stderr, in either failure mode. (At this
    # head the line interpolates SECRET_ENV, the name constant, not the
    # value; this test pins that property instead of the literal wording.)
    canary = "CANARY-FAILED-STARTUP-" + "x" * 24
    assert len(canary) >= 32 and teacher_os_api.SECRET_ENV == "TEACHER_OS_API_SESSION_SECRET"
    for env_secret, extra in ((canary, ["--allowed-origin", "https://evil.example"]), (None, ["--allowed-origin", "http://127.0.0.1:5173"])):
        port = _free_port()
        env = {k: v for k, v in os.environ.items() if k != teacher_os_api.SECRET_ENV}
        if env_secret is not None:
            env[teacher_os_api.SECRET_ENV] = env_secret
        proc = subprocess.Popen([sys.executable, "-I", str(SERVER), "--port", str(port), *extra], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert proc.wait(timeout=20) == 2
        err = proc.stderr.read()
        assert "refusing to start" in err and teacher_os_api.SECRET_ENV in err
        assert canary not in err


def test_production_server_process_is_loopback_authenticated_and_fails_closed_without_admission():
    port, secret = _free_port(), secrets.token_urlsafe(32)
    proc = _start(SERVER, port, secret, "--allowed-origin", "http://127.0.0.1:5173")
    try:
        status, hdrs, body = _get(port, UNITS)
        assert (status, body["reason_code"]) == (401, "unauthenticated") and hdrs["WWW-Authenticate"].startswith("Bearer")
        status, _, body = _get(port, UNITS, Authorization=f"Bearer {secret}", Host="evil.example")
        assert (status, body["reason_code"]) == (403, "host-not-allowed")
        status, hdrs, body = _get(port, UNITS, Authorization=f"Bearer {secret}")
        assert (status, body["status"], body["reason_code"]) == (503, "unavailable", "admission-required")
        assert hdrs["Cache-Control"] == "no-store" and hdrs["X-Content-Type-Options"] == "nosniff"
        assert "Access-Control-Allow-Origin" not in hdrs and "Python" not in hdrs.get("Server", "")
        status, _, body = _get(port, lessons_path(UNIT_COLOR), Authorization=f"Bearer {secret}")
        assert body["reason_code"] == "admission-required"
        # Bound to loopback only: the port is not reachable on any other local address.
        other = [a for a in {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)} if not a.startswith("127.")]
        for address in other:
            with pytest.raises(OSError):
                socket.create_connection((address, port), timeout=0.5).close()
    finally:
        log = _stop(proc)
    assert secret not in log and "Authorization" not in log  # the secret is never logged


def test_fixture_server_process_serves_the_synthetic_contract_over_http():
    port, secret = _free_port(), secrets.token_urlsafe(32)
    proc = _start(FIXTURE, port, secret)
    try:
        auth = {"Authorization": f"Bearer {secret}"}
        status, _, units = _get(port, UNITS, **auth)
        assert status == 200 and {u["title"] for u in units["units"]} >= {"Synthetic Unit — Color Planning (test data)"}
        status, _, lessons = _get(port, lessons_path(UNIT_COLOR), **auth)
        assert status == 200 and [x["day_lesson_number"] for x in lessons["lessons"]] == ["Day 1", "Day 2", "Day 3"]
        status, _, body = _get(port, lessons_path(UNIT_DRAFT), **auth)
        assert (status, body["reason_code"]) == (404, "unit-not-approved")
        assert _get(port, UNITS)[0] == 401
    finally:
        log = _stop(proc)
    assert secret not in log


def test_access_log_never_echoes_request_line_or_sensitive_text(api):
    # A crafted request line (query, path, fake canary) must never reach
    # stderr: only the response status and size are diagnostic.
    import io
    import sys

    built, _, _ = api
    handler_cls = teacher_os_api.make_handler(built)
    handler = object.__new__(handler_cls)
    handler.log_date_time_string = lambda: "01/Jan/2026 00:00:00"  # noqa: ARG005
    canary = "CANARY-FAKE-TOKEN-12345"
    capture = io.StringIO()
    old = sys.stderr
    sys.stderr = capture
    try:
        handler.log_message('"%s" %s %s', f"GET /api/teacher-os/units?token={canary} HTTP/1.1", "200", "42")
        handler.log_message("code %d, message %s", 404, canary)
    finally:
        sys.stderr = old
    log = capture.getvalue()
    assert canary not in log and "units" not in log and "GET" not in log
    assert "200" in log and "42" in log
