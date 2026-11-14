"""Immutable request identity, trace, and counters for the CKR6 model gateway.

Nothing here grants authority. A ``StopBoundary`` is terminal for the call that
raised it: the gateway never retries a denied admission.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping

OPERATIONS = frozenset({"issue-start", "failed-repair"})
# Model-entry kinds. ``invoke`` gives every kind a fresh full admission; a
# bounded session amortises one admission across ``normal``/``tool-continuation``
# turns and ``subagent`` turns of derived child sessions (see gateway.py).
KINDS = frozenset({"normal", "stream", "tool-continuation", "subagent", "retry", "resume"})
HINT_FIELDS = (
    "ecosystem_hints", "language_hints", "library_hints", "capability_keywords",
    "target_path_hints", "canonical_rule_refs", "known_knowledge_refs",
)
MAX_PROMPT_BYTES = 256 * 1024


class StopBoundary(RuntimeError):
    """Terminal STOP with a stable reason code in ``args[0]``."""

    @property
    def reason(self) -> str:
        return str(self.args[0]) if self.args else "stop"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class InvocationRequest:
    """Who/what/why of one model entry. There is deliberately NO admitted /
    specialized-knowledge / status field: materiality is computed by the gateway
    from the canonical planner and admission only from verified GitHub evidence."""

    invocation_id: str
    operation: str
    repository: str
    issue_number: int
    task_reference: str
    prompt: str = ""
    kind: str = "normal"
    attempt_id: str | None = None
    failed_hypothesis: str | None = None
    result_summary: str | None = None
    repair_context: str = "failed-pr-repair"
    ecosystem_hints: tuple[str, ...] = ()
    language_hints: tuple[str, ...] = ()
    library_hints: tuple[str, ...] = ()
    capability_keywords: tuple[str, ...] = ()
    target_path_hints: tuple[str, ...] = ()
    canonical_rule_refs: tuple[str, ...] = ()
    known_knowledge_refs: tuple[str, ...] = ()

    def validate(self) -> None:
        if type(self.invocation_id) is not str or not self.invocation_id.strip():
            raise StopBoundary("invalid-invocation-id")
        if (type(self.repository) is not str or type(self.task_reference) is not str
                or type(self.issue_number) is not int or isinstance(self.issue_number, bool)
                or any(type(getattr(self, n)) is not tuple or any(type(h) is not str for h in getattr(self, n))
                       for n in HINT_FIELDS)):
            raise StopBoundary("invalid-request")
        if self.operation not in OPERATIONS:
            raise StopBoundary("unsupported-operation")
        if self.kind not in KINDS:
            raise StopBoundary("unsupported-kind")
        if type(self.prompt) is not str or len(self.prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise StopBoundary("invalid-prompt")
        if self.operation == "issue-start" and (
            self.attempt_id or self.failed_hypothesis or self.result_summary
        ):
            raise StopBoundary("issue-start-must-not-carry-repair-attempt")
        if self.operation == "failed-repair" and not (
            self.attempt_id and self.failed_hypothesis and self.result_summary
        ):
            raise StopBoundary("missing-recorded-failed-attempt")

    def envelope_payload(self) -> dict[str, object]:
        """The CKR6 ingress envelope. ``specialized_knowledge_required`` is OMITTED on
        purpose so the canonical planner (not the caller) decides materiality."""
        payload: dict[str, object] = {
            "operation": self.operation, "repository": self.repository,
            "issue_number": self.issue_number, "task_reference": self.task_reference,
        }
        for name in HINT_FIELDS:
            hints = getattr(self, name)
            if hints:
                payload[name] = list(hints)
        if self.operation == "failed-repair":
            payload.update(attempt_id=self.attempt_id, failed_hypothesis=self.failed_hypothesis,
                           result_summary=self.result_summary, repair_context=self.repair_context)
        return payload

    def identity_hash(self) -> str:
        """Binds an admission to this exact request identity (prompt excluded: a
        bounded session admits an identity; each call binds its own prompt hash)."""
        body = {**self.envelope_payload(), "invocation_id": self.invocation_id}
        return sha256_text(canonical_json(body))

    def request_hash(self) -> str:
        return sha256_text(canonical_json({
            "identity": self.identity_hash(), "kind": self.kind, "prompt_sha256": sha256_text(self.prompt)}))

    def with_(self, **changes: Any) -> "InvocationRequest":
        from dataclasses import replace
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    allowed_repositories: tuple[str, ...]
    request_author_login: str
    receipt_ttl_seconds: int = 60
    session_ttl_seconds: int = 300
    session_max_turns: int = 8
    session_max_children: int = 2
    session_max_depth: int = 2
    max_polls: int = 12
    poll_spacing_seconds: int = 30
    deadline_seconds: int = 360
    max_clock_skew_seconds: int = 120


@dataclass(frozen=True, slots=True)
class AdmissionProof:
    """Evidence an admission rests on. Contains no lesson payload text."""

    identity_hash: str
    operation: str
    repository: str
    issue_number: int
    attempt_id: str | None
    request_comment_id: int
    request_created_at: str
    result_status: str
    result_sha256: str
    selected_lesson_ids: tuple[str, ...]
    expected_material: bool
    verified_at: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class AdmissionReceipt:
    """One-time, expiring, model-entry-scoped. Never leaves the gateway process."""

    receipt_id: str
    scope: str  # always "ckr6-model-entry" (or "ckr6-session-start" for launch gating)
    identity_hash: str
    invocation_id: str
    kind: str
    prompt_sha256: str
    result_sha256: str
    request_comment_id: int
    attempt_id: str | None
    session_id: str | None
    issued_at: datetime
    expires_at: datetime


@dataclass
class Stats:
    receipts_issued: int = 0
    receipts_consumed: int = 0
    backend_calls: int = 0
    denied: int = 0
    launches: int = 0

    def snapshot(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class Trace:
    """Gateway-owned ordered event log. Never records prompts, lessons, or credentials."""

    clock: Callable[[], datetime]
    events: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, event: str, **meta: Any) -> None:
        with self._lock:
            self.events.append({"seq": len(self.events) + 1, "event": event,
                                "ts": self.clock().isoformat(), **meta})


@dataclass(frozen=True, slots=True)
class InvocationOutcome:
    admitted: bool
    reason: str
    output: Any
    trace: tuple[Mapping[str, Any], ...]
    admission: AdmissionProof | None = None
    replayed: bool = False
    session: str | None = None
    # "model-entry": every provider call was gated. "session-start-only": a model-capable
    # process was launched after admission but its internal requests are NOT mediated.
    scope: str = "model-entry"
