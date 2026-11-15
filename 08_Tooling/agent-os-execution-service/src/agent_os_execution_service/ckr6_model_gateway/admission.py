"""Independent CKR6 admission: GitHub ingress, independent readback, bounded poll,
and the EXISTING repository R07 consumer/selector. No parallel parser lives here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Protocol, Sequence

from .. import ckr6_github_bridge as bridge
from .contract import (
    AdmissionProof, GatewayConfig, InvocationRequest, StopBoundary, Trace, canonical_json, sha256_text,
)


class GitHubTransport(Protocol):
    """Trusted-side GitHub I/O. ``get_issue_comment`` MUST be an independent GET."""

    def post_issue_comment(self, repository: str, issue_number: int, body: str) -> int: ...
    def get_issue_comment(self, repository: str, comment_id: int) -> Mapping[str, Any]: ...
    def list_issue_comments(self, repository: str, issue_number: int) -> Sequence[Mapping[str, Any]]: ...


def _utc(value: object) -> datetime:
    if type(value) is not str:
        raise StopBoundary("request-readback-mismatch:created_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise StopBoundary("request-readback-mismatch:created_at") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StopBoundary("request-readback-mismatch:created_at")
    return parsed


class Ckr6Admitter:
    def __init__(self, transport: GitHubTransport, config: GatewayConfig,
                 clock: Callable[[], datetime], sleep: Callable[[float], None], *,
                 verify_failed_attempt: Callable[[InvocationRequest], bool] | None = None,
                 verify_canonical_unavailability: Callable[[InvocationRequest, Mapping[str, Any]], bool] | None = None) -> None:
        self._transport = transport
        self._config = config
        self._clock = clock
        self._sleep = sleep
        self.verify_failed_attempt = verify_failed_attempt
        self._verify_unavailability = verify_canonical_unavailability

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _check_cancel(cancel: Any, reason: str) -> None:
        if cancel is not None and cancel.is_set():
            raise StopBoundary(reason)

    def _verify_request_record(self, record: object, comment_id: int, body: str,
                               request: InvocationRequest) -> datetime:
        if not isinstance(record, Mapping) or record.get("id") != comment_id:
            raise StopBoundary("request-readback-mismatch:id")
        if record.get("body") != body:
            raise StopBoundary("request-readback-mismatch:body")
        user = record.get("user")
        if not isinstance(user, Mapping) or user.get("login") != self._config.request_author_login:
            raise StopBoundary("request-readback-mismatch:author")
        issue_url, html_url = record.get("issue_url"), record.get("html_url")
        if issue_url is None and html_url is None:
            raise StopBoundary("request-readback-mismatch:location")
        if issue_url is not None and issue_url != (
                f"https://api.github.com/repos/{request.repository}/issues/{request.issue_number}"):
            raise StopBoundary("request-readback-mismatch:location")
        if html_url is not None and html_url != (
                f"https://github.com/{request.repository}/issues/{request.issue_number}#issuecomment-{comment_id}"):
            raise StopBoundary("request-readback-mismatch:location")
        created = _utc(record.get("created_at"))
        updated = record.get("updated_at")
        if updated is None or _utc(updated) != created:  # GitHub always reports it; absence hides edits
            raise StopBoundary("request-readback-mismatch:edited")
        if abs((self._clock() - created).total_seconds()) > self._config.max_clock_skew_seconds:
            raise StopBoundary("request-readback-mismatch:clock-skew")
        return created

    def _select(self, comments: Sequence[Mapping[str, Any]], comment_id: int, created_at: str,
                request: InvocationRequest) -> dict[str, object]:
        return bridge.select_ckr6_result_comment(
            comments, expected_request_comment_id=comment_id, expected_request_created_at=created_at,
            expected_issue_number=request.issue_number, expected_repository=request.repository,
            expected_operation=request.operation, expected_attempt_id=request.attempt_id)

    # ------------------------------------------------------------------- admit
    def admit(self, request: InvocationRequest, trace: Trace, cancel: Any = None) -> tuple[AdmissionProof, dict[str, object]]:
        cfg = self._config
        request.validate()
        if request.repository not in cfg.allowed_repositories:
            raise StopBoundary("repository-not-allowed")
        self._check_cancel(cancel, "cancelled-before-admission")
        try:
            envelope = bridge.parse_envelope(request.envelope_payload())
            expected_material = bool(bridge.classify_envelope(envelope)["retrieval_required"])
        except (ValueError, TypeError):
            raise StopBoundary("envelope-invalid") from None
        trace.record("materiality-classified", expected_material=expected_material,
                     source="canonical-classify_envelope")
        if request.operation == "failed-repair":
            try:
                verified = self.verify_failed_attempt is not None and self.verify_failed_attempt(request) is True
            except Exception:  # noqa: BLE001
                verified = False
            if not verified:
                raise StopBoundary("failed-attempt-record-not-verified")
            trace.record("failed-attempt-record-verified")
        body = bridge.COMMAND_PREFIX + json.dumps(request.envelope_payload(), separators=(",", ":"),
                                                  ensure_ascii=False, sort_keys=True)
        try:
            if bridge.parse_envelope(json.loads(body[len(bridge.COMMAND_PREFIX):])) != envelope:
                raise ValueError
        except (ValueError, TypeError):
            raise StopBoundary("envelope-roundtrip-mismatch") from None
        trace.record("request-prepared", body_sha256=sha256_text(body))
        self._check_cancel(cancel, "cancelled-before-post")
        try:
            comment_id = self._transport.post_issue_comment(request.repository, request.issue_number, body)
        except Exception:  # noqa: BLE001 - ambiguity after a failed POST is terminal, never retried
            raise StopBoundary("ingress-post-failed") from None
        if type(comment_id) is not int or isinstance(comment_id, bool) or comment_id < 1:
            raise StopBoundary("invalid-posted-receipt")
        trace.record("request-posted", comment_id=comment_id)
        try:
            record = self._transport.get_issue_comment(request.repository, comment_id)  # independent GET
        except Exception:  # noqa: BLE001
            raise StopBoundary("request-readback-failed") from None
        created = self._verify_request_record(record, comment_id, body, request)
        created_at = str(record["created_at"])
        trace.record("request-readback-verified", comment_id=comment_id, created_at=created_at)

        deadline = created + timedelta(seconds=cfg.deadline_seconds)
        result: dict[str, object] | None = None
        previous = None
        for _ in range(cfg.max_polls):
            now = self._clock()
            if now >= deadline:
                raise StopBoundary("bounded-wait-expired")
            if previous is not None:
                elapsed = (now - previous).total_seconds()
                if elapsed < cfg.poll_spacing_seconds:
                    self._sleep(cfg.poll_spacing_seconds - elapsed)
                now = self._clock()
                if now >= deadline:
                    raise StopBoundary("bounded-wait-expired")
            previous = now
            self._check_cancel(cancel, "cancelled-while-waiting")
            try:
                comments = self._transport.list_issue_comments(request.repository, request.issue_number)
            except Exception:  # noqa: BLE001
                raise StopBoundary("result-transport-error") from None
            if self._clock() >= deadline:
                raise StopBoundary("bounded-wait-expired")
            try:
                result = self._select(comments, comment_id, created_at, request)
            except (ValueError, TypeError) as exc:
                text = str(exc)
                if "not returned" in text:
                    continue
                raise StopBoundary("result-ambiguous" if "ambiguous" in text else "result-rejected") from None
            break
        if result is None:
            raise StopBoundary("bounded-wait-expired")
        result_sha = sha256_text(canonical_json(result))
        trace.record("result-selected", result_sha256=result_sha, status=result.get("status"))

        # Independent re-read: a result edited/removed/replaced after selection must not admit.
        try:
            comments_after_reread = self._transport.list_issue_comments(request.repository, request.issue_number)
            second = self._select(comments_after_reread, comment_id, created_at, request)
        except (ValueError, TypeError, LookupError, OSError):
            raise StopBoundary("result-reread-mismatch") from None
        if sha256_text(canonical_json(second)) != result_sha:
            raise StopBoundary("result-reread-mismatch")
        trace.record("result-reread-verified", result_sha256=result_sha)
        self._verify_result_records(comments_after_reread, result, created, deadline)

        selected = self._decide(request, result, expected_material, trace)
        now = self._clock()
        if now >= deadline:
            raise StopBoundary("deadline-expired-before-admission")
        self._check_cancel(cancel, "cancelled-before-receipt")
        trace.record("repository-r07-boundary-admitted")
        proof = AdmissionProof(
            identity_hash=request.identity_hash(), operation=request.operation,
            repository=request.repository, issue_number=request.issue_number,
            attempt_id=request.attempt_id, request_comment_id=comment_id, request_created_at=created_at,
            result_status=str(result.get("status")), result_sha256=result_sha, selected_lesson_ids=selected,
            expected_material=expected_material, verified_at=now.isoformat(),
            expires_at=min(deadline, now + timedelta(seconds=cfg.session_ttl_seconds)).isoformat())
        return proof, result

    def _verify_result_records(self, comments: Sequence[Mapping[str, Any]], result: Mapping[str, object],
                               request_created: datetime, deadline: datetime) -> None:
        """Time checks R07 does not make: the result's own timestamps against the deadline and local clock,
        and a mandatory updated_at (so an edit cannot hide behind an absent field)."""
        now = self._clock()
        skew = timedelta(seconds=self._config.max_clock_skew_seconds)
        checked = 0
        for comment in comments:
            user = comment.get("user") if isinstance(comment, Mapping) else None
            body = comment.get("body") if isinstance(comment, Mapping) else None
            if (not isinstance(user, Mapping) or user.get("login") != bridge.CKR6_PRODUCER_LOGIN
                    or user.get("id") != bridge.CKR6_PRODUCER_ACCOUNT_ID or type(body) is not str):
                continue
            try:
                if bridge.parse_ckr6_result_comment(body) != result:
                    continue
            except (ValueError, TypeError):
                continue
            checked += 1
            created, updated = _utc(comment.get("created_at")), comment.get("updated_at")
            if updated is None or _utc(updated) != created:
                raise StopBoundary("result-record-missing-or-edited-updated_at")
            if created > deadline:
                raise StopBoundary("result-after-deadline")
            if created > now + skew:
                raise StopBoundary("result-from-the-future")
        if checked == 0:
            raise StopBoundary("result-reread-mismatch")

    # ---------------------------------------------------------------- decision
    def _decide(self, request: InvocationRequest, result: Mapping[str, object], expected_material: bool,
                trace: Trace) -> tuple[str, ...]:
        if not bridge.ckr6_result_admits_boundary(result):  # the EXISTING repository decision
            raise StopBoundary("repository-r07-boundary-not-admitted")
        if any(result.get(flag) is not False for flag in bridge._AUTHORITY_FLAGS):
            raise StopBoundary("authority-flag-missing-or-nonfalse")
        if (result.get("operation") != request.operation or result.get("repository") != request.repository
                or result.get("issue_number") != request.issue_number
                or (request.operation == "failed-repair" and result.get("attempt_id") != request.attempt_id)):
            raise StopBoundary("post-consumption-binding-mismatch")
        status = result.get("status")
        selected_raw = result.get("selected_lesson_ids") or []
        selected = tuple(selected_raw) if isinstance(selected_raw, list) else ()
        if request.operation == "failed-repair":
            outcome = result.get("retry_reentry_outcome")
            if outcome == "consumed" and status == "sufficient":
                kind = "material"
            elif outcome == "not-material" and status == "not-needed":
                kind = "nonmaterial"
            else:
                raise StopBoundary("repair-reentry-outcome-not-admissible")
        else:
            kind = {"sufficient": "material", "not-needed": "nonmaterial",
                    "unavailable-safe-fallback": "fallback"}.get(str(status), "")
            if not kind:
                raise StopBoundary("issue-start-status-not-admissible")
        if kind == "nonmaterial":
            if expected_material:
                raise StopBoundary("materiality-downgrade")
            if selected or result.get("notion_read_performed") not in (False, None):
                raise StopBoundary("not-needed-must-carry-no-lessons-and-no-read")
            trace.record("nonmaterial-classification-verified")
        elif kind == "material":
            if not expected_material:
                raise StopBoundary("sufficient-with-nonmaterial-request")
            if (not isinstance(selected_raw, list) or not selected_raw or len(set(selected_raw)) != len(selected_raw)
                    or any(type(item) is not str or not item.strip() for item in selected_raw)):
                raise StopBoundary("sufficient-without-valid-selection")  # failed-repair has no R07 check for this
            if result.get("retrieval_required") is False:
                raise StopBoundary("result-contradicts-materiality")
            lessons = result.get("selected_lessons")
            if lessons is not None and (
                    not isinstance(lessons, list)
                    or [l.get("lesson_id") if isinstance(l, Mapping) else None for l in lessons] != list(selected)):
                raise StopBoundary("selection-incoherent")
        else:  # fallback
            if not expected_material:
                raise StopBoundary("nonmaterial-fallback")
            try:
                verified = self._verify_unavailability is not None and self._verify_unavailability(request, result) is True
            except Exception:  # noqa: BLE001
                verified = False
            if not verified:
                raise StopBoundary("canonical-unavailability-not-verified")
            trace.record("canonical-unavailability-verified")
        return selected
