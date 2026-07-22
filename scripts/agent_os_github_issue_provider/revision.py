from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

_REVISION_FIELDS = (
    "number",
    "title",
    "state",
    "body",
    "html_url",
    "created_at",
    "updated_at",
    "closed_at",
    "state_reason",
)


def canonical_issue_payload(item: Mapping[str, object]) -> bytes:
    missing = [field for field in _REVISION_FIELDS[:7] if field not in item]
    if missing:
        raise ValueError("missing revision field(s): " + ", ".join(missing))
    labels = item.get("labels")
    if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
        raise ValueError("labels must be a sequence")
    label_names: list[str] = []
    for label in labels:
        value = label.get("name") if isinstance(label, Mapping) else label
        if not isinstance(value, str) or not value.strip():
            raise ValueError("label names must be non-empty strings")
        label_names.append(value)
    normalized = {field: item.get(field) for field in _REVISION_FIELDS}
    normalized["body"] = "" if normalized["body"] is None else normalized["body"]
    normalized["labels"] = sorted(label_names)
    normalized["is_pull_request"] = "pull_request" in item
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def issue_source_revision(item: Mapping[str, object]) -> str:
    digest = hashlib.sha256(canonical_issue_payload(item)).hexdigest()
    return f"github-issue-v1:{digest}"
