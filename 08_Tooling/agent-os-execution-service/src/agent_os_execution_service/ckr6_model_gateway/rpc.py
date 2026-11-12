"""Gateway-side worker RPC. A frame carries a prompt, never a decision.

The task binding (repository, issue, task, attempt, hints) is fixed by the
trusted supervisor when the connection is created, so a worker cannot change
the identity or materiality inputs it is admitted under. Frames with any field
outside the per-method allow-list are refused.
"""
from __future__ import annotations

import json
import socket
import threading
from typing import Any

from .contract import InvocationRequest, StopBoundary
from .gateway import ModelGateway

MAX_FRAME_BYTES = 1024 * 1024
_ALLOWED = {
    "open": frozenset({"method"}),
    "turn": frozenset({"method", "session", "kind", "prompt", "key"}),
    "stream": frozenset({"method", "session", "prompt", "key"}),
    "child": frozenset({"method", "session"}),
    "close": frozenset({"method", "session"}),
}


class GatewayRpcServer:
    def __init__(self, gateway: ModelGateway, binding: InvocationRequest, *, max_opens: int = 2) -> None:
        self._gateway = gateway
        self._binding = binding
        self._max_opens = max_opens
        self._opens = 0
        self.cancel = threading.Event()  # set by the TRUSTED side to cancel in-flight admission

    @staticmethod
    def _bad(reason: str = "bad-frame") -> dict[str, Any]:
        return {"admitted": False, "reason": reason}

    def serve(self, sock: socket.socket) -> None:
        owned: set[str] = set()
        reader = sock.makefile("rb")
        writer = sock.makefile("wb")

        def send(frame: dict[str, Any]) -> None:
            writer.write(json.dumps(frame).encode() + b"\n")
            writer.flush()

        try:
            while True:
                line = reader.readline(MAX_FRAME_BYTES + 1)
                if not line:
                    return
                try:
                    if len(line) > MAX_FRAME_BYTES:
                        raise ValueError
                    frame = json.loads(line)
                    method = frame["method"]
                    if (type(frame) is not dict or method not in _ALLOWED
                            or set(frame) - _ALLOWED[method]):
                        raise ValueError
                except (ValueError, KeyError, TypeError):
                    send(self._bad())
                    continue
                self._handle(frame, method, owned, send)
        except (OSError, ValueError):
            return
        finally:
            for token in owned:
                self._gateway.session_close(token)

    def _owned(self, frame: dict[str, Any], owned: set[str]) -> str | None:
        token = frame.get("session")
        return token if isinstance(token, str) and token in owned else None

    def _handle(self, frame: dict[str, Any], method: str, owned: set[str], send) -> None:
        gw = self._gateway
        if method == "open":
            if self._opens >= self._max_opens:
                send(self._bad("open-limit-reached")); return
            self._opens += 1
            outcome = gw.open_session(self._binding.with_(invocation_id=f"{self._binding.invocation_id}:open:{self._opens}"),
                                      cancel=self.cancel)
            if outcome.session:
                owned.add(outcome.session)
            send({"admitted": outcome.admitted, "reason": outcome.reason, "session": outcome.session})
            return
        token = self._owned(frame, owned)
        if token is None:
            send(self._bad("unknown-session")); return
        if method == "turn":
            if type(frame.get("prompt")) is not str or type(frame.get("key")) is not str or type(frame.get("kind")) is not str:
                send(self._bad()); return
            out = gw.session_turn(token, frame["kind"], frame["prompt"], idempotency_key=frame["key"], cancel=self.cancel)
            send({"admitted": out.admitted, "reason": out.reason, "output": out.output})
        elif method == "stream":
            if type(frame.get("prompt")) is not str or type(frame.get("key")) is not str:
                send(self._bad()); return
            try:
                for chunk in gw.session_stream(token, frame["prompt"], idempotency_key=frame["key"], cancel=self.cancel):
                    send({"admitted": True, "chunk": chunk})
                send({"admitted": True, "done": True})
            except StopBoundary as exc:
                send(self._bad(exc.reason))
        elif method == "child":
            out = gw.session_child(token)
            if out.session:
                owned.add(out.session)
            send({"admitted": out.admitted, "reason": out.reason, "session": out.session})
        elif method == "close":
            gw.session_close(token)
            owned.discard(token)
            send({"admitted": False, "reason": "closed"})
