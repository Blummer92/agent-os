"""Authenticated loopback API for the Teacher OS React app (#2801).

The React client reads two routes:

    GET /api/teacher-os/units
    GET /api/teacher-os/units/{unit_uuid}/lessons

This server is the only thing that answers them. It adds no Notion client,
credential handling, curriculum store or cache: every read is delegated to the
governed seam ``scripts.agent_os_notion_read_request.teacher_os`` in-process,
so the admission decision never crosses a process boundary where it could be
forged.

Trust boundary, checked in this order before any admission or executor work:

1. loopback only - the socket binds ``127.0.0.1`` and there is no host option;
2. ``GET`` only, no request body, no query string, no percent-encoding;
3. ``Host`` must name this loopback listener (DNS-rebinding defence);
4. a cross-site ``Origin``/``Sec-Fetch-Site`` is refused (CSRF defence);
5. ``Authorization: Bearer <session secret>``, compared in constant time.
   The secret is generated per launch by ``server/dev.mjs``, handed to this
   process and to the Vite proxy through the process environment only, and
   never printed, logged or sent to the browser;
6. exact route + strict UUID, then a small read budget (rate limit).

Only then is the admission provider consulted. ``teacher_os`` refuses dispatch
without a scope-bound ``NotionReadAdmission`` before it calls the executor
factory, and the factory itself is lazy, so a refused request constructs no
credential-bearing adapter.

Authentication is not authorization. The session secret proves a request came
through this operator's own local launcher; it is not a multi-user teacher
identity and is not a production auth system. Authorization to dispatch a
Notion read comes only from the canonical admission path. No admission class
for Teacher OS discovery exists today (see ``canonical_teacher_os_admission``),
so the production server answers ``admission-required`` and live reads stay
closed until the owner admits one.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
for _entry in (REPO_ROOT / "08_Tooling" / "workflow-scheduler" / "src", REPO_ROOT / "src", REPO_ROOT):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from scripts.agent_os_notion_read_request.catalog import load_catalog  # noqa: E402
from scripts.agent_os_notion_read_request.models import (  # noqa: E402
    SCHEMA_VERSION,
    NotionReadAdmission,
    NotionReadCatalog,
)
from scripts.agent_os_notion_read_request.teacher_os import (  # noqa: E402
    RESULT_KIND,
    TeacherOsReadError,
    read_unit_lessons,
    read_units,
)

LOOPBACK = "127.0.0.1"
SECRET_ENV = "TEACHER_OS_API_SESSION_SECRET"
MIN_SECRET_LENGTH = 32
UNITS_PATH = "/api/teacher-os/units"
_LESSONS_RE = re.compile(r"^/api/teacher-os/units/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/lessons$")
_LOOPBACK_ORIGIN_RE = re.compile(r"http://(127\.0\.0\.1|localhost):\d{2,5}")
MAX_PATH_LENGTH = 128
READS_PER_WINDOW, WINDOW_SECONDS = 30, 60.0

#: Closed reason vocabulary -> (HTTP status, envelope status). Anything not
#: listed is reported as ``read-failed``; provider text is never published.
_REASONS: dict[str, tuple[int, str]] = {
    "method-not-allowed": (405, "error"),
    "invalid-request": (400, "error"),
    "not-found": (404, "error"),
    "host-not-allowed": (403, "error"),
    "origin-not-allowed": (403, "error"),
    "unauthenticated": (401, "error"),
    "rate-limited": (429, "error"),
    "admission-required": (503, "unavailable"),
    "not-configured": (503, "unavailable"),
    "source-unverified": (503, "unavailable"),
    "unit-not-approved": (404, "error"),
    "read-failed": (502, "error"),
}

AdmissionProvider = Callable[[], "NotionReadAdmission | None"]
ExecutorFactoryProvider = Callable[[], Callable[[], Callable[[Mapping[str, object]], object]]]


def canonical_teacher_os_admission() -> NotionReadAdmission | None:
    """Return the canonical admission for Teacher OS discovery, if one exists.

    The canonical admission path (``admission.admit_notion_read_request``)
    admits only GitHub issue-comment transport envelopes for catalog request
    records whose ``request_class`` is one of ``models.REQUEST_CLASSES``. None
    of those classes yields the shape ``teacher_os`` requires - admitted,
    ``secret_dispatch_authorized``, no ``canonical_unit_key``, and required
    sources covering both ``canonical-unit`` and ``daily-generation-packet``.
    Manufacturing that record here would forge an owner decision, so this
    returns ``None`` and every live read fails closed with
    ``admission-required``. Owner decision needed: admit a Teacher OS
    discovery request class with exactly that shape through the canonical
    path; then this function obtains it from there.
    """
    return None


def live_executor_factory() -> Callable[[], Callable[[Mapping[str, object]], object]]:
    """Return the existing lazy #936 read-only factory (reads no credential until called)."""
    from scripts.agent_os_notion_read_request.live_executor import build_live_notion_executor_factory

    return build_live_notion_executor_factory()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ReadBudget:
    """Sliding-window read budget shared by all requests of one server."""

    limit: int = READS_PER_WINDOW
    window: float = WINDOW_SECONDS
    clock: Callable[[], float] = time.monotonic
    _events: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def take(self) -> bool:
        now = self.clock()
        with self._lock:
            while self._events and now - self._events[0] >= self.window:
                self._events.popleft()
            if len(self._events) >= self.limit:
                return False
            self._events.append(now)
            return True


