"""Report exact-run GitHub job observations; never make a gate decision."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASELINE = (
    "Stop candidate while exact-current main recovery runs",
    "Project exact-current main health",
)
BOOTSTRAP = (
    "Verify aggregate checkout identity",
    "Recover missing exact-current main aggregate evidence",
    "Install validation dependencies",
)
UPLOAD = ("Upload branch coverage evidence", "Upload aggregate JUnit evidence")
BAD = {"failure", "timed_out", "action_required", "startup_failure"}
KNOWN = BAD | {"success", "cancelled", "skipped", "neutral", "stale"}
AGG = "Run aggregate validation"
CKR = "CKR6 mutation boundary gate"
MAX_BYTES = 2 * 1024 * 1024


def matching(rows, name):
    return [row for row in rows if type(row) is dict and row.get("name") == name]


def conclusion(row):
    value = row.get("conclusion")
    return (value if row.get("status") == "completed" and type(value) is str
            and value in KNOWN else "unavailable")


def records(payload, key):
    rows = payload.get(key) if type(payload) is dict else None
    if type(rows) is not list or type(payload.get("total_count")) is not int:
        raise ValueError("unsupported provider response")
    if len(rows) != payload["total_count"] or len(rows) > 100:
        raise ValueError("incomplete provider response")
    return rows


def observe(jobs, checks, *, head, run, attempt):
    if (type(head) is not str or not re.fullmatch(r"[a-f0-9]{40}", head)
            or type(run) is not int or type(attempt) is not int or min(run, attempt) < 1):
        raise ValueError("unverified run identity")
    listed = records(jobs, "jobs")
    if any(
        type(j) is not dict or type(j.get("run_id")) is not int
        or type(j.get("run_attempt")) is not int or j.get("run_id") != run or j.get("run_attempt") != attempt
        or j.get("head_sha") != head
        for j in listed
    ):
        raise ValueError("unverified job binding")
    aggregates = matching(listed, AGG)
    notes = []
    if len(aggregates) != 1:
        notes.append("Aggregate: unavailable (no unique aggregate job in this attempt).")
    elif conclusion(a := aggregates[0]) == "unavailable":
        notes.append("Aggregate: provider reports no completed aggregate job.")
    else:
        steps = a.get("steps")
        if type(steps) is not list:
            raise ValueError("unsupported step response")

        def state(name):
            rows = matching(steps, name)
            return conclusion(rows[0]) if len(rows) == 1 else "unavailable"

        executed = state(AGG)
        if executed == "unavailable" and conclusion(a) == "skipped":
            executed = "skipped"
        baseline_failures = [name for name in BASELINE if state(name) in BAD]
        failed = [name for name in BOOTSTRAP if state(name) in BAD]
        if executed == "success" and (baseline_failures or failed):
            raise ValueError("contradictory aggregate steps")
        if baseline_failures and executed == "skipped":
            notes.append("Main baseline: blocked before candidate aggregate execution.")
        elif baseline_failures:
            notes.append("Main baseline: setup or admission failed; candidate attribution is unverified.")
        if failed:
            notes.append("Infrastructure: " + "; ".join(failed) + " failed.")
        if executed in BAD:
            notes.append("Aggregate: execution step failed. Inspect JUnit and logs to distinguish a test failure from infrastructure.")
        elif executed == "success":
            notes.append("Aggregate: execution step succeeded; this report does not certify the result.")
        elif executed == "skipped":
            notes.append("Aggregate: execution skipped; no candidate test verdict.")
        else:
            notes.append("Aggregate: no completed execution verdict.")
        upload_failures = [name for name in UPLOAD if state(name) in BAD]
        if upload_failures:
            notes.append("Evidence: upload failed (" + "; ".join(upload_failures) + ").")
        elif executed in BAD | {"success"}:
            if all(state(name) == "success" for name in UPLOAD):
                notes.append("Evidence: upload steps succeeded; contents were not verified by this report.")
            else:
                notes.append("Evidence: complete uploads are unverified.")

    if checks is None:
        notes.append("CKR6: no check lookup for this event; not an aggregate result.")
    else:
        try:
            available = records(checks, "check_runs")
        except ValueError:
            available = []
        candidates = [
            c for c in matching(available, CKR)
            if c.get("head_sha") == head and type(c.get("app")) is dict
            and c["app"].get("slug") == "github-actions" and type(c.get("id")) is int
        ]
        ck = conclusion(max(candidates, key=lambda c: c["id"])) if candidates else "unavailable"
        notes.append(f"CKR6: {ck} (separate from aggregate testing).")
    return notes


def load_json(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("provider response exceeds bound")
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True)
    parser.add_argument("--run", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--checks", type=Path)
    args = parser.parse_args()
    print("## CI evidence summary (advisory)")
    checks = None
    if args.checks:
        try:
            checks = load_json(args.checks)
        except (OSError, ValueError):
            checks = {}  # optional CKR metadata cannot erase the aggregate observation
    try:
        notes = observe(
            load_json(args.jobs), checks,
            head=args.head, run=args.run, attempt=args.attempt,
        )
    except (OSError, ValueError, TypeError):
        print("\nReport unavailable: could not verify the bounded GitHub evidence.")
        return
    print(f"\nSource run: {args.run}, attempt: {args.attempt}, head: `{args.head}`.\n")
    for note in notes:
        print(f"- {note}")


if __name__ == "__main__":
    main()
