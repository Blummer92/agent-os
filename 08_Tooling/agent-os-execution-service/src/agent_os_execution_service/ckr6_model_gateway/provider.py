"""Provider client held ONLY by the trusted gateway process.

The credential lives in this object's private state, is never put in an
environment variable, argv, trace, or repr, and is never handed to a worker.
"""
from __future__ import annotations

import http.client
import json
from typing import Iterator


class ProviderError(RuntimeError):
    pass


class HttpProviderBackend:
    def __init__(self, host: str, port: int, credential: str, *, timeout: float = 30.0) -> None:
        if not credential:
            raise ValueError("provider credential is required")
        self._host, self._port, self._credential, self._timeout = host, port, credential, timeout

    def __repr__(self) -> str:  # never leak the credential through logs/tracebacks
        return f"HttpProviderBackend(host={self._host!r}, port={self._port!r}, credential=<redacted>)"

    def _post(self, path: str, prompt: str) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self._timeout)  # no proxy handling
        body = json.dumps({"prompt": prompt}).encode()
        conn.request("POST", path, body=body, headers={
            "Authorization": "Bearer " + self._credential, "Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            response.read()
            conn.close()
            raise ProviderError(f"provider-status-{response.status}")
        return response

    def complete(self, prompt: str) -> str:
        response = self._post("/v1/complete", prompt)
        try:
            return str(json.loads(response.read())["text"])
        finally:
            response.close()

    def stream(self, prompt: str) -> Iterator[str]:
        response = self._post("/v1/stream", prompt)
        try:
            done = False
            for raw in response:
                line = json.loads(raw)
                if line.get("done") is True:
                    done = True
                    break
                yield str(line["chunk"])
            if not done:
                raise ProviderError("stream-truncated")
        finally:
            response.close()
