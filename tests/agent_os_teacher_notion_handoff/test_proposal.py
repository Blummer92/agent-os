"""Zero-I/O tests of the proposed GitHub ingress grammar and non-authority."""
import unittest
from scripts.agent_os_teacher_notion_handoff import (
    ProposalBlocked, build_proposal, inspect_github_comment,
)

def event(body="/agent-os teacher-notion-propose planning-note photography-foundations"):
    return {
        "action": "created",
        "repository": {"full_name": "Blummer92/agent-os", "id": 1289370915},
        "issue": {"number": 2801},
        "comment": {
            "id": 19,
            "user": {"id": 32861845, "login": "Blummer92", "type": "User"},
            "created_at": "2026-10-20T16:00:00Z",
            "updated_at": "2026-10-20T16:00:00Z",
            "body": body,
        },
    }

class ProposalTest(unittest.TestCase):
    def test_proposed_only_even_for_owner(self):
        item = inspect_github_comment(event(), event_name="issue_comment", ref="refs/heads/main", run_attempt="1")
        self.assertEqual(item["status"], "review-required")
        self.assertEqual(item["write_mode"], "draft")
        for field in ("external_write_authorized", "notion_write_performed", "secret_dispatch_authorized", "execution_authorized", "notion_target_verified"):
            self.assertIs(item[field], False)
        self.assertEqual(item["comment_id"], 19)

    def test_all_categories_are_proposals_only(self):
        for category in ("planning-note", "lesson-candidate", "working-knowledge", "handoff-note"):
            record = build_proposal(category, "photo-review-1")
            self.assertEqual(record["comment"], f"/agent-os teacher-notion-propose {category} photo-review-1")
            self.assertFalse(record["external_write_authorized"])

    def test_rejects_free_text_secrets_and_noncanonical_ids(self):
        for bad in ("", "Private Student Name", "abc;echo", "abc--def", "abc-", "abc\nsecret", "a" * 41, "https://notion.so/x", "ab"):
            with self.subTest(bad=bad), self.assertRaises(ProposalBlocked):
                build_proposal("planning-note", bad)

    def test_rejects_unknown_category(self):
        for bad in ("canonical-unit", "student-record", "schema-change", "notion-write", ""):
            with self.subTest(bad=bad), self.assertRaises(ProposalBlocked):
                build_proposal(bad, "photography-foundations")

    def test_rejects_non_owner_and_bot(self):
        for change in ({"id": 1}, {"type": "Bot"}, {"login": "someone-else"}):
            payload = event()
            payload["comment"]["user"].update(change)
            with self.assertRaisesRegex(ProposalBlocked, "owner-comment-required"):
                inspect_github_comment(payload, event_name="issue_comment", ref="refs/heads/main", run_attempt="1")

    def test_rejects_replay_foreign_repo_and_pr(self):
        for key, value in (("event_name", "workflow_dispatch"), ("ref", "refs/heads/feature"), ("run_attempt", "2")):
            context = dict(event_name="issue_comment", ref="refs/heads/main", run_attempt="1")
            context[key] = value
            with self.assertRaises(ProposalBlocked):
                inspect_github_comment(event(), **context)
        foreign = event()
        foreign["repository"]["id"] = 999
        with self.assertRaises(ProposalBlocked):
            inspect_github_comment(foreign, event_name="issue_comment", ref="refs/heads/main", run_attempt="1")
        pr = event()
        pr["issue"]["pull_request"] = {}
        with self.assertRaises(ProposalBlocked):
            inspect_github_comment(pr, event_name="issue_comment", ref="refs/heads/main", run_attempt="1")

    def test_rejects_edits_expanded_commands_and_student_notes(self):
        samples = (
            "/agent-os teacher-notion-propose planning-note photography-foundations extra",
            "/agent-os teacher-notion-propose  planning-note photography-foundations",
            "/agent-os teacher-notion-propose planning-note photography-foundations\nStudent: X",
            "/agent-os notion-write photography-foundations",
        )
        for sample in samples:
            with self.subTest(sample=sample), self.assertRaises(ProposalBlocked):
                inspect_github_comment(event(sample), event_name="issue_comment", ref="refs/heads/main", run_attempt="1")
        changed = event()
        changed["comment"]["updated_at"] = "2026-10-20T16:01:00Z"
        with self.assertRaises(ProposalBlocked):
            inspect_github_comment(changed, event_name="issue_comment", ref="refs/heads/main", run_attempt="1")

if __name__ == "__main__":
    unittest.main()
