"""The single model-capability chokepoint.

Trust model (what is ENFORCED vs only DOCUMENTED is in docs/CKR6_MODEL_GATEWAY.md):

* ``ModelGateway`` runs in the trusted service process. It is the only object
  that holds the provider backend (and, in production composition, the provider
  credential). Workers are separate OS processes started by
  ``supervisor.spawn_isolated_worker`` with no credential, no backend handle,
  no network and a different uid; they reach this object only through
  ``rpc.GatewayRpcServer`` frames that carry a prompt and nothing else.
* Every provider call needs a one-time, expiring ``AdmissionReceipt`` minted
  here after independent CKR6 verification. Receipts never leave this process.
* Denials are terminal: no retry, no fallback, backend_calls stays 0.

In-process Python privacy (``_backend``) is NOT a security boundary; the process
and credential split is. Do not hand a ``ModelGateway`` to untrusted code.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator, Mapping, Protocol

from .admission import Ckr6Admitter, GitHubTransport
from .contract import (
    MAX_PROMPT_BYTES, AdmissionProof, AdmissionReceipt, GatewayConfig, InvocationOutcome, InvocationRequest,
    Stats, StopBoundary, Trace, sha256_text,
)

SESSION_KINDS = frozenset({"normal", "tool-continuation", "subagent"})


class ProviderBackend(Protocol):
    def complete(self, prompt: str) -> str: ...
    def stream(self, prompt: str) -> Iterator[str]: ...


@dataclass
class _Session:
    token: str
    request: InvocationRequest
    proof: AdmissionProof
    expires_at: datetime
    turns_left: int
    children_left: int
    depth: int
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    closed: bool = False
    # key -> (prompt sha, outcome); outcome is None while the turn is reserved/in flight.
    keys: dict[str, tuple[str, InvocationOutcome | None]] = field(default_factory=dict)


class ModelGateway:
    def __init__(self, transport: GitHubTransport, backend: ProviderBackend, *, config: GatewayConfig,
                 clock: Callable[[], datetime], sleep: Callable[[float], None],
                 verify_failed_attempt: Callable[[InvocationRequest], bool] | None = None,
                 verify_canonical_unavailability: Callable[[InvocationRequest, Mapping[str, Any]], bool] | None = None,
                 verify_binding_current: Callable[[InvocationRequest], bool] | None = None) -> None:
        self._config = config
        self._clock = clock
        self._backend = backend
        self._admitter = Ckr6Admitter(transport, config, clock, sleep,
                                      verify_failed_attempt=verify_failed_attempt,
                                      verify_canonical_unavailability=verify_canonical_unavailability)
        self._verify_binding_current = verify_binding_current
        self._lock = threading.RLock()
        self._receipts: dict[str, tuple[AdmissionReceipt, InvocationRequest]] = {}
        self._outcomes: dict[str, tuple[str, InvocationOutcome]] = {}
        self._inflight: set[str] = set()
        self._sessions: dict[str, _Session] = {}
        self.stats = Stats()
        self.trace_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------- small utils
    def _trace(self) -> Trace:
        return Trace(self._clock)

    def _finish(self, trace: Trace, outcome_kwargs: dict[str, Any]) -> InvocationOutcome:
        with self._lock:
            self.trace_log.extend(trace.events)
        return InvocationOutcome(trace=tuple(trace.events), **outcome_kwargs)

    def _deny(self, trace: Trace, reason: str, **extra: Any) -> InvocationOutcome:
        with self._lock:
            self.stats.denied += 1
        trace.record("boundary-stopped", reason=reason)
        return self._finish(trace, dict(admitted=False, reason=reason, output=None, **extra))

    def _still_current(self, request: InvocationRequest) -> None:
        """Re-check the live binding immediately before every dispatch (stale head/attempt)."""
        try:
            if request.operation == "failed-repair" and (
                    self._admitter.verify_failed_attempt is None
                    or self._admitter.verify_failed_attempt(request) is not True):
                raise StopBoundary("stale-failed-attempt")
            if self._verify_binding_current is not None and self._verify_binding_current(request) is not True:
                raise StopBoundary("stale-binding")
        except StopBoundary:
            raise
        except Exception:  # noqa: BLE001 - a crashing hook is a STOP, never an admission or a stuck key
            raise StopBoundary("binding-check-failed") from None

    # ---------------------------------------------------------------- receipts
    def _issue_receipt(self, trace: Trace, request: InvocationRequest, proof: AdmissionProof, *,
                       kind: str, binding_sha256: str, session_id: str | None,
                       scope: str = "ckr6-model-entry") -> str:
        now = self._clock()
        expiry = min(now + timedelta(seconds=self._config.receipt_ttl_seconds),
                     datetime.fromisoformat(proof.expires_at))
        receipt = AdmissionReceipt(
            receipt_id=secrets.token_urlsafe(24), scope=scope, identity_hash=proof.identity_hash,
            invocation_id=request.invocation_id, kind=kind, prompt_sha256=binding_sha256,
            result_sha256=proof.result_sha256, request_comment_id=proof.request_comment_id,
            attempt_id=proof.attempt_id, session_id=session_id, issued_at=now, expires_at=expiry)
        with self._lock:
            self._receipts[receipt.receipt_id] = (receipt, request)
            self.stats.receipts_issued += 1
        trace.record("receipt-issued", receipt_id=receipt.receipt_id[:8], scope=scope, kind=kind,
                     expires_at=expiry.isoformat())
        return receipt.receipt_id

    def _consume(self, trace: Trace, receipt_id: str, binding_sha256: str, *, scope: str,
                 cancel: Any = None) -> AdmissionReceipt:
        with self._lock:
            held = self._receipts.pop(receipt_id, None) if isinstance(receipt_id, str) else None
            if held is None:
                raise StopBoundary("receipt-unknown-or-used")
            self.stats.receipts_consumed += 1  # burned even if a later check refuses it
        receipt, request = held
        trace.record("receipt-consumed", receipt_id=receipt_id[:8])
        if receipt.scope != scope:
            raise StopBoundary("receipt-scope-mismatch")
        if self._clock() >= receipt.expires_at:
            raise StopBoundary("receipt-expired")
        if receipt.prompt_sha256 != binding_sha256:
            raise StopBoundary("receipt-binding-mismatch")
        if cancel is not None and cancel.is_set():
            raise StopBoundary("cancelled-before-dispatch")
        self._still_current(request)
        return receipt

    def dispatch(self, receipt_id: str, prompt: str) -> str:
        """Trusted-side single-use dispatch. Raises ``StopBoundary`` on any invalid receipt."""
        trace = self._trace()
        try:
            self._consume(trace, receipt_id, sha256_text(prompt), scope="ckr6-model-entry")
        except StopBoundary:
            with self._lock:
                self.stats.denied += 1
            trace.record("boundary-stopped", reason="dispatch-refused")
            with self._lock:
                self.trace_log.extend(trace.events)
            raise
        return self._call_backend(trace, prompt)

    def _call_backend(self, trace: Trace, prompt: str) -> str:
        with self._lock:
            self.stats.backend_calls += 1
        trace.record("model-call-started")
        output = self._backend.complete(prompt)
        trace.record("model-call-completed")
        return output

    @staticmethod
    def _exact(request: object) -> None:
        """Subclasses could return different values on later reads (TOCTOU on the prompt)."""
        if type(request) is not InvocationRequest:
            raise StopBoundary("invalid-request")

    # ----------------------------------------------------------- idempotency
    def _begin(self, key: str, request_hash: str) -> InvocationOutcome | None:
        """Return a cached/denial outcome, or None after registering the key in flight."""
        with self._lock:
            prior = self._outcomes.get(key)
            if prior is not None:
                if prior[0] != request_hash:
                    trace = self._trace()
                    return self._deny(trace, "invocation-id-reuse-mismatch")
                cached = prior[1]
                return InvocationOutcome(admitted=cached.admitted, reason=cached.reason, output=cached.output,
                                         trace=cached.trace, admission=cached.admission, replayed=True,
                                         session=cached.session, scope=cached.scope)
            if key in self._inflight:
                return self._deny(self._trace(), "invocation-in-flight")
            self._inflight.add(key)
        return None

    def _remember(self, key: str, request_hash: str, outcome: InvocationOutcome) -> None:
        with self._lock:
            self._outcomes[key] = (request_hash, outcome)
            self._inflight.discard(key)

    # ---------------------------------------------------------------- invoke
    def invoke(self, request: InvocationRequest, *, cancel: Any = None) -> InvocationOutcome:
        """One full CKR6 admission -> one receipt -> one provider call. Every kind
        (normal/retry/resume/tool-continuation/subagent) gets a FRESH admission here."""
        try:
            self._exact(request)
            request.validate()
            request_hash = request.request_hash()
        except (StopBoundary, TypeError, ValueError) as exc:
            return self._deny(self._trace(), exc.reason if isinstance(exc, StopBoundary) else "invalid-request")
        early = self._begin(request.invocation_id, request_hash)
        if early is not None:
            return early
        trace = self._trace()
        try:
            proof, _ = self._admitter.admit(request, trace, cancel)
            receipt_id = self._issue_receipt(trace, request, proof, kind=request.kind,
                                             binding_sha256=sha256_text(request.prompt), session_id=None)
            self._consume(trace, receipt_id, sha256_text(request.prompt), scope="ckr6-model-entry", cancel=cancel)
        except StopBoundary as exc:
            outcome = self._deny(trace, exc.reason)
            self._remember(request.invocation_id, request_hash, outcome)
            return outcome
        outcome = self._run_admitted(trace, request.prompt, proof)
        self._remember(request.invocation_id, request_hash, outcome)
        return outcome

    def _run_admitted(self, trace: Trace, prompt: str, proof: AdmissionProof, session: str | None = None) -> InvocationOutcome:
        try:
            output = self._call_backend(trace, prompt)
        except Exception as exc:  # noqa: BLE001 - failure AFTER admission is not a gate rejection; never retried
            trace.record("model-call-failed", exception_type=type(exc).__name__)
            return self._finish(trace, dict(admitted=True, reason="admitted-model-failed:" + type(exc).__name__,
                                            output=None, admission=proof, session=session))
        return self._finish(trace, dict(admitted=True, reason="admitted", output=output, admission=proof,
                                        session=session))

    def invoke_stream(self, request: InvocationRequest, *, cancel: Any = None) -> Iterator[str]:
        """Full admission, then stream. Admission completes BEFORE the first provider byte; a
        denial raises ``StopBoundary`` at the first ``next()``. No retry after a partial stream."""
        def generate() -> Iterator[str]:
            try:
                self._exact(request)
                request.validate()
                request_hash = request.request_hash()
            except (StopBoundary, TypeError, ValueError) as exc:
                raise StopBoundary(exc.reason if isinstance(exc, StopBoundary) else "invalid-request") from None
            if self._begin(request.invocation_id, request_hash) is not None:
                # A stream cannot be replayed from cache, so ANY reuse of an id is refused.
                raise StopBoundary("stream-invocation-id-already-used")
            outcome = InvocationOutcome(admitted=False, reason="stream-not-started", output=None, trace=())
            try:
                trace = self._trace()
                prompt = request.prompt
                proof, _ = self._admitter.admit(request, trace, cancel)
                rid = self._issue_receipt(trace, request, proof, kind="stream",
                                          binding_sha256=sha256_text(prompt), session_id=None)
                self._consume(trace, rid, sha256_text(prompt), scope="ckr6-model-entry", cancel=cancel)
                outcome = InvocationOutcome(admitted=True, reason="stream-consumed", output=None, trace=())
                yield from self._stream_backend(trace, prompt, cancel, None)
            except StopBoundary as exc:
                if not outcome.admitted:
                    outcome = InvocationOutcome(admitted=False, reason=exc.reason, output=None, trace=())
                raise
            finally:
                self._remember(request.invocation_id, request_hash, outcome)
        return generate()

    def _stream_backend(self, trace: Trace, prompt: str, cancel: Any, session: _Session | None) -> Iterator[str]:
        with self._lock:
            self.stats.backend_calls += 1
        trace.record("model-stream-started")
        delivered = 0
        stream = self._backend.stream(prompt)
        try:
            for chunk in stream:
                if cancel is not None and cancel.is_set():
                    raise StopBoundary("cancelled-during-stream")
                delivered += 1
                yield chunk
        except StopBoundary:
            trace.record("model-stream-cancelled", chunks_delivered=delivered)
            raise
        except Exception as exc:  # noqa: BLE001
            trace.record("model-stream-failed-after-partial", exception_type=type(exc).__name__,
                         chunks_delivered=delivered)
            if session is not None:
                self._close(session)
            raise StopBoundary("stream-aborted-no-retry") from None
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()
            with self._lock:
                self.trace_log.extend(trace.events)
        trace.record("model-stream-completed", chunks_delivered=delivered)

    # --------------------------------------------------------------- sessions
    def open_session(self, request: InvocationRequest, *, cancel: Any = None) -> InvocationOutcome:
        """One CKR6 admission amortised over a bounded, expiring session of receipted turns."""
        try:
            self._exact(request)
            request.validate()
            request_hash = request.identity_hash()
        except (StopBoundary, TypeError, ValueError) as exc:
            return self._deny(self._trace(), exc.reason if isinstance(exc, StopBoundary) else "invalid-request")
        early = self._begin(request.invocation_id, request_hash)
        if early is not None:
            # A session token is a capability: it is never replayed to a second caller.
            return early if not early.admitted else self._deny(self._trace(), "session-open-id-already-used")
        trace = self._trace()
        try:
            proof, _ = self._admitter.admit(request, trace, cancel)
        except StopBoundary as exc:
            outcome = self._deny(trace, exc.reason)
            self._remember(request.invocation_id, request_hash, outcome)
            return outcome
        session = _Session(
            token=secrets.token_urlsafe(24), request=request, proof=proof,
            expires_at=datetime.fromisoformat(proof.expires_at),
            turns_left=self._config.session_max_turns, children_left=self._config.session_max_children, depth=0)
        with self._lock:
            self._sessions[session.token] = session
        trace.record("session-opened", turns=session.turns_left, expires_at=proof.expires_at)
        outcome = self._finish(trace, dict(admitted=True, reason="session-admitted", output=None,
                                           admission=proof, session=session.token))
        self._remember(request.invocation_id, request_hash, outcome)
        return outcome

    def _close(self, session: _Session) -> None:
        with self._lock:
            stack = [session]
            while stack:
                current = stack.pop()
                current.closed = True
                self._sessions.pop(current.token, None)
                stack.extend(self._sessions[c] for c in current.children if c in self._sessions)

    def session_close(self, token: str) -> None:
        with self._lock:
            session = self._sessions.get(token)
        if session is not None:
            self._close(session)

    def _reserve_turn(self, token: Any, kind: str, prompt: Any, key: Any
                      ) -> tuple[_Session, str, InvocationOutcome | None]:
        """ATOMIC under one lock: validate, idempotency (incl. in-flight), spend one turn, reserve the key.
        Separate check-then-decrement steps let concurrent callers overspend the budget."""
        if (type(key) is not str or not key.strip() or type(prompt) is not str
                or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES):
            raise StopBoundary("invalid-turn")
        sha = sha256_text(prompt)
        with self._lock:
            session = self._sessions.get(token) if isinstance(token, str) else None
            if session is None or session.closed:
                raise StopBoundary("unknown-session")
            if kind in ("retry", "resume"):
                raise StopBoundary(kind + "-requires-new-admission")
            if kind == "stream":
                raise StopBoundary("use-session-stream")
            if kind not in SESSION_KINDS:
                raise StopBoundary("unsupported-kind")
            if kind == "subagent" and session.depth == 0:
                raise StopBoundary("subagent-requires-child-session")
            if kind != "subagent" and session.depth > 0:
                raise StopBoundary("child-session-turns-must-be-subagent")
            if self._clock() >= session.expires_at:
                self._close(session)
                raise StopBoundary("session-expired-needs-new-admission")
            prior = session.keys.get(key)
            if prior is not None:
                if prior[0] != sha:
                    raise StopBoundary("idempotency-key-reuse-mismatch")
                if prior[1] is None:
                    raise StopBoundary("idempotency-key-in-flight")
                return session, sha, prior[1]
            if session.turns_left <= 0:
                raise StopBoundary("session-turn-budget-exhausted")
            session.turns_left -= 1  # spent before dispatch: a failed call is never free
            session.keys[key] = (sha, None)
        return session, sha, None

    def session_turn(self, token: str, kind: str, prompt: str, *, idempotency_key: str,
                     cancel: Any = None) -> InvocationOutcome:
        trace = self._trace()
        try:
            session, prompt_sha, cached = self._reserve_turn(token, kind, prompt, idempotency_key)
        except StopBoundary as exc:
            return self._deny(trace, exc.reason)
        if cached is not None:
            return InvocationOutcome(admitted=cached.admitted, reason=cached.reason, output=cached.output,
                                     trace=cached.trace, admission=cached.admission, replayed=True,
                                     session=cached.session)
        try:
            self._still_current(session.request)
            rid = self._issue_receipt(trace, session.request, session.proof, kind=kind,
                                      binding_sha256=prompt_sha, session_id=session.token)
            self._consume(trace, rid, prompt_sha, scope="ckr6-model-entry", cancel=cancel)
        except StopBoundary as exc:
            outcome = self._deny(trace, exc.reason, session=session.token)
        else:
            outcome = self._run_admitted(trace, prompt, session.proof, session.token)
        with self._lock:
            session.keys[idempotency_key] = (prompt_sha, outcome)
        return outcome

    def session_stream(self, token: str, prompt: str, *, idempotency_key: str, cancel: Any = None) -> Iterator[str]:
        """Admission and receipt consumption happen at the first ``next()``, before any provider byte."""
        def generate() -> Iterator[str]:
            trace = self._trace()
            kind = "subagent" if self._depth(token) > 0 else "normal"
            session, prompt_sha, cached = self._reserve_turn(token, kind, prompt, idempotency_key)
            if cached is not None:
                raise StopBoundary("stream-idempotency-key-already-used")
            outcome = InvocationOutcome(admitted=False, reason="stream-not-started", output=None, trace=())
            try:
                self._still_current(session.request)
                rid = self._issue_receipt(trace, session.request, session.proof, kind="stream",
                                          binding_sha256=prompt_sha, session_id=session.token)
                self._consume(trace, rid, prompt_sha, scope="ckr6-model-entry", cancel=cancel)
                outcome = InvocationOutcome(admitted=True, reason="stream-consumed", output=None, trace=())
                yield from self._stream_backend(trace, prompt, cancel, session)
            except StopBoundary as exc:
                if not outcome.admitted:
                    outcome = InvocationOutcome(admitted=False, reason=exc.reason, output=None, trace=())
                raise
            finally:
                with self._lock:
                    session.keys[idempotency_key] = (prompt_sha, outcome)
        return generate()

    def _depth(self, token: str) -> int:
        with self._lock:
            session = self._sessions.get(token)
        return session.depth if session is not None else 0

    def session_child(self, token: str) -> InvocationOutcome:
        """Derive a bounded subagent session. It inherits the parent's admission, expiry and
        request binding, takes its turn budget from the parent, and can never outlive it."""
        trace = self._trace()
        with self._lock:
            parent = self._sessions.get(token) if isinstance(token, str) else None
            if parent is None or parent.closed:
                return self._deny(trace, "unknown-session")
            if self._clock() >= parent.expires_at:
                self._close(parent)
                return self._deny(trace, "session-expired-needs-new-admission")
            if parent.depth + 1 > self._config.session_max_depth or parent.children_left <= 0:
                return self._deny(trace, "subagent-limit-reached")
            share = parent.turns_left // 2
            if share < 1:
                return self._deny(trace, "session-turn-budget-exhausted")
            parent.turns_left -= share
            parent.children_left -= 1
            child = _Session(token=secrets.token_urlsafe(24), request=parent.request, proof=parent.proof,
                             expires_at=parent.expires_at, turns_left=share,
                             children_left=parent.children_left if parent.depth + 1 < self._config.session_max_depth else 0,
                             depth=parent.depth + 1, parent=parent.token)
            parent.children.append(child.token)
            self._sessions[child.token] = child
        trace.record("child-session-opened", depth=child.depth, turns=share)
        return self._finish(trace, dict(admitted=True, reason="child-session-admitted", output=None,
                                        admission=parent.proof, session=child.token))

    # ------------------------------------------------------ launch (Option A)
    def gate_launch(self, request: InvocationRequest, *, binding_sha256: str,
                    launcher: Callable[[], Any], cancel: Any = None) -> InvocationOutcome:
        """Admit a model-capable PROCESS LAUNCH. Scope is ``session-start-only``: nothing here
        mediates the launched process's own later provider requests."""
        try:
            self._exact(request)
            request.validate()
            request_hash = sha256_text(request.request_hash() + binding_sha256)
        except (StopBoundary, TypeError, ValueError) as exc:
            return self._deny(self._trace(), exc.reason if isinstance(exc, StopBoundary) else "invalid-request",
                              scope="session-start-only")
        early = self._begin(request.invocation_id, request_hash)
        if early is not None:
            return early
        trace = self._trace()
        try:
            proof, _ = self._admitter.admit(request, trace, cancel)
            rid = self._issue_receipt(trace, request, proof, kind="normal", binding_sha256=binding_sha256,
                                      session_id=None, scope="ckr6-session-start")
            self._consume(trace, rid, binding_sha256, scope="ckr6-session-start", cancel=cancel)
        except StopBoundary as exc:
            outcome = self._deny(trace, exc.reason, scope="session-start-only")
            self._remember(request.invocation_id, request_hash, outcome)
            return outcome
        with self._lock:
            self.stats.launches += 1
        trace.record("launch-started")
        try:
            handle = launcher()
        except Exception as exc:  # noqa: BLE001
            trace.record("launch-failed", exception_type=type(exc).__name__)
            outcome = self._finish(trace, dict(admitted=True, reason="admitted-launch-failed:" + type(exc).__name__,
                                               output=None, admission=proof, scope="session-start-only"))
        else:
            outcome = self._finish(trace, dict(admitted=True, reason="admitted", output=handle, admission=proof,
                                               scope="session-start-only"))
        self._remember(request.invocation_id, request_hash, outcome)
        return outcome
