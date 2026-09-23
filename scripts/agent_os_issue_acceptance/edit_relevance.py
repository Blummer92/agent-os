from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_EXACT_HEAD_ACCEPTANCE_EVIDENCE_LINE_RE = re.compile(
    r"^[ \t]*(?:[-*][ \t]+)?Exact-head[ \t]+`?Agent OS Issue Acceptance Report`?"
    r"[ \t]*:[ \t]*\*\*[^*\n]+\*\*[ \t]+on[ \t]+`?[0-9a-fA-F]{7,40}`?\.?[ \t]*$"
)


def normalize_acceptance_pr_body(body: str) -> str:
    """Remove only canonical exact-head acceptance evidence from trigger comparison."""
    if type(body) is not str:
        raise TypeError("body must be a string")

    kept = [
        line.rstrip()
        for line in body.splitlines()
        if not _EXACT_HEAD_ACCEPTANCE_EVIDENCE_LINE_RE.fullmatch(line)
    ]
    normalized = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", normalized)


def classify_acceptance_event(payload: dict[str, Any]) -> tuple[bool, str]:
    """Return whether a workflow event can change acceptance-report inputs."""
    if type(payload) is not dict:
        raise TypeError("payload must be a dict")

    if payload.get("action") != "edited":
        return True, "non-edited-event"

    changes = payload.get("changes")
    if not isinstance(changes, dict):
        return True, "edited-event-missing-changes"

    if "title" in changes:
        return True, "title-changed"
    if "base" in changes:
        return True, "base-changed"
    if "body" not in changes:
        return False, "edited-without-consumed-field"

    body_change = changes.get("body")
    old_body = body_change.get("from", "") if isinstance(body_change, dict) else ""
    pull_request = payload.get("pull_request")
    new_body = pull_request.get("body", "") if isinstance(pull_request, dict) else ""
    old_body = old_body or ""
    new_body = new_body or ""

    if normalize_acceptance_pr_body(old_body) == normalize_acceptance_pr_body(new_body):
        return False, "acceptance-evidence-only-body-edit"
    return True, "body-input-changed"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit(
            "usage: python -m scripts.agent_os_issue_acceptance.edit_relevance <event-json>"
        )

    payload = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    should_run, reason = classify_acceptance_event(payload)
    print(f"should_run={'true' if should_run else 'false'}")
    print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
