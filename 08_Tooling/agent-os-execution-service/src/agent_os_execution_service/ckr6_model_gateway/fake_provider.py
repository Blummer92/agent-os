"""Fixture ONLY: a local fake model provider run as a SEPARATE OS PROCESS.

No real model, credential, or paid inference is involved. It exists so tests
can observe, from the provider's side and independent of any gateway log, how
many authenticated calls actually arrived and how many unauthenticated
attempts were refused.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _serve() -> None:  # runs inside the provider process
    creds = json.loads(sys.stdin.readline())
    state = {"authenticated_calls": 0, "rejected_calls": 0, "events": []}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *args):  # silence
            pass

        def _auth(self, token: str) -> bool:
            return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if self.path == "/__stats" and self._auth(creds["admin"]):
                body = json.dumps(state).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            else:
                self.send_response(403); self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            prompt = json.loads(self.rfile.read(length) or b"{}").get("prompt", "")
            ok = self._auth(creds["provider"])
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            state["events"].append({"seq": len(state["events"]) + 1, "ts": time.time(), "path": self.path,
                                    "auth_ok": ok, "prompt_sha256": digest})
            if not ok:
                state["rejected_calls"] += 1
                self.send_response(401); self.end_headers(); return
            state["authenticated_calls"] += 1
            if "FAIL_BACKEND" in prompt:
                self.send_response(500); self.end_headers(); return
            self.send_response(200); self.end_headers()
            if self.path == "/v1/stream":
                for i, tok in enumerate(("alpha", "beta", "gamma")):
                    self.wfile.write(json.dumps({"chunk": tok}).encode() + b"\n"); self.wfile.flush()
                    if "FAIL_MIDSTREAM" in prompt and i == 0:
                        return  # connection closes without the done marker
                self.wfile.write(b'{"done":true}\n')
            else:
                self.wfile.write(json.dumps({"text": "provider-reply:" + digest[:8]}).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    print(json.dumps({"port": server.server_address[1]}), flush=True)
    server.serve_forever()


class FakeProviderProcess:
    host = "127.0.0.1"

    def __init__(self, proc: subprocess.Popen, port: int, credential: str, admin: str) -> None:
        self._proc, self.port, self.credential, self._admin = proc, port, credential, admin

    @classmethod
    def start(cls) -> "FakeProviderProcess":
        credential, admin = secrets.token_hex(16), secrets.token_hex(16)
        proc = subprocess.Popen([sys.executable, "-I", __file__, "--serve"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, close_fds=True)
        assert proc.stdin and proc.stdout
        proc.stdin.write(json.dumps({"provider": credential, "admin": admin}) + "\n"); proc.stdin.flush()
        port = json.loads(proc.stdout.readline())["port"]
        return cls(proc, port, credential, admin)

    def stats(self) -> dict:
        import http.client
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        conn.request("GET", "/__stats", headers={"Authorization": "Bearer " + self._admin})
        return json.loads(conn.getresponse().read())

    def stop(self) -> None:
        self._proc.kill(); self._proc.wait(timeout=10)
        for stream in (self._proc.stdin, self._proc.stdout):
            if stream:
                stream.close()


if __name__ == "__main__" and "--serve" in sys.argv:
    _serve()
