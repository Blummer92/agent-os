"""The Lessons write workflow's sanitized summary step exposes activation prerequisites safely.

Runs the workflow's own embedded Python (extracted from the YAML, so the test cannot
drift from the shipped step) against a temporary result.json. No network, no secrets.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/agent-os-notion-lessons-write.yml"
STEP_NAME = "Publish sanitized result summary"


def _step():
    value = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(step for step in value["jobs"]["lessons_write"]["steps"] if step.get("name") == STEP_NAME)


def _embedded_python():
    run = _step()["run"]
    head, _, rest = run.partition("<<'PY'\n")
    assert head.strip() == "python -", head
    return rest.rsplit("\nPY", 1)[0] if "\nPY" in rest else rest.rstrip().removesuffix("PY")


def render(result, verification=None):
    """Execute the shipped step body; return the summary text it appends."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "agent-os-lessons-write"
        root.mkdir()
        if result is not None:
            (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
        if verification is not None:
            (root / "verification.json").write_text(json.dumps(verification), encoding="utf-8")
        summary = Path(tmp) / "summary.md"
        env = {**os.environ, "RUNNER_TEMP": tmp, "GITHUB_STEP_SUMMARY": str(summary)}
        done = subprocess.run([sys.executable, "-I", "-c", _embedded_python()], env=env,
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        return summary.read_text(encoding="utf-8") if summary.exists() else ""


BASE = {"status": "persisted", "reason_code": "exact-canonical-readback-confirmed", "write_attempts": 1,
        "readback_verified": True, "page_id": "page", "revision": "rev"}


DIRECT = {
    **BASE, "status": "unchanged", "reason_code": "direct-duplicate-reused", "write_attempts": 0,
    "lesson_id": "LL-87", "revision": "2026-10-05T13:06:00.000Z", "follow_existing_lesson": True,
    "reuse_log": {"event": "direct-duplicate-encountered", "lesson_id": "LL-87",
                  "source_revision": "2026-10-05T13:06:00.000Z", "counted_as_applied": False,
                  "application_receipt_required": True, "unrecognized": "DO-NOT-PUBLISH-PROVIDER"},
}
UPDATE = {
    **BASE, "lesson_id": "LL-87",
    "evidence_update": {"target_lesson_id": "LL-87", "primary_source_preserved": True,
                        "independent_verification_required": True,
                        "added_supporting_source_links": [
                            "https://github.com/Blummer92/agent-os/pull/3458", "PRIVATE-LINK-B"
                        ]},
}
VERIFIED = {"status": "verified-current-state", "persisted_state_verified": True}


class SummaryStepTests(unittest.TestCase):
    def test_step_is_unprivileged_and_unchanged_in_shape(self):
        step = _step()
        self.assertEqual(step["if"], "${{ always() }}")
        self.assertNotIn("env", step)
        self.assertNotIn("NOTION_TOKEN", step["run"])
        self.assertNotIn("secrets.", step["run"])

    def test_prerequisites_are_exposed_when_present(self):
        text = render({**BASE, "activation_prerequisites": {
            "required_fields_present": False,
            "missing_owner_activation": ["Status", "Surface Before Work?"],
            "missing_reviewed_metadata": ["Area", "Learning Type", "Source Link"]}})
        self.assertIn("required_fields_present: `False`", text)
        self.assertIn("missing_owner_activation: `['Status', 'Surface Before Work?']`", text)
        self.assertIn("missing_reviewed_metadata: `['Area', 'Learning Type', 'Source Link']`", text)
        self.assertIn("Agent OS Lessons Learned: persisted", text)
        self.assertIn("readback_verified: `True`", text)

    def test_present_and_complete_prerequisites_report_true_with_empty_lists(self):
        text = render({**BASE, "activation_prerequisites": {
            "required_fields_present": True, "missing_owner_activation": [], "missing_reviewed_metadata": []}})
        self.assertIn("required_fields_present: `True`", text)
        self.assertIn("missing_owner_activation: `[]`", text)

    def test_results_without_prerequisites_add_nothing(self):
        for result in ({**BASE, "activation_prerequisites": None}, BASE, {"status": "blocked"}):
            with self.subTest(result=result):
                text = render(result)
                self.assertNotIn("required_fields_present", text)
                self.assertNotIn("missing_owner_activation", text)
        self.assertIn("Agent OS Lessons Learned: unavailable", render(None))

    def test_hostile_or_unbounded_values_are_not_echoed(self):
        canary = "LEAK-CANARY-" + "x" * 40
        text = render({**BASE, "activation_prerequisites": {
            "required_fields_present": canary,
            "missing_owner_activation": [canary, {"raw": "notion payload"}, "Status"] + ["Area"] * 1000,
            "missing_reviewed_metadata": "Area" * 5000}})
        self.assertNotIn(canary, text)
        self.assertNotIn("notion payload", text)
        self.assertIn("required_fields_present: `False`", text)
        self.assertIn("missing_reviewed_metadata: `[]`", text)
        line = next(item for item in text.splitlines() if item.startswith("missing_owner_activation"))
        self.assertLessEqual(line.count("Area") + line.count("Status"), 5)
        self.assertLess(len(text), 1200)

    def test_malformed_prerequisite_shapes_never_crash_the_always_run_step(self):
        for value in ([], "x", 7, {"missing_owner_activation": 3}, {"missing_reviewed_metadata": None}):
            with self.subTest(value=value):
                render({**BASE, "activation_prerequisites": value})


    def test_duplicate_review_reports_bounded_ids_not_evidence_text(self):
        result = {"status": "blocked", "reason_code": "possible-semantic-duplicate",
                  "write_attempts": 0, "duplicate_lesson_ids": ["LL-3", "LL-87"],
                  "duplicate_evidence_reviews": [
                      {"lesson_id": "LL-3", "candidate_source_refs_to_verify": [
                           "https://github.com/Blummer92/agent-os/issues/3418",
                           "https://github.com/Blummer92/agent-os/pull/3458",
                           "https://github.com/other/repo/issues/16",
                           "https://github.com/Blummer92/agent-os/pull/3458#DO-NOT-PUBLISH-FRAGMENT",
                       ],
                       "claim_fields_to_review": ["DO-NOT-PUBLISH-NARRATIVE"]}
                  ]}
        text = render(result)
        self.assertIn("duplicate_candidates_for_review: `['LL-3', 'LL-87']`", text)
        self.assertIn("LL-3 candidate_sources_to_verify: ", text)
        self.assertIn("https://github.com/Blummer92/agent-os/issues/3418", text)
        self.assertIn("https://github.com/Blummer92/agent-os/pull/3458", text)
        self.assertNotIn("github.com/other", text)
        self.assertNotIn("DO-NOT-PUBLISH", text)
        self.assertNotIn("direct_duplicate_encountered", text)

    def test_candidate_sources_and_complete_delta_are_distinct(self):
        first = "https://github.com/Blummer92/agent-os/issues/3418"
        second = "https://github.com/Blummer92/agent-os/pull/3458"
        unrelated = "https://github.com/Blummer92/agent-os/issues/999999"
        for comparison, shows_delta in (("complete", True), ("unavailable", False)):
            with self.subTest(comparison=comparison):
                text = render({
                    "status": "blocked", "reason_code": "possible-semantic-duplicate", "write_attempts": 0,
                    "duplicate_lesson_ids": ["LL-87"], "duplicate_evidence_reviews": [{
                        "lesson_id": "LL-87", "candidate_source_refs_to_verify": [first, second],
                        "source_comparison": comparison, "new_source_refs_to_review": [second, unrelated],
                    }],
                })
                self.assertIn(f"LL-87 candidate_sources_to_verify: `{[first, second]}`", text)
                self.assertEqual(f"LL-87 candidate_new_repository_sources_to_verify: `{[second]}`" in text,
                                 shows_delta)
                self.assertNotIn(unrelated, text)

    def test_primary_source_comparison_is_closed_vocabulary(self):
        for value in ("unavailable", "not-proposed", "same", "different", "PRIVATE-PRIMARY-REASON", []):
            with self.subTest(value=value):
                text = render({
                    "status": "blocked", "reason_code": "possible-semantic-duplicate", "write_attempts": 0,
                    "duplicate_lesson_ids": ["LL-87"], "duplicate_evidence_reviews": [{
                        "lesson_id": "LL-87", "primary_source_comparison": value,
                    }],
                })
                self.assertEqual("LL-87 primary_source_comparison" in text,
                                 value in ("unavailable", "not-proposed", "same", "different"))
                self.assertNotIn("PRIVATE-PRIMARY-REASON", text)

    def test_does_not_echo_invalid_conflicting_and_oversized_candidates(self):
        for ids in (["LL-3", "PRIVATE-GITHUB-BODY`"], ["LL-3", "LL-3"], ["LL-0"],
                    [f"LL-{i}" for i in range(1, 12)], "LL-3"):
            with self.subTest(ids=ids):
                text = render({"status": "blocked", "reason_code": "possible-semantic-duplicate",
                               "write_attempts": 0, "duplicate_lesson_ids": ids})
                self.assertNotIn("duplicate_candidates_for_review", text)
                self.assertNotIn("PRIVATE-GITHUB", text)

    def test_title_conflict_reuses_the_same_bounded_review_projection(self):
        review = {"lesson_id": "LL-87", "candidate_source_refs_to_verify": [
            "https://github.com/Blummer92/agent-os/issues/3418", "PRIVATE-PAGE-TEXT"
        ]}
        for status, reason, attempts, report in (
            ("conflict", "existing-lesson-requires-reviewed-update-entry", 0, True),
            ("conflict", "lesson-appeared-before-create", 0, True),
            ("conflict", "stale-revision-refused", 0, False),
            ("conflict", "possible-semantic-duplicate", 0, False),
            ("blocked", "lesson-appeared-before-create", 0, False),
            ("conflict", "lesson-appeared-before-create", 1, False),
        ):
            with self.subTest(status=status, reason=reason, attempts=attempts):
                result = {"status": status, "reason_code": reason, "write_attempts": attempts,
                          "duplicate_lesson_ids": ["LL-87"], "duplicate_evidence_reviews": [review]}
                text = render(result)
                self.assertEqual("duplicate_candidates_for_review: `['LL-87']`" in text, report)
                self.assertEqual("https://github.com/Blummer92/agent-os/issues/3418" in text, report)
                self.assertNotIn("PRIVATE-PAGE-TEXT", text)
                if report:
                    del result["duplicate_lesson_ids"]
                    self.assertNotIn("candidate_sources_to_verify", render(result))

    def test_direct_duplicate_preserves_encounter_without_inventing_use(self):
        text = render(DIRECT)
        for line in ("direct_duplicate_encountered: `LL-87`",
                     "duplicate_counted_as_applied: `False`",
                     "separate_application_receipt_required: `True`"):
            self.assertIn(line, text)
        self.assertNotIn("DO-NOT-PUBLISH", text)
        self.assertNotIn("independent_state_verification: `verified-current-state`", text)

    def test_direct_duplicate_with_mismatched_or_invalid_binding_is_omitted(self):
        for top, event in (({}, {"counted_as_applied": 0}),
                           ({}, {"counted_as_applied": True}),
                           ({}, {"application_receipt_required": False}),
                           ({}, {"lesson_id": "LL-2"}),
                           ({}, {"source_revision": "2026-01-02T01:23:45Z"}),
                           ({"status": "persisted"}, {}),
                           ({"write_attempts": False}, {}),
                           ({"readback_verified": "True"}, {}),
                           ({"revision": "DO-NOT-PUBLISH malformed revision"}, {})):
            with self.subTest(top=top, event=event):
                text = render({**DIRECT, **top, "reuse_log": {**DIRECT["reuse_log"], **event}})
                self.assertNotIn("direct_duplicate_encountered", text)
                self.assertNotIn("DO-NOT-PUBLISH", text)

    def test_supporting_update_projects_count_only_after_independent_verification(self):
        no_verification = render(UPDATE)
        self.assertNotIn("supporting_sources_added", no_verification)
        verified = render(UPDATE, VERIFIED)
        self.assertIn("supporting_sources_added: `2`", verified)
        self.assertIn("primary_source_preserved: `True`", verified)
        self.assertIn("added_repository_supporting_sources: `['https://github.com/Blummer92/agent-os/pull/3458']`", verified)
        self.assertNotIn("PRIVATE", verified)

    def test_unbound_or_malformed_evidence_update_does_not_project(self):
        for top, evidence, verification in (
            ({"status": "uncertain"}, {}, VERIFIED),
            ({"write_attempts": True}, {}, VERIFIED),
            ({}, {"target_lesson_id": "LL-2"}, VERIFIED),
            ({}, {"primary_source_preserved": "True"}, VERIFIED),
            ({}, {"independent_verification_required": False}, VERIFIED),
            ({}, {"added_supporting_source_links": ["duplicate", "duplicate"]}, VERIFIED),
            ({}, {"added_supporting_source_links": ["x"] * 1000}, VERIFIED),
            ({}, {"added_supporting_source_links": [{}]}, VERIFIED),
            ({}, {}, {"status": "verified-current-state", "persisted_state_verified": "True"}),
        ):
            with self.subTest(top=top, evidence=evidence, verification=verification):
                text = render({**UPDATE, **top, "evidence_update": {**UPDATE["evidence_update"],
                              **evidence}}, verification)
                self.assertNotIn("supporting_sources_added", text)
                self.assertNotIn("PRIVATE", text)


if __name__ == "__main__":
    unittest.main()
