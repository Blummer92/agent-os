"""JSON and human-readable report rendering for a reconciliation plan."""

from __future__ import annotations

import json
from typing import Any

from .plan import ReconciliationPlan


def plan_to_dict(plan: ReconciliationPlan) -> dict[str, Any]:
    return {
        "dry_run": plan.dry_run,
        "zero_write_confirmed": plan.zero_write_confirmed,
        "total_source_records": plan.total_source_records,
        "summary": {
            "update_existing": plan.update_existing,
            "create_missing": plan.create_missing,
            "duplicate_id": plan.duplicate_id,
            "malformed_identity": plan.malformed_identity,
            "contradictory_record": plan.contradictory_record,
            "excluded": plan.excluded,
        },
        "entries": [
            {
                "source_row": entry.source_row,
                "result": entry.result.value,
                "identity_key": entry.identity_key,
                "matched_page_ids": list(entry.matched_page_ids),
                "reason": entry.reason,
                "preserved_fields": entry.preserved_fields,
            }
            for entry in plan.entries
        ],
    }


def plan_to_json(plan: ReconciliationPlan, *, indent: int = 2) -> str:
    return json.dumps(plan_to_dict(plan), indent=indent, sort_keys=False)


def plan_to_summary(plan: ReconciliationPlan) -> str:
    lines = [
        "Visual Asset Reconciliation Plan (dry run — zero external writes)",
        f"Total source records: {plan.total_source_records}",
        f"  UPDATE_EXISTING:      {plan.update_existing}",
        f"  CREATE_MISSING:       {plan.create_missing}",
        f"  DUPLICATE_ID:         {plan.duplicate_id}",
        f"  MALFORMED_IDENTITY:   {plan.malformed_identity}",
        f"  CONTRADICTORY_RECORD: {plan.contradictory_record}",
        f"  EXCLUDED:             {plan.excluded}",
    ]
    return "\n".join(lines)
