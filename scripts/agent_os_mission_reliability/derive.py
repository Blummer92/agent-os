"""Validate normalized records and compose the pure #2766 metric projections."""

from collections.abc import Mapping, Sequence
from typing import Any

from .delivery_metrics import delivery
from .errors import ValidationError
from .inputs import positive_issue, valid_timestamp
from .lifecycle_metrics import lifecycle
from .outcome_metrics import finite_requests, learning
from .progress_metrics import completion, interaction

SCHEMA_VERSION = "2766-mission-reliability.v1"

# Normalized mission record fields consumed by derive_mission_reliability().
# All timestamps are ISO-8601 UTC strings (e.g. "2026-09-22T02:04:54Z").
#
# {
#   "issue_number": int,                       # required
#   "admitted": bool,                          # admitted mission in the frozen window
#   "admitted_at": str | None,                 # mission admission timestamp
#   "issue_state": "open" | "closed" | "unknown",
#   "issue_closed_at": str | None,
#   "implementation_prs": [                    # linked implementation PRs, oldest first
#       {"number": int, "created_at": str, "merged": bool,
#        "merged_at": str | None, "repair": bool,
#        "first_terminal_validation_at": str | None}
#   ],
#   "requested_items": int | None,             # finite mission requested count
#   "delivered_items": int | None,             # finite mission delivered count
#   "terminal_state": "completed_truthful" | "blocked_systemic" |
#                     "blocked_item_local" | "intermediate_stop" | "unknown",
#   "user_interventions": int | None,         # None = no durable evidence
#   "continuation_prompts": int | None,       # None = unknown (do not infer)
#   "bug_family": str | None,
#   "prior_completed_fix_issue": int | None,
#   "finding_issue": int | None,
#   "retest_at": str | None,
# }

_TERMINAL_STATES = frozenset({
    "completed_truthful", "blocked_systemic", "blocked_item_local", "intermediate_stop", "unknown",
})


def _validate_records(records):
    """Validate exact issue identity, admission evidence, and normalized row shape."""
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)) or not records:
        raise ValidationError("invalid_records", "Expected nonempty mission records.", "report")
    seen = set()
    for record in records:
        if not isinstance(record, Mapping) or not positive_issue(record.get("issue_number")):
            raise ValidationError("invalid_record", "Mission record needs an exact issue number.", "report")
        number = record["issue_number"]
        if number in seen:
            raise ValidationError("duplicate_record", "Mission records repeat an issue.", "report")
        seen.add(number)
        state = record.get("terminal_state", "unknown")
        if type(state) is not str or state not in _TERMINAL_STATES:
            raise ValidationError("invalid_terminal_state", "Invalid mission terminal state.", "report")
        prs = record.get("implementation_prs")
        if prs is not None and (not isinstance(prs, list) or not all(isinstance(pr, Mapping) for pr in prs)):
            raise ValidationError("invalid_pr_records", "Expected a list of implementation PR objects.", "report")
        flag = record.get("admitted", False)
        if type(flag) is not bool or (flag and not valid_timestamp(record.get("admitted_at"))):
            raise ValidationError("invalid_admission", "Admitted records need an exact flag and ISO timestamp.", "report")


def derive_mission_reliability(records: Sequence[Mapping[str, Any]], *, window: str) -> dict[str, Any]:
    """Project a named population into evidence-honest metrics, without I/O or mutation."""
    if type(window) is not str or not window.strip():
        raise ValidationError("invalid_window", "Expected a nonempty window label.", "report")
    _validate_records(records)
    admitted = [record for record in records if record.get("admitted") is True]
    metrics = (
        completion(records, admitted, window) + interaction(admitted, window)
        + delivery(admitted, window) + lifecycle(admitted, window)
        + finite_requests(admitted, window) + learning(admitted, window)
    )
    return {
        "schema_version": SCHEMA_VERSION, "issue": 2766, "window": window,
        "records_considered": len(records), "admitted": len(admitted), "metrics": metrics,
    }
