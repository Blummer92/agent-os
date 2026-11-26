"""Strict in-memory GitHub fixtures for the exact-merge report suites."""
from pathlib import Path
from re import escape
import unittest

from scripts.agent_os_post_merge_learning.report import EvidenceError

REPO = "Blummer92/agent-os"
SHA = "f" * 40
ASSOCIATION = f"/commits/{SHA}/pulls?per_page=100"
DETAIL = "/pulls/4101"
VALIDATION = "/actions/runs/100"
WORKFLOW_REF = f"{REPO}/.github/workflows/agent-os-post-merge-learning.yml@refs/heads/main"
FORBIDDEN = ("/reviews", "/comments", "/check-runs", "/statuses", "/timeline")
_DEFAULT = object()


def commits_page(page):
    return f"{DETAIL}/commits?per_page=100&page={page}"


def commit(n, msg):
    return {"sha": f"{n:040x}", "commit": {"message": msg}}


def pr(n=2, merged=True, sha=SHA):
    return {
        "number": 4101, "commits": n,
        "merged_at": "2026-11-23T23:39:56Z" if merged else None,
        "merged": merged, "merge_commit_sha": sha,
        "base": {"ref": "main", "repo": {"full_name": REPO}},
    }


def run(sha=SHA, conclusion="success"):
    return {
        "id": 100, "head_sha": sha, "name": "Agent OS Validation Gate", "event": "push",
        "head_branch": "main", "status": "completed", "conclusion": conclusion,
        "html_url": f"https://github.com/{REPO}{VALIDATION}",
    }


class Reader:
    """Only serve the current PR and exact validation run; log every read."""

    repository = REPO

    def __init__(self, records, metadata=_DEFAULT, validation=_DEFAULT, associations=_DEFAULT):
        self.requests = []
        self.responses = {
            DETAIL: pr(len(records)) if metadata is _DEFAULT else metadata,
            VALIDATION: run() if validation is _DEFAULT else validation,
            **{commits_page(page): records[(page - 1)*100:page*100] for page in range(1, 5)},
        }
        detail = self.responses[DETAIL]
        self.responses[ASSOCIATION] = [detail] if associations is _DEFAULT else associations

    def get(self, path):
        self.requests.append(path)
        if any(fragment in path for fragment in FORBIDDEN) or path not in self.responses:
            raise AssertionError(f"unexpected read: {path}")
        return self.responses[path]


class ReportCase(unittest.TestCase):
    def reader(self, *args, **kwargs):
        reader = Reader(*args, **kwargs)
        self.addCleanup(self.assert_no_history_reads, reader)
        return reader

    def assert_no_history_reads(self, reader):
        self.assertEqual(
            [path for path in reader.requests if any(part in path for part in FORBIDDEN)],
            [],
        )

    def evidence_error(self, code):
        return self.assertRaisesRegex(EvidenceError, rf"\A{escape(code)}\Z")


def repo_root():
    """Locate the repo by its workflow and producer, not by test depth."""
    for root in Path(__file__).resolve().parents:
        if ((root / ".github/workflows/agent-os-post-merge-learning.yml").is_file()
                and (root / "scripts/agent_os_post_merge_learning/report.py").is_file()):
            return root
    raise AssertionError("post-merge learning repository root not found")
