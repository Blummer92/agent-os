"""Durable at-most-once create admission, independent of Notion query indexing.

GitHub's create-ref operation is an atomic, create-only reservation for one
reviewed lesson title. It is deliberately never released automatically. A lost
Notion response or GitHub response must not permit a second POST. No Notion
credentials are used by this module; no GitHub data is returned as evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import urllib.error
import urllib.request

from .admission import REPOSITORY, WriteBlocked
from .catalog import entry_for, lesson_for

REF_PREFIX = "refs/tags/agent-os-notion-create-once-v1/"
MAX_REPLY_BYTES = 4096


def reservation_ref(request_id: str) -> str:
    """Same reviewed title -> same immutable reservation, across request IDs."""
    entry = entry_for(request_id)
    if entry["target_lesson_id"] is not None:
        raise WriteBlocked("create-reservation-not-applicable")
    title = lesson_for(request_id)["Lesson Learned"]
    if type(title) is not str or not title:
        raise WriteBlocked("create-reservation-invalid")
    key = unicodedata.normalize("NFKC", title).strip().casefold()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return REF_PREFIX + digest


def reserve_once(request_id: str, *, token: str | None = None,
                 commit_sha: str | None = None, opener=None) -> None:
    """Atomically reserve exactly one Notion create, or refuse before POST.

    The fixed GitHub repository is the durable namespace. A 422 means the
    reference already exists (or is invalid): either case must fail closed.
    Other network/permission failures also refuse the Notion mutation.
    Never query-then-create the ref: that would reintroduce a race.
    """
    ref = reservation_ref(request_id)
    token = os.environ.get("GITHUB_TOKEN", "") if token is None else token
    commit_sha = os.environ.get("GITHUB_SHA", "") if commit_sha is None else commit_sha
    if type(token) is not str or not token.strip():
        raise WriteBlocked("create-reservation-credential-unavailable")
    if type(commit_sha) is not str or re.fullmatch(r"[0-9a-fA-F]{40}", commit_sha) is None:
        raise WriteBlocked("create-reservation-commit-unavailable")
    from .live import _NoRedirect
    url = "https://api.github.com/repos/" + REPOSITORY + "/git/refs"
    payload = json.dumps({"ref": ref, "sha": commit_sha}).encode("utf-8")
    request = urllib.request.Request(
        url, method="POST", data=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "agent-os-notion-create-reservation",
        },
    )
    try:
        transport = opener if opener is not None else urllib.request.build_opener(_NoRedirect())
        with transport.open(request, timeout=15) as response:
            if response.status != 201:
                raise WriteBlocked("create-reservation-unavailable")
            raw = response.read(MAX_REPLY_BYTES + 1)
        if len(raw) > MAX_REPLY_BYTES:
            raise WriteBlocked("create-reservation-unavailable")
        receipt = json.loads(raw)
        if (not isinstance(receipt, dict) or receipt.get("ref") != ref
                or receipt.get("object", {}).get("sha") != commit_sha):
            # A 201 could have committed the ref even when its receipt is
            # malformed. Fail closed: NEVER attempt a Notion POST.
            raise WriteBlocked("create-reservation-unconfirmed")
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            raise WriteBlocked("create-reservation-already-exists") from None
        raise WriteBlocked("create-reservation-unavailable") from None
    except WriteBlocked:
        raise
    except Exception:
        raise WriteBlocked("create-reservation-unavailable") from None
