"""CKR11 stage-1 read-only retrieval-shape probe (PROPOSED, NOT PUBLISHED, NOT RUN).

Runs a fixed, finite manifest of Lessons Learned data-source queries through the
canonical NotionReadOnlyAdapter, one page each, and writes only counts and
booleans. It never follows a cursor, never retries, never sends more than the
manifest length (hard cap 16) HTTP requests, and never writes to Notion.

Owner decision binding: 2026-11-15 18:30 (page_size 26, max_pages 1,
max_results 100, <= 16 queries, no cursor follow, no retry, sanitized output).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

from workflow_scheduler.adapters.notion_readonly_adapter import (
    NOTION_API_BASE,
    NotionReadOnlyAdapter,
    _default_http_post_read,
)
from workflow_scheduler.models import Task

SCHEMA = "ckr11-stage1-probe-result/v1"
PAGE_SIZE = 26
MAX_PAGES = 1
MAX_RESULTS = 100
HARD_CALL_CAP = 16

# Pinned literal copies. A unit test compares each to the production source
# (lesson_activation_bridge) so drift fails closed instead of being followed.
AREAS = ("Automation", "Curriculum", "Dashboard", "Documentation", "Governance", "Testing")
LEARNING_TYPES = (
    "Deployment lesson",
    "Mistake",
    "QA feedback",
    "Scope/permission lesson",
    "Testing lesson",
    "Trigger lesson",
)
BASE = (
    {"property": "Surface Before Work?", "checkbox": {"equals": True}},
    {"property": "Status", "select": {"does_not_equal": "Archived note"}},
)


def _area(value: str) -> dict[str, Any]:
    return {"property": "Area", "select": {"equals": value}}


def _learning_type(value: str) -> dict[str, Any]:
    return {"property": "Learning Type", "select": {"equals": value}}


def _query(*extra: Mapping[str, Any]) -> dict[str, Any]:
    return {"and": [dict(item) for item in BASE] + [dict(item) for item in extra]}


def _build_manifest() -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = [
        {"code": "V00_base", "filter": _query(), "provenance": ["base filter of build_filtered_query"]}
    ]
    for index, area in enumerate(AREAS, start=1):
        provenance = ["Area vocabulary: _AREA_ECOSYSTEM key"]
        if area == "Testing":
            provenance.append("first-step query of #3972 (request 6902370485), identical filter")
            provenance.append("first-step query of #3988 (request 6902241927), identical filter")
        entries.append(
            {"code": f"V{index:02d}_area_{area.lower()}", "filter": _query(_area(area)), "provenance": provenance}
        )
    for index, learning_type in enumerate(LEARNING_TYPES, start=7):
        slug = re.sub(r"[^a-z]+", "_", learning_type.lower()).strip("_")
        entries.append(
            {
                "code": f"V{index:02d}_type_{slug}",
                "filter": _query(_learning_type(learning_type)),
                "provenance": ["Learning Type vocabulary: _LEARNING_TYPE_CAPABILITY key"],
            }
        )
    entries.append(
        {
            "code": "V13_prod_3991_or",
            "filter": _query({"or": [_area("Testing"), _area("Automation"), _area("Dashboard")]}),
            "provenance": ["first-step query of #3991 (request 6902018616), page_size aside"],
        }
    )
    return tuple(entries)


MANIFEST = _build_manifest()
assert 1 <= len(MANIFEST) <= HARD_CALL_CAP
assert len({json.dumps(e["filter"], sort_keys=True) for e in MANIFEST}) == len(MANIFEST)


def manifest_sha256(manifest: tuple[dict[str, Any], ...] = MANIFEST) -> str:
    payload = json.dumps(
        {"page_size": PAGE_SIZE, "max_pages": MAX_PAGES, "max_results": MAX_RESULTS, "entries": list(manifest)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


MANIFEST_SHA256 = manifest_sha256()

STOP_REASONS = (
    "http_429",
    "http_5xx",
    "http_4xx",
    "timeout",
    "connection_error",
    "malformed_response",
    "oversized_page",
    "request_contract_violation",
    "call_cap",
)
REFUSALS = (
    "run_attempt_not_first",
    "output_exists",
    "manifest_hash_mismatch",
    "missing_credential",
    "missing_source_binding",
    "unsafe_artifact",
)


class ProbeStop(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ProbeRefusal(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _no_get(*_args: Any, **_kwargs: Any) -> Any:
    raise ProbeStop("request_contract_violation")


class _Transport:
    """The only network path. Validates each request, counts it, reads counts only."""

    def __init__(self, data_source_id: str, post: Callable[..., Any], cap: int) -> None:
        self._url = f"{NOTION_API_BASE}/data_sources/{data_source_id}/query"
        self._post = post
        self._cap = cap
        self.calls = 0
        self.expected_filter: Any = None
        self.last: dict[str, Any] | None = None

    def __call__(self, url: str, headers: dict[str, str], body: dict[str, Any], timeout: float) -> Any:
        if url != self._url:
            raise ProbeStop("request_contract_violation")
        if set(body) != {"page_size", "filter"} or body["page_size"] != PAGE_SIZE:
            raise ProbeStop("request_contract_violation")
        if body["filter"] != self.expected_filter:
            raise ProbeStop("request_contract_violation")
        if self.calls >= self._cap:
            raise ProbeStop("call_cap")
        self.calls += 1
        try:
            response = self._post(url, headers, body, timeout)
        except ProbeStop:
            raise
        except Exception as exc:  # class and numeric status only, never the message text
            raise ProbeStop(_classify_failure(exc)) from None
        results = response.get("results") if isinstance(response, dict) else None
        has_more = response.get("has_more") if isinstance(response, dict) else None
        if not isinstance(results, list) or not isinstance(has_more, bool):
            raise ProbeStop("malformed_response")
        cursor = response.get("next_cursor")
        self.last = {
            "raw_count": len(results),
            "has_more": has_more,
            "cursor_present": isinstance(cursor, str) and bool(cursor),
        }
        return response


def _classify_failure(exc: BaseException) -> str:
    text = str(exc)
    match = re.search(r"HTTP (\d{3})", text)
    if match:
        status = int(match.group(1))
        if status == 429:
            return "http_429"
        if 500 <= status <= 599:
            return "http_5xx"
        return "http_4xx"
    if "timed out" in text.lower():
        return "timeout"
    return "connection_error"


def _count_class(returned: int, has_more: bool, anomaly: bool) -> str:
    if anomaly:
        return "unknown"
    if has_more:
        return "26+" if returned >= 26 else "unknown"
    if returned == 0:
        return "0"
    return "1..25" if returned <= 25 else "26+"


def run_probe(
    *,
    data_source_id: str,
    token: str,
    post: Callable[..., Any] = _default_http_post_read,
    manifest: tuple[dict[str, Any], ...] = MANIFEST,
) -> dict[str, Any]:
    cap = min(HARD_CALL_CAP, len(manifest))
    transport = _Transport(data_source_id, post, cap)
    adapter = NotionReadOnlyAdapter(token=token, http_get=_no_get, http_post_query_data_source=transport)
    variants: list[dict[str, Any]] = []
    stop_reason: str | None = None
    for entry in manifest:
        if stop_reason is not None:
            variants.append(_row(entry["code"], "not_run"))
            continue
        transport.expected_filter = entry["filter"]
        transport.last = None
        task = Task(
            id="ckr11-stage1-probe",
            workflow_id="ckr11-stage1-probe",
            type="read:notion",
            owner="ckr11-stage1-probe",
            action="query_data_source",
            idempotency_key="ckr11-stage1-probe",
            payload={
                "action": "query_data_source",
                "data_source_id": data_source_id,
                "page_size": PAGE_SIZE,
                "max_pages": MAX_PAGES,
                "max_results": MAX_RESULTS,
                "filter": entry["filter"],
            },
        )
        try:
            result = adapter.execute(task)
            observed = transport.last
            if result.get("status") != "success" or observed is None:
                raise ProbeStop("malformed_response")
        except ProbeStop as stop:
            stop_reason = stop.reason
            variants.append(_row(entry["code"], "error"))
            continue
        returned = observed["raw_count"]
        anomaly = returned > PAGE_SIZE
        row = _row(entry["code"], "completed")
        row.update(
            {
                "returned_count": returned,
                "has_more": observed["has_more"],
                "next_cursor_present": observed["cursor_present"],
                "page_size_anomaly": anomaly,
                "count_class": _count_class(returned, observed["has_more"], anomaly),
                "count_exact": (not observed["has_more"]) and not anomaly,
            }
        )
        variants.append(row)
        if anomaly:
            stop_reason = "oversized_page"
    return {
        "schema": SCHEMA,
        "manifest_sha256": manifest_sha256(manifest),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_revision": _source_revision(),
        "page_size": PAGE_SIZE,
        "max_pages": MAX_PAGES,
        "max_results": MAX_RESULTS,
        "call_cap": HARD_CALL_CAP,
        "http_calls": transport.calls,
        "cursor_follow_calls": 0,
        "notion_writes_performed": False,
        "stopped": stop_reason is not None,
        "stop_reason": stop_reason,
        "variants": variants,
    }


def _row(code: str, status: str) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "returned_count": None,
        "has_more": None,
        "next_cursor_present": None,
        "page_size_anomaly": False,
        "count_class": "unknown",
        "count_exact": False,
    }


def _source_revision() -> str | None:
    value = os.environ.get("GITHUB_SHA", "")
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


_ROW_KEYS = {
    "code", "status", "returned_count", "has_more", "next_cursor_present",
    "page_size_anomaly", "count_class", "count_exact",
}
_TOP_KEYS = {
    "schema", "manifest_sha256", "script_sha256", "source_revision", "page_size", "max_pages",
    "max_results", "call_cap", "http_calls", "cursor_follow_calls", "notion_writes_performed",
    "stopped", "stop_reason", "variants",
}
_FORBIDDEN = (
    re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])"),
    re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    re.compile(r"notion\.so|secret_|ntn_|https?://|Bearer|next_cursor\"\s*:\s*\"", re.I),
)


def validate_result(result: Mapping[str, Any], *, secrets: tuple[str, ...] = ()) -> str:
    """Strict schema and content gate. Returns the serialized artifact or raises."""
    if set(result) != _TOP_KEYS or result["schema"] != SCHEMA:
        raise ProbeRefusal("unsafe_artifact")
    if result["stop_reason"] is not None and result["stop_reason"] not in STOP_REASONS:
        raise ProbeRefusal("unsafe_artifact")
    if not isinstance(result["variants"], list) or len(result["variants"]) > HARD_CALL_CAP:
        raise ProbeRefusal("unsafe_artifact")
    allowed_codes = {entry["code"] for entry in MANIFEST}
    for row in result["variants"]:
        if set(row) != _ROW_KEYS or row["code"] not in allowed_codes:
            raise ProbeRefusal("unsafe_artifact")
        if row["status"] not in {"completed", "error", "not_run"}:
            raise ProbeRefusal("unsafe_artifact")
        if row["count_class"] not in {"0", "1..25", "26+", "unknown"}:
            raise ProbeRefusal("unsafe_artifact")
        for key in ("has_more", "next_cursor_present"):
            if row[key] is not None and not isinstance(row[key], bool):
                raise ProbeRefusal("unsafe_artifact")
        count = row["returned_count"]
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > MAX_RESULTS):
            raise ProbeRefusal("unsafe_artifact")
    text = json.dumps(result, sort_keys=True, indent=1) + "\n"
    if any(pattern.search(text) for pattern in _FORBIDDEN):
        raise ProbeRefusal("unsafe_artifact")
    if any(secret and secret in text for secret in secrets):
        raise ProbeRefusal("unsafe_artifact")
    return text


def main(argv: list[str] | None = None, *, post: Callable[..., Any] = _default_http_post_read) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
        if attempt is not None and attempt != "1":
            raise ProbeRefusal("run_attempt_not_first")
        output = Path(args.output)
        if output.exists():
            raise ProbeRefusal("output_exists")
        if args.expected_manifest_sha256 != MANIFEST_SHA256:
            raise ProbeRefusal("manifest_hash_mismatch")
        token = os.environ.get("NOTION_TOKEN", "")
        if not token.strip():
            raise ProbeRefusal("missing_credential")
        source = os.environ.get("AGENT_OS_LESSONS_LEARNED_DATA_SOURCE_ID", "").strip()
        if not source:
            raise ProbeRefusal("missing_source_binding")
        result = run_probe(data_source_id=source, token=token, post=post)
        text = validate_result(result, secrets=(token, source))
        output.write_text(text, encoding="utf-8")
        print(f"ckr11-stage1-probe calls={result['http_calls']} stopped={result['stopped']} reason={result['stop_reason']}")
        return 1 if result["stopped"] else 0
    except ProbeRefusal as refusal:
        print(f"ckr11-stage1-probe refused: {refusal.reason}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
