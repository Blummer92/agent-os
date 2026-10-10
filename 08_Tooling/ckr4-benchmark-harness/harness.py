"""CKR4 bounded GPT-6 A/B/C observation runner; read-only providers."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

MODEL = "gpt-6-astra"
FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "agent-memory-context-manager/tests/fixtures/ckr4_hypothesis_benchmark.json"
GITHUB_REPO = "Blummer92/agent-os"
MAX_TASKS = 3
MAX_OUTPUT_TOKENS = 512
MAX_SOURCE_CHARS = 6000
MAX_ROWS = 20
TASKS_REQUIRING_SPECIALIZED = {"T1", "T3", "T4", "T6", "T7", "T8", "T9", "T10"}


def request_json(url: str, *, token: str, payload: dict | None = None, notion: bool = False) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if notion:
        headers["Notion-Version"] = "2022-06-28"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("provider returned non-object")
    return result


def frozen_tasks() -> dict[str, str]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tasks = {t["task_id"]: t["description"] for t in fixture["tasks"]}
    if list(tasks) != [f"T{i}" for i in range(1, 11)]:
        raise ValueError("frozen task IDs changed")
    return tasks


def parse_tasks(value: str, known: dict[str, str]) -> list[str]:
    tasks = [part.strip() for part in value.split(",")]
    if not tasks or len(tasks) > MAX_TASKS or len(set(tasks)) != len(tasks):
        raise ValueError("task count/uniqueness out of bounds")
    if any(t not in known for t in tasks):
        raise ValueError("unknown frozen task")
    return tasks


def github_evidence() -> str:
    # One immutable GitHub authority reference shared by all arms.
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/08_Tooling/agent-memory-context-manager/CKR4_BENCHMARK_COUNTERS.md"
    # GitHub contents endpoint defaults to base64; use raw content through fixed raw URL.
    req = urllib.request.Request(
        "https://raw.githubusercontent.com/Blummer92/agent-os/main/08_Tooling/agent-memory-context-manager/CKR4_BENCHMARK_COUNTERS.md",
        headers={"Accept": "text/plain"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read(MAX_SOURCE_CHARS).decode("utf-8", "replace")


def notion_rows(token: str, source: str, *, targeted: bool) -> list[dict]:
    # No mutation: the only Notion operation is POST /query, a read endpoint.
    if not source or not all(ch.isalnum() or ch == "-" for ch in source):
        raise ValueError("invalid Notion data source identifier")
    query = {"page_size": 5 if targeted else MAX_ROWS}
    if targeted:
        query["filter"] = {"and": [
            {"property": "Surface Before Work?", "checkbox": {"equals": True}},
            {"property": "Status", "select": {"does_not_equal": "Archived note"}},
        ]}
    result = request_json(
        f"https://api.notion.com/v1/databases/{source}/query",
        token=token, payload=query, notion=True,
    )
    if result.get("has_more"):
        raise ValueError("incomplete bounded Notion population")
    rows = result.get("results")
    if not isinstance(rows, list) or len(rows) > (5 if targeted else MAX_ROWS):
        raise ValueError("Notion result exceeds bound")
    return rows


def safe_notion_projection(rows: list[dict]) -> list[dict]:
    # Never place raw Notion pages, titles, or personal content in model prompts/artifacts.
    return [{"row_id": str(row.get("id", ""))[:48],
             "currentness": "unverified",
             "authority": "advisory-only"} for row in rows]


def prompt(task: str, description: str, condition: str, canonical: str, notion: list[dict]) -> str:
    return (
        f"Frozen CKR4 task {task}: {description}.\n"
        "Return a short diagnosis/implementation approach with correctness, safety, and "
        "GitHub source-of-truth considerations. No actions or writes. "
        "Notion is non-authoritative; unverified candidates must not override GitHub.\n"
        f"Canonical GitHub excerpt:\n{canonical}\n"
        f"Advisory Notion candidate metadata:\n{json.dumps(notion, sort_keys=True)}"
    )


def model_call(key: str, text: str) -> dict:
    result = request_json("https://api.openai.com/v1/responses", token=key, payload={
        "model": MODEL, "reasoning": {"effort": "medium"},
        "input": text, "max_output_tokens": MAX_OUTPUT_TOKENS,
        "store": False,
    })
    usage = result.get("usage") or {}
    if not isinstance(usage.get("input_tokens"), int):
        raise ValueError("model did not provide directly observed input_tokens")
    if result.get("status") != "completed":
        raise ValueError("model response not completed")
    return {"context_token_count": usage["input_tokens"],
            "agent_step_count": 1,
            "output_tokens": usage.get("output_tokens"),
            "model_response_id": result.get("id")}


def reduction(before: int | None, after: int | None) -> float | None:
    return None if before is None or after is None or before == 0 else (before - after) / before


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    tasks = frozen_tasks()
    selected = parse_tasks(args.tasks, tasks)
    api_key = os.environ["CKR4_MODEL_API_KEY"]
    notion_token = os.environ["NOTION_TOKEN"]
    source = os.environ["NOTION_SOURCE"]
    evidence = {"schema_version": 1, "benchmark_issue": 1146,
                "model": MODEL, "model_effort": "medium",
                "status": "incomplete", "observations": [], "scoring": [],
                "limitations": ["Model responses are not automatically graded for correctness or safety.",
                                "No raw Notion content is projected; candidate identities are unverified.",
                                "These are single-turn observations, not comparable agent tool-step runs."]}
    output = pathlib.Path(args.out)
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    canonical = github_evidence()
    for task in selected:
        observed = {}
        for arm in ("A", "B", "C"):
            notion = []
            reads = 0
            if arm == "B" or (arm == "C" and task in TASKS_REQUIRING_SPECIALIZED):
                rows = notion_rows(notion_token, source, targeted=arm == "C")
                reads = 1
                notion = safe_notion_projection(rows)
            observation = model_call(api_key, prompt(task, tasks[task], arm, canonical, notion))
            observation.update({"task_id": task, "architecture": arm,
                                "github_read_count": 1, "notion_retrieval_count": reads,
                                "candidate_count": len(notion), "selected_count": None,
                                "irrelevant_candidate_count": None,
                                "source_authority": "github-canonical-notion-advisory",
                                "correctness": "ungraded", "safety": "ungraded"})
            evidence["observations"].append(observation)
            observed[arm] = observation
            output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        evidence["scoring"].append({"task_id": task,
            "context_reduction_C_vs_A": reduction(observed["A"]["context_token_count"],
                                                   observed["C"]["context_token_count"]),
            "agent_step_reduction_C_vs_A": reduction(observed["A"]["agent_step_count"],
                                                      observed["C"]["agent_step_count"]),
            "disposition": "manual-review"})
    evidence["status"] = "measured-ungraded"
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, KeyError, urllib.error.URLError) as exc:
        print(f"CKR4 fail-closed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
