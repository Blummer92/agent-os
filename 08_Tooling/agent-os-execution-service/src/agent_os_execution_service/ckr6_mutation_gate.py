"""CKR6 mutation-boundary gate: landing-only enforcement (#2425 follow-up).

A required-lane CI check that refuses to let governed work land without a
trusted CKR6 admission bound to the exact work attempt under test. This
enforces the LANDING boundary only: it cannot and does not try to govern
what a host does inside a chat before work is proposed for landing (no
pre-work hook is proven to exist in the current GitHub-connector path; the
overlay itself states "Procedure, not mechanical enforcement").

The gate performs its OWN trusted reads through a completeness-checked,
repo-scoped read path (``github.token`` in Actions, the binding pattern
shipped by #3963 for the refinement read step) and consumes results only
through the R07-hardened consumer (``select_ckr6_result_comment`` /
``ckr6_result_admits_boundary``). Nothing the host pastes is trusted: every
request and result is re-validated from the GitHub record.

Semantics (fail closed):
- Boundary operations are ``issue-start`` and ``failed-repair``. Learning
  operations (``lesson-candidate`` / ``lesson-refinement``) never decide the
  gate.
- A trusted request is an owner-authored, UNEDITED comment record (record
  ``updated_at`` must equal ``created_at``; a missing ``updated_at`` is not
  trusted) from the owner's exact numeric account id (login alone is not
  identity: an account rename could reuse it), whose body is a canonical
  CKR6 command envelope parsed by the ingress's own parser, whose envelope
  repository and issue number match the thread it was posted on.
- Producer result records are held to the SAME unedited proof: a producer
  record whose ``updated_at`` is missing or differs from ``created_at`` is
  not evidence and is excluded before result selection.
- The NEWEST trusted boundary request across the linked-issue thread and the
  PR thread decides. An older admitted request never rescues a newer
  unanswered, ambiguous, invalid, or blocked request.
- Work-attempt binding: when a PR is gated, the newest trusted request must
  (a) name the gated head's exact 40-hex SHA in its ``task_reference``
  (``ckr6-request-head-unbound`` otherwise) and (b) postdate the
  server-recorded push that proposed that head (found via the repository
  Events API; commit author/committer dates are author-controlled and are
  never used). A push after admission invalidates it - "admit once, then
  change the work" is blocked, and a fresh admission for unrelated work on
  the linked issue admits nothing here. Remediation: the owner posts a
  fresh ``/agent-os ckr6`` request naming the current head and the failed
  check is re-run. When no push event for the exact head SHA is visible
  (event retention is bounded), the gate fails closed with
  ``ckr6-head-proposal-unproven``.
- The newest request's result is selected from the SAME thread's records
  with exact request binding (``request_comment_id``, request
  ``created_at``, operation, and for failed-repair the envelope's exact
  ``attempt_id``). The boundary is admitted only when
  ``ckr6_result_admits_boundary`` accepts the consumed payload. A valid
  blocked result (``insufficient`` / ``manual-review`` / bounded
  infrastructure fallback) is STOP evidence, never an admission.
- Comment reads paginate to exhaustion with a bounded page count; a thread
  too deep to read completely fails closed (``ckr6-read-unavailable``)
  rather than deciding on a truncated, oldest-first page.

Documented residuals (explicit, not silently accepted):
- Two PRs sharing one head branch share one head SHA, so one head-named
  admission covers both (identical content; low impact).
- Naming the head in ``task_reference`` free text is the gate-local
  convention; the durable form is an optional typed ``head_sha`` envelope
  field, which needs a small ingress parser change (``parse_envelope``
  rejects unknown fields today) and is tracked as a separate owner
  proposal. The gate's requirement is identical under either form.
- Revocation timing: issue comments do not re-trigger the PR check. A newer
  blocking owner request posted after a green run takes effect on the next
  gate evaluation (any PR event or a maintainer re-run).
- The gate module path is not yet in the trusted status publisher's
  authority surface; until it is, a PR that edits this module self-certifies
  its own enforcement. Adding the module path to the publisher's authority
  set is owner-side follow-up, tracked with the workflow.

This module grants no repository write, merge, closure, Notion, execution,
or credential authority. It reads issue comments and returns a verdict.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping, Sequence

from .ckr6_github_bridge import (
    CKR6_PRODUCER_ACCOUNT_ID,
    CKR6_PRODUCER_LOGIN,
    COMMAND_PREFIX,
    MAX_COMMENT_BYTES,
    ckr6_result_admits_boundary,
    parse_envelope,
    select_ckr6_result_comment,
    # Deliberate same-package reuse of the ingress's own payload decoder so
    # the gate accepts exactly the request syntax the ingress accepts
    # (including the one documented host attribution trailer) and no more.
    _command_payload,
)
from .ckr6_github_reader import (
    ALLOWED_REPOSITORY,
    GITHUB_API_BASE_URL,
    GitHubIssueCommentReadUnavailable,
)

DEFAULT_ALLOWED_ACTOR = "Blummer92"
# The owner's exact numeric GitHub account id, from the live 2026-11-14
# request record 6870478787 (login alone is not identity: a vacated login
# can be registered by someone else; the numeric id cannot be reused).
DEFAULT_ALLOWED_ACTOR_ID = 32861845

# Only boundary operations create a landing obligation. Learning operations
# never admit a boundary and must not decide this gate.
BOUNDARY_OPERATIONS = frozenset({"issue-start", "failed-repair"})

# Finite verdict reason codes.
ADMITTED = "admitted"
REQUEST_MISSING = "ckr6-request-missing"
REQUEST_UNANSWERED = "ckr6-request-unanswered"
REQUEST_STALE = "ckr6-request-stale"
REQUEST_HEAD_UNBOUND = "ckr6-request-head-unbound"
RESULT_AMBIGUOUS = "ckr6-result-ambiguous"
RESULT_INVALID = "ckr6-result-invalid"
BOUNDARY_BLOCKED = "ckr6-boundary-blocked"
READ_UNAVAILABLE = "ckr6-read-unavailable"
HEAD_PROPOSAL_UNPROVEN = "ckr6-head-proposal-unproven"
ISSUE_LINK_MISSING = "ckr6-issue-link-missing"
ISSUE_LINK_AMBIGUOUS = "ckr6-issue-link-ambiguous"
EVENT_INVALID = "ckr6-event-invalid"

_MAX_EVENT_BYTES = 1024 * 1024

# Read bounds mirroring the shared reader's: one bounded page per request,
# a bounded number of pages, a bounded response size.
_COMMENT_PAGE_SIZE = 100
_MAX_COMMENT_PAGES = 50  # 5000 comments; deeper threads fail closed.
_EVENT_PAGE_SIZE = 100
_MAX_EVENT_PAGES = 3  # the Events API retains at most 300 events / 90 days.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_READ_TIMEOUT_SECONDS = 30
_USER_AGENT = "agent-os-ckr6-mutation-gate"
_READ_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": _USER_AGENT,
    "X-GitHub-Api-Version": "2022-11-28",
}
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_HEAD_SHA_RE = re.compile(r"(?i)^[0-9a-f]{40}$")

# Closing-keyword convention mirroring the GitHub-effective detection in
# scripts/agent_os_issue_acceptance/parse_pr.py: markdown that GitHub does
# not treat as content (HTML comments, fenced/indented/inline code, quotes)
# cannot carry a directive, and an authoritative directive is line-anchored,
# not a keyword substring inside prose. The full convention (Non-closing
# directives, informational references, title evidence) stays owned by
# parse_pr.py; this gate only needs the single this-repo closing target.
_CANONICAL_REPOSITORY = "blummer92/agent-os"
_EXPLICIT_KEYWORDS = r"close[sd]?|fix(?:e[sd])?|resolve[sd]?"
_URL_TARGET = (
    r"https://github\.com/(?P<url_repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"/issues/(?P<url_number>\d+)"
)
_CLOSING_DIRECTIVE_RE = re.compile(
    rf"^[ \t]*(?:{_EXPLICIT_KEYWORDS})"
    rf"(?:\s*:\s*|\s+)(?:{_URL_TARGET}|#(?P<number>\d+))\b",
    re.IGNORECASE | re.MULTILINE,
)
_ISSUE_REFERENCE_RE = re.compile(
    rf"(?<![A-Za-z0-9_.-])(?:{_URL_TARGET}|#(?P<number>\d+))\b"
)
_AUTHORITATIVE_PREFIX_RE = re.compile(
    rf"\b(?:{_EXPLICIT_KEYWORDS}|address(?:es|ed)?)\b[^#\n]{{0,80}}$",
    re.IGNORECASE,
)
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*?`+")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _mask_text(text: str) -> str:
    return "".join(
        "\n" if character == "\n" else "\r" if character == "\r" else " "
        for character in text
    )


def _mask_non_authoritative_markdown(text: str) -> str:
    """Blank markdown regions GitHub does not treat as prose content.

    Mirrors parse_pr._mask_non_authoritative_markdown so a closing-looking
    string inside an HTML comment, code fence, indented code block,
    blockquote, or inline code span cannot bind an issue here either.
    """
    masked = _HTML_COMMENT_RE.sub(lambda match: _mask_text(match.group(0)), text)
    output: list[str] = []
    fence_marker: str | None = None
    for line in masked.splitlines(keepends=True):
        if line.startswith(("    ", "\t")):
            output.append(_mask_text(line))
            continue
        stripped = line.lstrip()
        fence = re.match(r"(`{3,}|~{3,})(.*)$", stripped.rstrip("\r\n"))
        if fence_marker is not None:
            if (
                fence is not None
                and fence.group(1)[0] == fence_marker[0]
                and len(fence.group(1)) >= len(fence_marker)
                and not fence.group(2).strip(" \t")
            ):
                fence_marker = None
            output.append(_mask_text(line))
            continue
        if fence is not None:
            fence_marker = fence.group(1)
            output.append(_mask_text(line))
            continue
        if stripped.startswith(">"):
            output.append(_mask_text(line))
            continue
        output.append(_INLINE_CODE_RE.sub(lambda match: _mask_text(match.group(0)), line))
    return "".join(output)


def _parse_github_ts(value: str) -> datetime:
    """Parse a GitHub UTC timestamp; anything unparseable is a caller error."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The gate verdict. ``detail`` carries only bounded contract text."""

    admitted: bool
    reason_code: str
    operation: str | None = None
    status: str | None = None
    request_comment_id: int | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "reason_code": self.reason_code,
            "operation": self.operation,
            "status": self.status,
            "request_comment_id": self.request_comment_id,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class _TrustedRequest:
    envelope: Any
    comment_id: int
    created_at: str
    target_kind: str
    thread_comments: Sequence[Mapping[str, object]]


