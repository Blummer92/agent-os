"""Semantic timing and read-only collection regressions, without live credentials."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/ci_perf/github_actions_timing.py'
SPEC = importlib.util.spec_from_file_location('actions_timing', SCRIPT)
timing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timing)
SHA = 'a' * 40


def run(attempt=1, status='completed', conclusion='success'):
    return dict(id=1, run_attempt=attempt, head_sha=SHA, path='validation.yml', event='pull_request',
        status=status, conclusion=conclusion, created_at='2026-10-01T00:00:00Z',
        run_started_at='2026-10-01T00:00:05Z', updated_at='2027-01-01T00:00:00Z', jobs=[
            dict(id=11, name='tests', status='completed', conclusion='success',
                started_at='2026-10-01T00:00:10Z', completed_at='2026-10-01T00:00:20Z', steps=[
                    dict(number=1, name='Install dependencies', status='completed', conclusion='success',
                         started_at='2026-10-01T00:00:10Z', completed_at='2026-10-01T00:00:13Z')])])


def summarize(runs):
    return timing.report(dict(runs=runs, collection={'status': 'complete'}), SHA)


class TimingTests(unittest.TestCase):
    def test_native_timestamps_and_no_updated_at_wall_time(self):
        result = summarize([run()])
        row = result['runs'][0]
        self.assertEqual(row['initial_dispatch_delay_seconds'], 5)
        self.assertIsNone(row['workflow_wall_seconds'])
        self.assertEqual(row['created_to_last_completed_job_lower_bound_seconds'], 20)
        self.assertEqual(row['jobs'][0]['duration_seconds'], 10)
        self.assertEqual(row['jobs'][0]['steps'][0]['duration_seconds'], 3)

    def test_duplicate_attempt_is_not_double_counted(self):
        result = summarize([run(), run()])
        self.assertEqual(result['run_attempt_count'], 1)
        self.assertEqual(result['missing_data']['duplicate-run-attempt'], 1)

    def test_repeated_attempts_distinct_and_queue_origin_unknown(self):
        result = summarize([run(), run(attempt=2)])
        self.assertEqual(result['run_attempt_count'], 2)
        self.assertIsNone(result['runs'][1]['initial_dispatch_delay_seconds'])
        self.assertIn('rerun-queue-origin-unavailable', result['runs'][1]['missing'])

    def test_reversed_job_is_not_zero_or_negative_measurement(self):
        r = run()
        r['jobs'][0]['completed_at'] = '2026-09-30T00:00:00Z'
        item = summarize([r])['runs'][0]['jobs'][0]
        self.assertIsNone(item['duration_seconds'])
        self.assertEqual(item['missing'], 'reversed-timestamp')

    def test_skipped_is_not_successful_zero_duration(self):
        r = run()
        r['jobs'][0]['conclusion'] = 'skipped'
        self.assertIsNone(summarize([r])['runs'][0]['jobs'][0]['duration_seconds'])

    def test_inflight_does_not_become_workflow_completion(self):
        result = summarize([run(status='in_progress', conclusion=None)])
        self.assertIsNone(result['runs'][0]['created_to_last_completed_job_lower_bound_seconds'])

    def test_cancelled_runs_do_not_pool_with_success(self):
        second = run(conclusion='cancelled'); second['id'] = 2
        self.assertEqual(len(summarize([run(), second])['summaries']), 2)

    def test_sha_boundaries_not_pooled_and_staleness_not_supersession(self):
        r = run(); r['id'] = 2; r['head_sha'] = 'b' * 40
        result = timing.report({'runs': [run(), r]}, SHA, SHA)
        self.assertEqual(len(result['summaries']), 2)
        self.assertTrue(result['runs'][1]['stale_head'])
        self.assertTrue(result['runs'][1]['superseded'].startswith('unknown'))

    def test_nearest_rank_p90_and_actual_n(self):
        result = timing.distribution(list(range(1, 21)))
        self.assertEqual((result['n'], result['median_seconds'], result['p90_seconds']), (20, 10.5, 18))
        self.assertEqual(timing.distribution([])['n'], 0)
        self.assertEqual(timing.distribution([1])['confidence'], 'low')

    def test_bad_provenance_and_input_bounds_rejected(self):
        with self.assertRaises(ValueError): timing.report({'runs': []}, 'main')
        with self.assertRaises(ValueError): summarize([run()] * 101)
        r = run(); r['run_attempt'] = True
        with self.assertRaises(ValueError): summarize([r])

    def test_optional_expected_head_and_capture_shape_are_validated(self):
        with self.assertRaises(ValueError): timing.report({'runs': []}, SHA, 'main')
        with self.assertRaises(ValueError): timing.report([], SHA)

    def test_collection_get_only_pagination_and_attempt_endpoints(self):
        calls = []
        r = run(attempt=2)
        def get(endpoint):
            calls.append(endpoint)
            if '/actions/runs?' in endpoint: return {'workflow_runs': [r]}
            if '/jobs?' in endpoint: return {'jobs': run()['jobs']}
            return run()
        result = timing.collect('owner/repo', '2026-10-01T00:00:00Z', '2026-10-02T00:00:00Z',
                                'validation.yml', get=get)
        self.assertEqual(len(result['runs']), 2)
        self.assertTrue(any('/attempts/1/jobs?' in x for x in calls))
        self.assertTrue(any('/attempts/2/jobs?' in x for x in calls))
        self.assertEqual(result['collection']['status'], 'complete')

    def test_mismatched_attempt_identity_is_error_not_relabelled(self):
        for field, wrong in (('id', 999), ('run_attempt', 5), ('head_sha', 'b' * 40),
                             ('path', 'wrong.yml')):
            def get(endpoint):
                if '/actions/runs?' in endpoint: return {'workflow_runs': [run(attempt=2)]}
                if '/jobs?' in endpoint: return {'jobs': []}
                mismatched = run(); mismatched[field] = wrong
                return mismatched
            result = timing.collect('owner/repo', '2026-10-01T00:00:00Z',
                '2026-10-02T00:00:00Z', 'validation.yml', get=get)
            self.assertEqual(result['collection']['status'], 'error')
            self.assertIn('native-api-provenance-mismatch', result['collection']['reason_codes'])
            self.assertEqual(result['runs'], [])

    def test_job_lineage_mismatch_is_refused_live_and_offline(self):
        for field, wrong in (('run_id', 999), ('head_sha', 'b' * 40), ('run_attempt', 5)):
            r = run(); r['jobs'][0][field] = wrong
            with self.assertRaisesRegex(ValueError, 'job-lineage-mismatch'):
                summarize([r])
            def get(endpoint):
                if '/actions/runs?' in endpoint: return {'workflow_runs': [run()]}
                return {'jobs': r['jobs']}
            result = timing.collect('owner/repo', '2026-10-01T00:00:00Z',
                '2026-10-02T00:00:00Z', 'validation.yml', get=get)
            self.assertEqual(result['collection']['status'], 'error')
            self.assertIn('native-api-provenance-mismatch', result['collection']['reason_codes'])
            self.assertEqual(result['runs'], [])

    def test_api_errors_fail_visibly_without_provider_secrets(self):
        def get(_): raise timing.ApiError('credential=DO-NOT-REPORT')
        result = timing.collect('owner/repo', '2026-10-01T00:00:00Z', '2026-10-02T00:00:00Z',
                                'validation.yml', get=get)
        self.assertEqual(result['collection']['status'], 'error')
        self.assertNotIn('DO-NOT-REPORT', json.dumps(result))

    def test_api_request_uses_existing_gh_auth_and_fixed_get(self):
        with patch.object(timing.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{}', '')) as mock:
            self.assertEqual(timing.gh_get('repos/owner/repo/actions/runs'), {})
        self.assertEqual(mock.call_args.args[0][:4], ['gh', 'api', '--method', 'GET'])

    def test_rate_limit_is_distinct_from_access_failure(self):
        for diagnostic, expected in [('HTTP 429 rate limit', 'native-api-rate-limited'),
                                     ('HTTP 403 forbidden', 'native-api-access-denied')]:
            with patch.object(timing.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', diagnostic)):
                with self.assertRaises(timing.ApiError) as error:
                    timing.gh_get('repos/owner/repo/actions/runs')
                self.assertEqual(error.exception.code, expected)

    def test_pagination_cap_marks_partial(self):
        result = timing.collect('owner/repo', '2026-10-01T00:00:00Z', '2026-10-02T00:00:00Z',
            'validation.yml', max_pages=1, max_runs=1,
            get=lambda endpoint: {'workflow_runs': [run()] * 100} if '/actions/runs?' in endpoint else {'jobs': []})
        self.assertEqual(result['collection']['status'], 'partial')

    def test_cli_partial_exit_two_and_both_reports_preserve_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'capture.json'
            source.write_text(json.dumps({'runs': [run()], 'collection': {'status': 'partial'}}))
            process = subprocess.run(['python', str(SCRIPT), '--input', str(source),
                '--implementation-head', SHA, '--output', folder], capture_output=True)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(json.loads((Path(folder)/'timing.json').read_text())['implementation_head'], SHA)
            self.assertIn(SHA, (Path(folder)/'timing.md').read_text())


if __name__ == '__main__':
    unittest.main()
