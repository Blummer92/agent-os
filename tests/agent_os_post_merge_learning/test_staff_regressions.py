"""Fail-closed report and workflow regressions for PR #4102."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import yaml

from scripts.agent_os_post_merge_learning import report
from report_fixtures import (
    ASSOCIATION, DETAIL, REPO, SHA, ReportCase, commit, commits_page, pr, repo_root, run,
)


class StaffRegressions(ReportCase):
    def test_null_base_and_repo(self):
        for base, code in ((None, 'base-not-main'), ({'ref': 'main', 'repo': None}, 'base-repository-mismatch')):
            with self.subTest(base=base), self.evidence_error(code):
                report.build_report(self.reader([commit(1, 'fix(api): repair')], metadata={**pr(1), 'base': base}), SHA, 4101, None)

    def test_manual_summary_has_no_dependency_on_success_fields(self):
        result = {'status': 'manual-review', 'reason_code': 'base-not-main'}
        self.assertIn('base-not-main', report.render_summary(result))

    def test_unexpected_exception_writes_bounded_non_authorizing_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'report.json'
            summary = Path(tmp) / 'summary.md'
            with patch.object(report, 'GitHubReader', side_effect=RuntimeError('private-text')), patch.dict(
                os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}
            ):
                result = report.main(['--repository', REPO, '--merge-sha', SHA, '--output', str(output)])
            self.assertEqual(result, 2)
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt['status'], 'manual-review')
            self.assertEqual(receipt['reason_code'], 'report-generation-failed')
            self.assertIsNone(receipt['lesson_proposal'])
            self.assertIs(receipt['publication_authorized'], False)
            for path in (output, summary):
                self.assertNotIn('private-text', path.read_text())

    def test_only_fix_groups_spend_budget(self):
        rows = [commit(i, f'test(scope{i}): regression') for i in range(1, 27)]
        rows.append(commit(27, 'fix(api): repair'))
        result = report.build_report(self.reader(rows), SHA, 4101, 100)
        self.assertEqual([lead['scope'] for lead in result['review_leads']], ['api'])
        self.assertEqual(result['commit_kind_counts']['test'], 26)

    def test_unscoped_label_does_not_claim_repeated_repair(self):
        rows = [commit(1, 'fix: one'), commit(2, 'fix: unrelated')]
        with patch.object(report, 'normalize_learning_outcome', wraps=report.normalize_learning_outcome) as normalize:
            result = report.build_report(self.reader(rows), SHA, 4101, 100)
        self.assertTrue(result['review_leads'])
        self.assertEqual(sum(lead['fix_count'] for lead in result['review_leads']), 2)
        self.assertTrue(normalize.call_args_list)
        self.assertTrue(all(c.args[0].signal is report.LearningSignal.SUBSTANTIVE_REVIEW_FINDING
                            for c in normalize.call_args_list))

    def test_long_crlf_and_lf_commit_subjects(self):
        for newline in ('\r\n', '\n'):
            for title in ('fix(api): repair', 'fix(api): ' + 'x' * 250):
                with self.subTest(newline=newline, title=title[:20]):
                    result = report.build_report(self.reader([commit(1, title + newline + 'body')]), SHA, 4101, 100)
                    self.assertEqual(result['commit_kind_counts']['fix'], 1)
                    self.assertEqual(result['review_leads'][0]['scope'], 'api')

    def test_api_shas_normalized_in_both_routes_and_commit_refs(self):
        for explicit in (4101, None):
            with self.subTest(explicit=explicit):
                row = {**commit(10, 'fix(api): repair'), 'sha': f'{10:040X}'}
                reader = self.reader([row], metadata=pr(1, sha=SHA.upper()), validation=run(sha=SHA.upper()))
                result = report.build_report(reader, SHA.upper(), explicit, 100)
                self.assertEqual(result['merge_sha'], SHA)
                self.assertEqual(result['all_commit_shas'], [f'{10:040x}'])
                self.assertEqual(result['review_leads'][0]['evidence_refs'], [f'https://github.com/{REPO}/commit/{10:040x}'])
                self.assertEqual(result['validation']['state'], 'success')

    def test_analyzer_provenance_does_not_accept_invalid_sha(self):
        with patch.dict(os.environ, {'GITHUB_SHA': 'bad', 'GITHUB_WORKFLOW_REF': ''}, clear=True):
            result = report.build_report(self.reader([commit(1, 'docs(api): note')]), SHA, 4101, 100)
        self.assertIsNone(result['analyzer_sha'])
        self.assertIsNone(result['analyzer_workflow_ref'])
        self.assertEqual(result['merge_sha'], SHA)

    def test_summary_escapes_all_dynamic_fields(self):
        result = report.build_report(self.reader([commit(1, 'fix(api): repair')]), SHA, 4101, 100)
        attack = '<tag>|\n[link](target)'
        result.update(pr_url=attack, merge_sha=attack, commit_count=attack, analyzer_sha=attack)
        result['validation']['state'] = attack
        result['review_leads'][0].update(scope=attack, fix_count=attack, test_count=attack)
        rendered = report.render_summary(result)
        self.assertNotIn('<tag>', rendered)
        self.assertNotIn('[link](target)', rendered)
        self.assertEqual(rendered.count(r'\|'), 8)

    def test_workflow_contract_is_parsed(self):
        path = repo_root() / '.github/workflows/agent-os-post-merge-learning.yml'
        parsed = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(parsed['permissions'], {'contents': 'read'})
        steps = parsed['jobs']['review']['steps']
        upload = steps[-1]
        self.assertEqual(upload['with']['if-no-files-found'], 'error')
        self.assertEqual(upload['if'], 'always()')
        check = next(step for step in steps if step.get('name') == 'Require evidence receipt')
        self.assertEqual(check['if'], 'always()')
        self.assertIn('test -s', check['run'])

        self.assertEqual(parsed["on"]["workflow_run"]["workflows"], ["Agent OS Validation Gate"])
        self.assertEqual(parsed["on"]["workflow_run"]["types"], ["completed"])
        self.assertEqual(
            parsed["jobs"]["premerge_tests"]["steps"][0]["with"]["ref"],
            "${{ github.event.pull_request.head.sha }}",
        )
        analysis = next(step for step in steps if step.get("name") == "Read-only exact-merge analysis")
        self.assertNotIn("GITHUB_TOKEN", analysis["env"])
        for flag in ("--merge-sha", "--pr-number", "--validation-run-id", "--output"):
            self.assertIn(flag, analysis["run"])
        for job in parsed["jobs"].values():
            self.assertNotIn("permissions", job)
            self.assertNotIn("continue-on-error", job)
            for step in job["steps"]:
                self.assertNotIn("continue-on-error", step)
                command = step.get("run", "").lower()
                self.assertNotRegex(command, r"\b(notion|gh)\b")

    def test_invalid_cli_numbers_write_a_receipt_without_github(self):
        for flag, code in (("--pr-number", "pr-number-invalid"),
                           ("--validation-run-id", "validation-run-id-invalid")):
            with self.subTest(flag=flag), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "out.json"
                with patch.object(report, "GitHubReader") as reader, patch.dict(os.environ, {
                    "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary.md"),
                }):
                    exit_code = report.main([
                        "--repository", REPO, "--merge-sha", SHA, flag, "not-a-number", "--output", str(out),
                    ])
                reader.assert_not_called()
                self.assertEqual(exit_code, 2)
                receipt = json.loads(out.read_text())
                self.assertEqual(receipt["reason_code"], code)
                self.assertIs(receipt["listed_commits_complete"], False)

    def test_summary_write_failure_replaces_success_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            with patch.object(report, "GitHubReader", return_value=self.reader([commit(1, "fix(api): repair")])), patch.dict(
                os.environ, {"GITHUB_STEP_SUMMARY": tmp}
            ):
                exit_code = report.main(["--repository", REPO, "--merge-sha", SHA, "--pr-number", "4101", "--output", str(out)])
            self.assertEqual(exit_code, 2)
            receipt = json.loads(out.read_text())
            self.assertEqual((receipt["status"], receipt["reason_code"]), ("manual-review", "summary-write-failed"))
            self.assertIsNone(receipt["lesson_proposal"])

    def test_full_association_page_cannot_prove_uniqueness(self):
        others = [{**pr(1, merged=False), "number": n} for n in range(1, 100)]
        reader = self.reader([], associations=[pr(1), *others])
        with self.evidence_error("associated-prs-incomplete"):
            report.build_report(reader, SHA, None, 100)
        self.assertEqual(reader.requests, [ASSOCIATION])

    def test_malformed_association_is_not_a_non_merge_push(self):
        for value in (None, {}, [42]):
            with self.subTest(value=value):
                reader = self.reader([], associations=value)
                with self.evidence_error("associated-prs-malformed"):
                    report.build_report(reader, SHA, None, None)
                self.assertEqual(reader.requests, [ASSOCIATION])

    def test_duplicate_commit_identity_is_case_insensitive(self):
        row = commit(10, "fix(api): repair")
        reader = self.reader([row, {**row, "sha": row["sha"].upper()}])
        with self.evidence_error("commit-history-identity-invalid"):
            report.build_report(reader, SHA, 4101, 100)
        self.assertEqual(reader.requests, [DETAIL, commits_page(1)])

    def test_non_boolean_merge_marker_is_not_a_merge(self):
        for flag in (0, 1, "true", None):
            with self.subTest(flag=flag):
                reader = self.reader([], metadata={**pr(1), "merged": flag})
                with self.evidence_error("pr-not-merged"):
                    report.build_report(reader, SHA, 4101, 100)
                self.assertEqual(reader.requests, [DETAIL])