def _drop_unproven_producer_records(
    comments: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Exclude producer records that cannot prove they are unedited.

    The R07 consumer rejects an EDITED result record (``updated_at`` present
    and different) but accepts one with the field MISSING. The request side
    of this gate requires the proof positively, so the same standard is
    applied here before result selection: a trusted-producer record without
    a present-and-equal ``updated_at`` is not evidence and does not
    participate in selection, ambiguity, or admission.
    """
    kept: list[Mapping[str, object]] = []
    for record in comments:
        if isinstance(record, Mapping):
            user = record.get("user")
            if (
                isinstance(user, Mapping)
                and user.get("login") == CKR6_PRODUCER_LOGIN
                and type(user.get("id")) is int
                and user.get("id") == CKR6_PRODUCER_ACCOUNT_ID
            ):
                created_at = record.get("created_at")
                updated_at = record.get("updated_at")
                if (
                    type(created_at) is not str
                    or type(updated_at) is not str
                    or updated_at != created_at
                ):
                    continue
        kept.append(record)
    return kept


def _trusted_boundary_requests(
    comments: object,
    *,
    repository: str,
    thread_number: int,
    target_kind: str,
    allowed_actor: str,
    allowed_actor_id: int,
) -> list[_TrustedRequest]:
    """Return the thread's trusted boundary-operation requests, or [].

    Every check fails closed by exclusion: anything untrusted is simply not
    a request. Mirrors the ingress contract (owner actor, command prefix,
    bounded body, canonical envelope, repository and thread identity) plus a
    mandatory unedited proof and the owner's exact numeric account id.
    """
    if comments is None or isinstance(comments, (str, bytes, Mapping)):
        raise TypeError("comments must be an iterable of comment records")
    trusted: list[_TrustedRequest] = []
    for record in comments:
        if not isinstance(record, Mapping):
            continue
        comment_id = record.get("id")
        if type(comment_id) is not int or isinstance(comment_id, bool) or comment_id < 1:
            continue
        body = record.get("body")
        if (
            type(body) is not str
            or not body.startswith(COMMAND_PREFIX)
            or len(body.encode("utf-8")) > MAX_COMMENT_BYTES
        ):
            continue
        user = record.get("user")
        if not isinstance(user, Mapping) or user.get("login") != allowed_actor:
            continue
        account_id = user.get("id")
        if (
            type(account_id) is not int
            or isinstance(account_id, bool)
            or account_id != allowed_actor_id
        ):
            continue
        created_at = record.get("created_at")
        if type(created_at) is not str or not created_at.strip():
            continue
        try:
            _parse_github_ts(created_at)
        except ValueError:
            continue
        updated_at = record.get("updated_at")
        # An edited request, or one whose record cannot prove it is unedited,
        # is never trusted.
        if type(updated_at) is not str or updated_at != created_at:
            continue
        try:
            payload = _command_payload(body[len(COMMAND_PREFIX):])
            if type(payload) is not dict:
                continue
            envelope = parse_envelope(payload)
        except (TypeError, ValueError):
            continue
        if envelope.repository != repository:
            continue
        if envelope.issue_number != thread_number:
            continue
        if envelope.operation not in BOUNDARY_OPERATIONS:
            continue
        trusted.append(
            _TrustedRequest(
                envelope=envelope,
                comment_id=comment_id,
                created_at=created_at,
                target_kind=target_kind,
                thread_comments=comments,
            )
        )
    return trusted


def evaluate_mutation_boundary(
    *,
    repository: str,
    issue_number: int,
    issue_comments: Sequence[Mapping[str, object]],
    pr_number: int | None = None,
    pr_comments: Sequence[Mapping[str, object]] = (),
    allowed_actor: str = DEFAULT_ALLOWED_ACTOR,
    allowed_actor_id: int = DEFAULT_ALLOWED_ACTOR_ID,
    head_proposed_at: str | None = None,
    head_sha: str | None = None,
) -> GateDecision:
    """Decide whether the CKR6 mutation boundary admits landing.

    Pure function over already-read comment records; the newest trusted
    boundary request across the issue thread and the PR thread decides. When
    ``head_proposed_at`` is given (the server-recorded time the gated head
    was pushed), the newest trusted request must strictly postdate it.
    """
    if type(repository) is not str or not repository.strip():
        raise ValueError("repository must be non-empty exact text")
    if type(issue_number) is not int or isinstance(issue_number, bool) or issue_number < 1:
        raise ValueError("issue_number must be a positive integer")
    if pr_number is not None and (
        type(pr_number) is not int or isinstance(pr_number, bool) or pr_number < 1
    ):
        raise ValueError("pr_number must be a positive integer")
    if type(allowed_actor) is not str or not allowed_actor.strip():
        raise ValueError("allowed_actor must be non-empty exact text")
    if (
        type(allowed_actor_id) is not int
        or isinstance(allowed_actor_id, bool)
        or allowed_actor_id < 1
    ):
        raise ValueError("allowed_actor_id must be a positive integer")
    if head_proposed_at is not None:
        if type(head_proposed_at) is not str:
            raise ValueError("head_proposed_at must be exact text")
        head_dt = _parse_github_ts(head_proposed_at)
    else:
        head_dt = None
    if head_sha is not None and (
        type(head_sha) is not str or not _HEAD_SHA_RE.match(head_sha)
    ):
        raise ValueError("head_sha must be exact 40-hex text")

    requests = _trusted_boundary_requests(
        _drop_unproven_producer_records(issue_comments),
        repository=repository,
        thread_number=issue_number,
        target_kind="issue",
        allowed_actor=allowed_actor,
        allowed_actor_id=allowed_actor_id,
    )
    if pr_number is not None:
        requests = requests + _trusted_boundary_requests(
            _drop_unproven_producer_records(pr_comments),
            repository=repository,
            thread_number=pr_number,
            target_kind="pr",
            allowed_actor=allowed_actor,
            allowed_actor_id=allowed_actor_id,
        )
    if not requests:
        return GateDecision(False, REQUEST_MISSING)

    newest = max(requests, key=lambda r: (r.created_at, r.comment_id))
    envelope = newest.envelope
    if head_sha is not None and head_sha.lower() not in envelope.task_reference.lower():
        return GateDecision(
            False,
            REQUEST_HEAD_UNBOUND,
            operation=envelope.operation,
            request_comment_id=newest.comment_id,
            detail=(
                "the newest trusted request does not name the gated head; "
                "admission must name this exact work attempt in "
                "task_reference"
            ),
        )
    if head_dt is not None and _parse_github_ts(newest.created_at) <= head_dt:
        return GateDecision(
            False,
            REQUEST_STALE,
            operation=envelope.operation,
            request_comment_id=newest.comment_id,
            detail=(
                "the newest trusted request predates the current head's "
                "proposal; admission must be re-requested for this exact "
                "work attempt"
            ),
        )
    try:
        payload = select_ckr6_result_comment(
            newest.thread_comments,
            expected_request_comment_id=newest.comment_id,
            expected_request_created_at=newest.created_at,
            expected_issue_number=envelope.issue_number,
            expected_repository=repository,
            expected_operation=envelope.operation,
            expected_attempt_id=(
                envelope.attempt_id if envelope.operation == "failed-repair" else None
            ),
            expected_target_kind=newest.target_kind,
        )
    except ValueError as exc:
        message = str(exc)
        if message.startswith("CKR6 result not returned"):
            reason = REQUEST_UNANSWERED
        elif message.startswith("ambiguous CKR6 result"):
            reason = RESULT_AMBIGUOUS
        else:
            reason = RESULT_INVALID
        return GateDecision(
            False,
            reason,
            operation=envelope.operation,
            request_comment_id=newest.comment_id,
            detail=message,
        )

    status = payload.get("status")
    status_text = status if type(status) is str else None
    if ckr6_result_admits_boundary(payload):
        return GateDecision(
            True,
            ADMITTED,
            operation=envelope.operation,
            status=status_text,
            request_comment_id=newest.comment_id,
        )
    reason_codes = payload.get("reason_codes")
    bounded_codes = (
        ",".join(code for code in reason_codes if type(code) is str)
        if isinstance(reason_codes, list)
        else ""
    )
    return GateDecision(
        False,
        BOUNDARY_BLOCKED,
        operation=envelope.operation,
        status=status_text,
        request_comment_id=newest.comment_id,
        detail=f"status={status_text} reason_codes=[{bounded_codes}]",
    )


# ``http_get(url, headers) -> (status_code, body_bytes)``, the same
# injectable transport contract as the shared reader, so tests never touch
# the network.
HttpGet = Callable[[str, dict[str, str]], "tuple[int, bytes]"]


def _urllib_http_get(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=_READ_TIMEOUT_SECONDS) as response:
            return response.status, response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise GitHubIssueCommentReadUnavailable(
            "github-api-failure", f"GitHub API returned HTTP {exc.code}"
        ) from exc
    except Exception as exc:  # URLError, timeout, TLS failure: no read happened.
        raise GitHubIssueCommentReadUnavailable(
            "github-api-failure", f"GitHub API read failed: {type(exc).__name__}"
        ) from exc


class PaginatedIssueCommentReader:
    """Completeness-checked trusted reads for the gate's decision inputs.

    The shared ``GitHubIssueCommentReader`` reads ONE oldest-first page of
    comments with no completeness signal; on a thread deeper than 100
    comments a newer owner request would be invisible and the gate would
    decide on a stale subset. This reader paginates to exhaustion with a
    bounded page count and fails closed when completeness cannot be
    established. It also reads the server-recorded push time of an exact
    branch head from the repository Events API (commit timestamps are
    author-controlled and never used). Same trust bound as the shared
    reader: GET only, bounded responses, the token leaves the process never.
    """

    def __init__(
        self,
        *,
        token_provider: Any = None,
        http_get: HttpGet | None = None,
    ) -> None:
        self._token_provider = token_provider
        self._http_get = http_get or _urllib_http_get

    def _token(self) -> str:
        if self._token_provider is None:
            raise GitHubIssueCommentReadUnavailable(
                "HOST_READ_PATH_UNAVAILABLE",
                "no GitHub App installation-token provider is installed",
            )
        try:
            token = self._token_provider.get_installation_token()
        except Exception:
            raise GitHubIssueCommentReadUnavailable(
                "HOST_READ_PATH_UNAVAILABLE",
                "GitHub App installation token is unavailable",
            ) from None
        if type(token) is not str or not token.strip():
            raise GitHubIssueCommentReadUnavailable(
                "HOST_READ_PATH_UNAVAILABLE",
                "no GitHub App installation token is available",
            )
        return token

    def _get_json_list(self, url: str) -> list[Mapping[str, object]]:
        status, body = self._http_get(
            url, _READ_HEADERS | {"Authorization": "Bearer " + self._token()}
        )
        if status != 200:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-failure", f"GitHub API returned HTTP {status}"
            )
        if len(body) > _MAX_RESPONSE_BYTES:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-unexpected-response",
                "GitHub API response exceeds the bounded size",
            )
        try:
            records = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubIssueCommentReadUnavailable(
                "github-api-unexpected-response", "GitHub API response is not valid JSON"
            ) from exc
        if type(records) is not list or any(
            not isinstance(item, Mapping) for item in records
        ):
            raise GitHubIssueCommentReadUnavailable(
                "github-api-unexpected-response",
                "GitHub API response is not a list of records",
            )
        return records

    def read_issue_comments(
        self, repository: str, issue_number: int
    ) -> list[dict[str, object]]:
        """Return ALL of the thread's comment records, newest-last.

        Paginates to exhaustion. Raises ``ValueError`` on malformed caller
        identity and ``GitHubIssueCommentReadUnavailable`` when no token is
        available, the transport fails, a page is malformed, or the thread
        exceeds the bounded page count (completeness unproven: fail closed).
        """
        if type(repository) is not str or repository != ALLOWED_REPOSITORY:
            raise ValueError(
                "GitHub issue-comment reads are scoped to exactly "
                f"{ALLOWED_REPOSITORY}"
            )
        if type(issue_number) is not int or isinstance(issue_number, bool) or issue_number < 1:
            raise ValueError("issue_number must be a positive integer")
        records: list[dict[str, object]] = []
        for page in range(1, _MAX_COMMENT_PAGES + 1):
            batch = self._get_json_list(
                f"{GITHUB_API_BASE_URL}/repos/{repository}/issues/{issue_number}"
                f"/comments?per_page={_COMMENT_PAGE_SIZE}&page={page}"
            )
            records.extend(dict(item) for item in batch)
            if len(batch) < _COMMENT_PAGE_SIZE:
                return records
        raise GitHubIssueCommentReadUnavailable(
            "github-api-unexpected-response",
            "comment pagination exceeds the bounded page count",
        )

    def read_branch_push_time(
        self, repository: str, branch: str, head_sha: str
    ) -> str | None:
        """Return when ``head_sha`` was last pushed to ``branch``, or None.

        Scans the repository Events API (server-assigned ``created_at``;
        bounded to the API's retained window). ``None`` means the push that
        proposed this exact head is not visible - retention exceeded or the
        head never landed on this ref - and callers must fail closed.
        """
        if type(repository) is not str or not _REPOSITORY_RE.match(repository):
            raise ValueError("repository must be exact owner/name text")
        if type(branch) is not str or not branch.strip():
            raise ValueError("branch must be non-empty exact text")
        if type(head_sha) is not str or not head_sha.strip():
            raise ValueError("head_sha must be non-empty exact text")
        wanted_ref = f"refs/heads/{branch}"
        latest: datetime | None = None
        latest_text: str | None = None
        for page in range(1, _MAX_EVENT_PAGES + 1):
            events = self._get_json_list(
                f"{GITHUB_API_BASE_URL}/repos/{repository}/events"
                f"?per_page={_EVENT_PAGE_SIZE}&page={page}"
            )
            for event in events:
                if event.get("type") != "PushEvent":
                    continue
                payload = event.get("payload")
                if not isinstance(payload, Mapping):
                    continue
                if payload.get("ref") != wanted_ref or payload.get("head") != head_sha:
                    continue
                created_at = event.get("created_at")
                if type(created_at) is not str:
                    continue
                try:
                    parsed = _parse_github_ts(created_at)
                except ValueError:
                    continue
                if latest is None or parsed > latest:
                    latest = parsed
                    latest_text = created_at
            if len(events) < _EVENT_PAGE_SIZE:
                break
        return latest_text


def run_gate(
    *,
    reader: Any,
    repository: str,
    issue_number: int,
    pr_number: int | None = None,
    allowed_actor: str = DEFAULT_ALLOWED_ACTOR,
    allowed_actor_id: int = DEFAULT_ALLOWED_ACTOR_ID,
    head_repository: str | None = None,
    head_branch: str | None = None,
    head_sha: str | None = None,
) -> GateDecision:
    """Read both threads through the trusted read path, then decide.

    When a PR is gated, the head's server-recorded push time is read first
    and the admission must postdate it; a head whose proposal cannot be
    proven fails closed.
    """
    head_proposed_at: str | None = None
    if pr_number is not None:
        if head_repository is None or head_branch is None or head_sha is None:
            raise ValueError(
                "head_repository, head_branch and head_sha are required "
                "when a pull request is gated"
            )
        if type(head_sha) is not str or not _HEAD_SHA_RE.match(head_sha):
            raise ValueError("head_sha must be exact 40-hex text")
        try:
            head_proposed_at = reader.read_branch_push_time(
                head_repository, head_branch, head_sha
            )
        except GitHubIssueCommentReadUnavailable as exc:
            return GateDecision(False, READ_UNAVAILABLE, detail=exc.reason_code)
        if head_proposed_at is None:
            return GateDecision(
                False,
                HEAD_PROPOSAL_UNPROVEN,
                detail=(
                    "no server-recorded push of this exact head to the PR "
                    "branch is visible in the retained events"
                ),
            )
    try:
        issue_comments = reader.read_issue_comments(repository, issue_number)
        if pr_number is not None and pr_number != issue_number:
            pr_comments: Sequence[Mapping[str, object]] = reader.read_issue_comments(
                repository, pr_number
            )
        else:
            pr_comments = ()
    except GitHubIssueCommentReadUnavailable as exc:
        return GateDecision(False, READ_UNAVAILABLE, detail=exc.reason_code)
    return evaluate_mutation_boundary(
        repository=repository,
        issue_number=issue_number,
        issue_comments=issue_comments,
        pr_number=pr_number,
        pr_comments=pr_comments,
        allowed_actor=allowed_actor,
        allowed_actor_id=allowed_actor_id,
        head_proposed_at=head_proposed_at,
        head_sha=head_sha if pr_number is not None else None,
    )


def _linked_issue_from_pr_body(body: object) -> int:
    """Return the single closing-keyword issue target of a PR body.

    Mirrors parse_pr.py's GitHub-effective detection: non-prose markdown is
    masked, directives must be line-anchored, and a URL target binds only
    when it names this repository (a cross-repo closing URL is not a link
    into this tracker). Zero or several distinct this-repo targets are not
    decidable here and fail closed; the full linked-issue convention stays
    owned by parse_pr.py.
    """
    if type(body) is not str:
        raise ValueError(ISSUE_LINK_MISSING)
    masked = _mask_non_authoritative_markdown(body)

    def _this_repo_number(match: re.Match[str]) -> int | None:
        url_number = match.group("url_number")
        if url_number is not None:
            if match.group("url_repository").lower() != _CANONICAL_REPOSITORY:
                return None  # a reference into another tracker binds nothing here
            return int(url_number)
        return int(match.group("number"))

    explicit: set[int] = set()
    occupied: list[tuple[int, int]] = []
    for match in _CLOSING_DIRECTIVE_RE.finditer(masked):
        number = _this_repo_number(match)
        if number is not None:
            explicit.add(number)
        occupied.append(match.span())
    closing_looking: set[int] = set()
    for match in _ISSUE_REFERENCE_RE.finditer(masked):
        if any(start < match.end() and match.start() < end for start, end in occupied):
            continue
        line_start = masked.rfind("\n", 0, match.start()) + 1
        prefix = masked[max(line_start, match.start() - 90):match.start()]
        if not _AUTHORITATIVE_PREFIX_RE.search(prefix):
            continue  # an informational mention, not a linkage claim
        number = _this_repo_number(match)
        if number is not None:
            closing_looking.add(number)
    if len(explicit) == 1 and closing_looking <= explicit:
        return next(iter(explicit))
    if explicit or closing_looking:
        # Several directives, or closing-looking references with no
        # standalone directive: not decidable here, fail closed.
        raise ValueError(ISSUE_LINK_AMBIGUOUS)
    raise ValueError(ISSUE_LINK_MISSING)


class _EnvTokenProvider:
    """The workflow's repo-scoped ``github.token`` from the step environment.

    Mirrors the bridge's Actions token provider (private there); duplicated
    deliberately as five lines so this module imports no other private name
    than the envelope decoder. The token is never logged, stored, or
    returned.
    """

    def get_installation_token(self) -> str | None:
        token = os.environ.get("GITHUB_TOKEN", "")
        return token if token.strip() else None


def _load_event(path: str) -> Mapping[str, object]:
    if os.path.getsize(path) > _MAX_EVENT_BYTES:
        raise ValueError("event payload exceeds the bounded size")
    with open(path, encoding="utf-8") as handle:
        event = json.load(handle)
    if not isinstance(event, Mapping):
        raise ValueError("event payload must be a mapping")
    return event


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed CKR6 mutation-boundary gate (landing only)."
    )
    parser.add_argument("--event", required=True, help="Path to the GitHub event payload JSON")
    parser.add_argument("--repository", required=True)
    parser.add_argument(
        "--issue-number",
        type=int,
        default=None,
        help="Linked issue number; when omitted, the single closing-keyword "
        "target of the PR body is used",
    )
    parser.add_argument("--allowed-actor", required=False, default=DEFAULT_ALLOWED_ACTOR)
    args = parser.parse_args(argv)

    try:
        event = _load_event(args.event)
        pull_request = event.get("pull_request")
        if not isinstance(pull_request, Mapping):
            raise ValueError("event carries no pull_request record")
        pr_number = pull_request.get("number")
        if type(pr_number) is not int or isinstance(pr_number, bool) or pr_number < 1:
            raise ValueError("event pull_request number must be a positive integer")
        head = pull_request.get("head")
        if not isinstance(head, Mapping):
            raise ValueError("event pull_request carries no head record")
        head_sha = head.get("sha")
        head_branch = head.get("ref")
        head_repo = head.get("repo")
        head_repository = head_repo.get("full_name") if isinstance(head_repo, Mapping) else None
        if type(head_sha) is not str or not head_sha.strip():
            raise ValueError("event pull_request head sha must be non-empty exact text")
        if type(head_branch) is not str or not head_branch.strip():
            raise ValueError("event pull_request head ref must be non-empty exact text")
        if type(head_repository) is not str or not _REPOSITORY_RE.match(head_repository):
            raise ValueError("event pull_request head repo must be exact owner/name text")
        issue_number = args.issue_number
        if issue_number is None:
            issue_number = _linked_issue_from_pr_body(pull_request.get("body"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        code = str(exc) if str(exc) in (ISSUE_LINK_MISSING, ISSUE_LINK_AMBIGUOUS) else EVENT_INVALID
        decision = GateDecision(False, code, detail=str(exc) if code == EVENT_INVALID else "")
        print(json.dumps(decision.as_dict(), sort_keys=True))
        return 1

    reader = PaginatedIssueCommentReader(token_provider=_EnvTokenProvider())
    decision = run_gate(
        reader=reader,
        repository=args.repository,
        issue_number=issue_number,
        pr_number=pr_number,
        allowed_actor=args.allowed_actor,
        head_repository=head_repository,
        head_branch=head_branch,
        head_sha=head_sha,
    )
    print(json.dumps(decision.as_dict(), sort_keys=True))
    return 0 if decision.admitted else 1


if __name__ == "__main__":
    sys.exit(main())
