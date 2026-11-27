"""Offline CKR v2 regression fixtures (from the 2026-11-25 adversarial review).

Nothing here talks to a network. Every fake sits at an I/O seam only:
  * notion_row(...)          -> one Notion-API-shaped page dict for normalize_lesson_row
  * PagedNotion              -> a read executor (query -> page) with optional mid-read mutation
  * FakeGitHub               -> GitHubTransport; its CKR6 "producer" runs the REAL bridge
                                (parse_envelope, classify_envelope, execute_envelope,
                                serialize_ckr6_result_comment) with an injected Notion reader
  * RecordingProvider        -> ProviderBackend that records the exact prompt bytes it receives
  * FakeClock                -> deterministic clock; sleep() advances it
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping


def notion_row(n: int, *, title: str, area: str = "Testing", learning_type: str = "Testing lesson",
               applies_to: tuple[str, ...] = (), next_time: str = "Do the documented thing.",
               guardrail: str = "Keep the documented guard.", status: str = "Applied",
               surface: bool = True, source_link: str | None = "https://github.com/Blummer92/agent-os/pull/1",
               revision: str = "2026-11-20T10:00:00.000Z", lesson_id_prefix: str = "LL") -> dict:
    props: dict[str, Any] = {
        "Lesson ID": {"type": "unique_id", "unique_id": {"prefix": lesson_id_prefix, "number": n}},
        "Lesson Learned": {"type": "title", "title": [{"plain_text": title}]},
        "Status": {"type": "select", "select": {"name": status}},
        "Surface Before Work?": {"type": "checkbox", "checkbox": surface},
        "Area": {"type": "select", "select": {"name": area}},
        "Learning Type": {"type": "select", "select": {"name": learning_type}},
        "Applies To": {"type": "multi_select", "multi_select": [{"name": a} for a in applies_to]},
        "What To Do Next Time": {"type": "rich_text", "rich_text": [{"plain_text": next_time}]},
        "Guardrail": {"type": "rich_text", "rich_text": [{"plain_text": guardrail}]},
    }
    if source_link is not None:
        props["Source Link"] = {"type": "url", "url": source_link}
    return {"object": "page", "id": str(uuid.UUID(int=n)), "last_edited_time": revision,
            "url": f"https://www.notion.so/lesson-{n}", "properties": props}


class PagedNotion:
    """Read executor over a mutable row list. Honors the base Surface/Status filter
    (as the live provider is asked to) unless honor_filter=False. Pages are cut by
    POSITION (offset cursor) so a deletion between pages shifts later rows."""

    def __init__(self, rows: list[dict], *, page_size: int = 100, honor_filter: bool = True,
                 on_page: Callable[["PagedNotion", int], None] | None = None) -> None:
        self.rows = rows
        self.page_size = page_size
        self.honor_filter = honor_filter
        self.on_page = on_page
        self.queries: list[dict] = []

    def _visible(self) -> list[dict]:
        if not self.honor_filter:
            return list(self.rows)
        out = []
        for row in self.rows:
            props = row.get("properties", {})
            surface = props.get("Surface Before Work?", {}).get("checkbox")
            status = (props.get("Status", {}).get("select") or {}).get("name")
            if surface is True and status != "Archived note":
                out.append(row)
        return out

    def __call__(self, query: Mapping[str, Any]) -> dict:
        self.queries.append(dict(query))
        page_index = len(self.queries) - 1
        if "filter" in query and isinstance(query["filter"], dict):
            pass  # relevance OR-clauses are ignored: the snapshot query has none (broad request)
        start = int(query.get("start_cursor", "0") or 0)
        size = min(int(query.get("page_size", self.page_size)), self.page_size)
        visible = self._visible()
        page = visible[start:start + size]
        more = start + size < len(visible)
        result = {"object": "list", "results": page, "has_more": more,
                  "next_cursor": str(start + size) if more else None}
        if self.on_page is not None:
            self.on_page(self, page_index)
        return result


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RecordingProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"model-output-{len(self.prompts)}"

    def stream(self, prompt: str):
        self.prompts.append(prompt)
        yield "chunk-1"
        yield "chunk-2"


class FakeGitHub:
    """In-memory GitHubTransport. The CKR6 producer is the REAL bridge code.

    producer_delay_s: simulated workflow latency between request creation and result post.
    notion: read executor injected at bridge.resolve_lesson_read_route (the only patched seam).
    forger: optional callable(request_record) -> list[(body, delay_s)] of extra bot comments.
    """

    def __init__(self, bridge, clock: FakeClock, *, repository: str, request_login: str,
                 notion: Callable | None, producer_delay_s: float = 45.0,
                 forger: Callable[[dict], list[tuple[str, float]]] | None = None,
                 producer_enabled: bool = True) -> None:
        self.bridge = bridge
        self.clock = clock
        self.repository = repository
        self.request_login = request_login
        self.notion = notion
        self.producer_delay_s = producer_delay_s
        self.forger = forger
        self.producer_enabled = producer_enabled
        self.comments: list[dict] = []
        self.next_id = 7_000_000_000
        self.pending: list[tuple[datetime, dict]] = []  # (post_time, record)
        self.posts = 0
        self.producer_runs: list[dict] = []

    # -- record helpers
    def _record(self, issue: int, body: str, login: str, uid: int, created: datetime,
                app: str | None = None) -> dict:
        self.next_id += 1
        cid = self.next_id
        rec = {
            "id": cid, "body": body, "user": {"login": login, "id": uid,
                                                 "type": "Bot" if login.endswith("[bot]") else "User"},
            "created_at": iso(created), "updated_at": iso(created),
            "issue_url": f"https://api.github.com/repos/{self.repository}/issues/{issue}",
            "html_url": f"https://github.com/{self.repository}/issues/{issue}#issuecomment-{cid}",
            "_issue": issue,
        }
        if app:
            rec["performed_via_github_app"] = {"slug": app}
        return rec

    def _run_producer(self, request_rec: dict) -> str:
        bridge = self.bridge
        payload = json.loads(request_rec["body"][len(bridge.COMMAND_PREFIX):])
        envelope = bridge.parse_envelope(payload)
        required = bool(bridge.classify_envelope(envelope)["retrieval_required"])

        class _Route:
            reason_code = "fixture-route"
            execute_read = self.notion

        original = bridge.resolve_lesson_read_route
        bridge.resolve_lesson_read_route = lambda: _Route()  # injected Notion reader (I/O seam only)
        try:
            result = bridge.execute_envelope(envelope, retrieval_required=required)
        finally:
            bridge.resolve_lesson_read_route = original
        self.producer_runs.append({"retrieval_required": required, "status": result.get("status"),
                                   "selected": result.get("selected_lesson_ids")})
        return bridge.serialize_ckr6_result_comment(result, request_comment_id=request_rec["id"])

    # -- GitHubTransport protocol
    def post_issue_comment(self, repository: str, issue_number: int, body: str) -> int:
        self.posts += 1
        rec = self._record(issue_number, body, self.request_login, 9_000_001, self.clock())
        self.comments.append(rec)
        if self.producer_enabled:
            self.pending.append((self.clock() + timedelta(seconds=self.producer_delay_s), {"kind": "result", "req": rec}))
        if self.forger is not None:
            for forged_body, delay in self.forger(rec):
                self.pending.append((self.clock() + timedelta(seconds=delay), {"kind": "forged", "body": forged_body, "req": rec}))
        return rec["id"]

    def _flush(self) -> None:
        now = self.clock()
        due = sorted([p for p in self.pending if p[0] <= now], key=lambda p: p[0])
        self.pending = [p for p in self.pending if p[0] > now]
        for when, item in due:
            req = item["req"]
            body = self._run_producer(req) if item["kind"] == "result" else item["body"]
            rec = self._record(req["_issue"], body, self.bridge.CKR6_PRODUCER_LOGIN,
                               self.bridge.CKR6_PRODUCER_ACCOUNT_ID, when, app="github-actions")
            self.comments.append(rec)

    def get_issue_comment(self, repository: str, comment_id: int) -> Mapping[str, Any]:
        for rec in self.comments:
            if rec["id"] == comment_id:
                return {k: v for k, v in rec.items() if not k.startswith("_")}
        raise LookupError("not found")

    def list_issue_comments(self, repository: str, issue_number: int):
        self._flush()
        return [{k: v for k, v in rec.items() if not k.startswith("_")}
                for rec in self.comments if rec["_issue"] == issue_number]