@dataclass
class TeacherOsApi:
    """Transport-free request policy, so every rule is testable without sockets."""

    session_secret: str
    port: int
    admission_provider: AdmissionProvider = canonical_teacher_os_admission
    factory_provider: ExecutorFactoryProvider = live_executor_factory
    catalog_loader: Callable[[], NotionReadCatalog] = lambda: load_catalog(sources_only=True)
    clock: Callable[[], str] = _utc_now
    budget: ReadBudget = field(default_factory=ReadBudget)
    allowed_origins: frozenset[str] = frozenset()
    _read_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if not isinstance(self.session_secret, str) or len(self.session_secret) < MIN_SECRET_LENGTH:
            raise ValueError("session secret is missing or too short")
        self._allowed_hosts = {f"{LOOPBACK}:{self.port}", f"localhost:{self.port}"}
        for origin in self.allowed_origins:
            if not _LOOPBACK_ORIGIN_RE.fullmatch(origin):
                raise ValueError("allowed origins must be loopback http origins")

    # -- policy ---------------------------------------------------------
    def handle(self, method: str, raw_path: str, headers: Mapping[str, str], body_length: int) -> tuple[int, dict[str, Any]]:
        lower = {k.lower(): v for k, v in headers.items()}
        if method != "GET":
            return self._fail("method-not-allowed")
        if body_length or "transfer-encoding" in lower:
            return self._fail("invalid-request")
        if lower.get("host") not in self._allowed_hosts:
            return self._fail("host-not-allowed")
        site = lower.get("sec-fetch-site")
        origin = lower.get("origin")
        if site not in (None, "same-origin", "none") or (origin is not None and origin not in self.allowed_origins):
            return self._fail("origin-not-allowed")
        if not self._authenticated(lower.get("authorization")):
            return self._fail("unauthenticated")
        if len(raw_path) > MAX_PATH_LENGTH or "?" in raw_path or "%" in raw_path or "#" in raw_path:
            return self._fail("invalid-request")
        if raw_path == UNITS_PATH:
            return self._read(lambda catalog, admission, factory, generated_at: read_units(catalog, admission, factory, generated_at=generated_at))
        match = _LESSONS_RE.fullmatch(raw_path)
        if match is None:
            if raw_path.startswith(UNITS_PATH + "/"):
                return self._fail("invalid-request")
            return self._fail("not-found")
        unit_id = match.group(1)
        return self._read(lambda catalog, admission, factory, generated_at: read_unit_lessons(catalog, admission, factory, unit_id, generated_at=generated_at))

    def _authenticated(self, authorization: str | None) -> bool:
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return False
        presented = authorization[len("Bearer "):].encode("utf-8")
        return hmac.compare_digest(presented, self.session_secret.encode("utf-8"))

    def _read(self, call: Callable[..., dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        if not self.budget.take():
            return self._fail("rate-limited")
        admission = self.admission_provider()
        provider = self.factory_provider

        def lazy_factory() -> Callable[[Mapping[str, object]], object]:
            # Only reached after teacher_os has accepted the admission.
            return provider()()

        with self._read_lock:  # one Notion read at a time
            try:
                payload = call(self.catalog_loader(), admission, lazy_factory, self.clock())
            except TeacherOsReadError as exc:
                return self._fail(exc.reason_code)
            except Exception:  # provider/validation text is never published
                return self._fail("read-failed")
        return 200, payload

    @staticmethod
    def _fail(reason: str) -> tuple[int, dict[str, Any]]:
        if reason not in _REASONS:
            reason = "read-failed"
        status, kind = _REASONS[reason]
        return status, {"schema_version": SCHEMA_VERSION, "result_kind": RESULT_KIND, "status": kind, "reason_code": reason}


_SECURITY_HEADERS = (
    ("Content-Type", "application/json; charset=utf-8"),
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)


def make_handler(api: TeacherOsApi) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TeacherOsApi"
        sys_version = ""

        def _respond(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 1
            status, body = api.handle(self.command, self.path, dict(self.headers.items()), length)
            data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                for name, value in _SECURITY_HEADERS:
                    self.send_header(name, value)
                if status == 401:
                    self.send_header("WWW-Authenticate", 'Bearer realm="teacher-os"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # The browser aborted a superseded request; there is no one to answer.
                self.close_connection = True

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _respond
        # BaseHTTPRequestHandler answers methods without a do_* with its own HTML 501; route them here too.
        do_TRACE = do_CONNECT = _respond

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Never log the request line: it is user-controlled text (method,
            # path, query) and must not reach stderr, where a crafted path
            # could carry sensitive-looking material. Only the response
            # status and size are diagnostic, and only when the arguments
            # match the log_request shape (requestline, code, size).
            # Anything else is logged as a bare error marker, with no args.
            if len(args) >= 3 and isinstance(args[1], (int, str)) and isinstance(args[2], (int, str)):
                sys.stderr.write(
                    "teacher-os-api %s %s %s\n" % (self.log_date_time_string(), args[1], args[2])
                )
            else:
                sys.stderr.write("teacher-os-api %s error\n" % self.log_date_time_string())

    return Handler


def serve(api: TeacherOsApi) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((LOOPBACK, api.port), make_handler(api))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Teacher OS loopback API (binds 127.0.0.1 only).")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--allowed-origin", action="append", default=[], help="exact loopback origin of the Vite app (repeatable)")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024-65535")
    secret = os.environ.pop(SECRET_ENV, "")
    try:
        api = TeacherOsApi(session_secret=secret, port=args.port, allowed_origins=frozenset(args.allowed_origin))
    except ValueError:
        # Static text only: this names the environment VARIABLE, never the
        # secret value. The value lives only in `secret` above and is passed
        # to TeacherOsApi, where it is used solely by hmac.compare_digest;
        # it is never printed, logged, returned or placed in argv. Keeping
        # the message a literal (no interpolation of SECRET_ENV or `secret`)
        # removes the dataflow a clear-text-logging check flagged here
        # (CodeQL thread PRRT_kwDOTNo9I86z3DPP) without suppressing logging.
        sys.stderr.write("teacher-os-api: refusing to start without TEACHER_OS_API_SESSION_SECRET and loopback origins (launch with `npm run dev:app`)\n")
        return 2
    server = serve(api)
    sys.stderr.write(f"teacher-os-api listening on http://{LOOPBACK}:{args.port} (loopback only)\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
