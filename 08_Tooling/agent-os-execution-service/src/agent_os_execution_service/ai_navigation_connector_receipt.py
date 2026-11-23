"""Bounded, read-only GitHub connector retrieval adapter for AI Navigation (#3970).

The host MUST supply trusted GitHub connector callbacks; untrusted callbacks
cannot authenticate a run. The existing pure validator owns receipt checks.
This module does not trigger Actions, dispatch execution, or mutate GitHub.
It preserves authentic=False: matching run/artifact data is not an attestation
that the callbacks were supplied by a trusted host.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from .ai_navigation_receipt_retrieval import (
    select_artifact, validate_retrieved_receipt, validate_run_metadata,
)

REPOSITORY = "Blummer92/agent-os"
PAGE_SIZE = 100
MAX_PAGES = 10
_SHA = re.compile(r"[0-9a-f]{40}", re.ASCII)


def _stop(reason: str, *, rejected: bool = False) -> dict[str, Any]:
    return {"status": "rejected" if rejected else "blocked",
            "reason": reason, "authentic": False}


def _read(fetch: Callable[[str], object], url: str) -> Mapping[str, Any] | None:
    try:
        data = fetch(url)
    except Exception:
        return None
    return data if isinstance(data, Mapping) else None


def retrieve_and_validate_connector_receipt(
    *, expected_binding: Mapping[str, Any],
    fetch_json: Callable[[str], object],
    download_zip: Callable[[int], object],
) -> dict[str, Any]:
    """Fetch an exact run, every artifact page, and one named ZIP.

    The host binds fetch_json to its authenticated GitHub API GET tool and
    download_zip to a ZIP-bytes materializer for the artifact returned by
    GitHub. Passing a user-supplied callback does not establish provenance.
    """
    run_id = expected_binding.get("run_id")
    attempt = expected_binding.get("run_attempt")
    sha = expected_binding.get("source_sha")
    if (expected_binding.get("repository") != REPOSITORY
            or type(run_id) is not int or run_id < 1
            or type(attempt) is not int or attempt < 1
            or type(sha) is not str or _SHA.fullmatch(sha) is None):
        return _stop("expected-binding-malformed", rejected=True)

    api = "https://api.github.com/repos/" + REPOSITORY
    run = _read(fetch_json, f"{api}/actions/runs/{run_id}")
    if run is None:
        return _stop("github-run-read-unavailable")
    ok, reason = validate_run_metadata(
        run, run_id=run_id, run_attempt=attempt,
        head_sha=sha, repository=REPOSITORY,
    )
    if not ok:
        return _stop(reason, rejected=reason != "blocked-by-workflow-run-metadata")

    items: list[Mapping[str, Any]] = []
    total: int | None = None
    for page in range(1, MAX_PAGES + 1):
        url = f"{api}/actions/runs/{run_id}/artifacts?per_page={PAGE_SIZE}&page={page}"
        response = _read(fetch_json, url)
        if response is None:
            return _stop("artifact-page-read-unavailable")
        current_total, batch = response.get("total_count"), response.get("artifacts")
        if (type(current_total) is not int or current_total < 0
                or current_total > PAGE_SIZE * MAX_PAGES
                or not isinstance(batch, list) or len(batch) > PAGE_SIZE
                or any(not isinstance(item, Mapping) for item in batch)):
            return _stop("artifact-listing-malformed", rejected=True)
        if total is None:
            total = current_total
        if current_total != total:
            return _stop("artifact-total-changed")
        if len(items) + len(batch) > total:
            return _stop("artifact-listing-overfull", rejected=True)
        items.extend(batch)
        if len(items) == total:
            break
        if len(batch) != PAGE_SIZE:
            return _stop("artifact-listing-incomplete")
    else:
        return _stop("artifact-listing-page-bound")

    ids = [item.get("id") for item in items]
    if any(type(i) is not int or i < 1 for i in ids) or len(ids) != len(set(ids)):
        return _stop("artifact-ids-invalid", rejected=True)

    listing = {"total_count": total, "artifacts": items}
    artifact, reason = select_artifact(
        listing, run_id=run_id, run_attempt=attempt, head_sha=sha,
    )
    if artifact is None:
        return _stop(reason, rejected=reason not in (
            "listing-missing", "listing-incomplete", "listing-completeness-unprovable",
        ))
    try:
        blob = download_zip(artifact["id"])
    except Exception:
        return _stop("artifact-download-unavailable")
    if type(blob) is not bytes:
        return _stop("artifact-bytes-unavailable")

    verdict = validate_retrieved_receipt(
        run_metadata=run, listing=listing, zip_bytes=blob,
        expected_binding=expected_binding,
    )
    return {**verdict, "authentic": False}
