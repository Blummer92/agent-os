"""Worker-side RPC client. STDLIB ONLY (it is copied next to an untrusted worker).

It can send a prompt and receive an answer. It holds no admission flag, receipt,
backend handle, credential, or network address: every decision is the gateway's.
"""
from __future__ import annotations

import json
import socket
from typing import Any, Iterator


class GatewayClient:
    def __init__(self, fd: int) -> None:
        self._sock = socket.socket(fileno=fd)
        self._file = self._sock.makefile("rwb")

    def _send(self, frame: dict[str, Any]) -> None:
        self._file.write(json.dumps(frame).encode() + b"\n")
        self._file.flush()

    def _recv(self) -> dict[str, Any]:
        line = self._file.readline()
        if not line:
            return {"admitted": False, "reason": "gateway-connection-closed"}
        return json.loads(line)

    def raw(self, frame: dict[str, Any]) -> dict[str, Any]:
        self._send(frame)
        return self._recv()

    def open(self) -> dict[str, Any]:
        return self.raw({"method": "open"})

    def turn(self, session: str, kind: str, prompt: str, key: str) -> dict[str, Any]:
        return self.raw({"method": "turn", "session": session, "kind": kind, "prompt": prompt, "key": key})

    def child(self, session: str) -> dict[str, Any]:
        return self.raw({"method": "child", "session": session})

    def close_session(self, session: str) -> dict[str, Any]:
        return self.raw({"method": "close", "session": session})

    def stream(self, session: str, prompt: str, key: str) -> Iterator[dict[str, Any]]:
        self._send({"method": "stream", "session": session, "prompt": prompt, "key": key})
        while True:
            frame = self._recv()
            yield frame
            if frame.get("done") or frame.get("admitted") is False:
                return
