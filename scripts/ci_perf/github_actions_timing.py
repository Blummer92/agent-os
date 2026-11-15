#!/usr/bin/env python3
"""Read-only native Actions capture and bounded, advisory timing reports (#3694)."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
from urllib.parse import urlencode

MAX_RUNS = 100
MAX_JOBS = 1000
MAX_STEPS = 200
MAX_INPUT_BYTES = 10_000_000


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except ValueError:
        return None


def elapsed(start, end):
    a, b = timestamp(start), timestamp(end)
    if a is None or b is None:
        return None, 'missing-timestamp'
    delta = (b - a).total_seconds()
    return (delta, None) if delta >= 0 else (None, 'reversed-timestamp')


def distribution(values):
    values = sorted(values)
    n = len(values)
    return {'n': n, 'median_seconds': statistics.median(values) if n else None,
            'p90_seconds': values[math.ceil(.9 * n) - 1] if n else None,
            'confidence': 'low' if n < 20 else 'sample-size-only; comparability-unverified'}


def step_phase(name):
    # Heuristic labels are advisory; raw step names and durations remain visible.
    text = name.casefold()
    if re.search(r'upload|artifact|report|post ', text):
        return 'artifact-reporting'
    if re.search(r'install|dependencies|pip |npm ci', text):
        return 'dependency-install'
    if re.search(r'test|pytest|aggregate validation|validate-all', text):
        return 'test-validation'
    if re.search(r'set up|setup|checkout|check out', text):
        return 'setup'
    return 'other'


def validate_job_lineage(job, run):
    if not isinstance(job, dict):
        raise ValueError('job must be an object')
    for field, expected in (('run_id', run['id']), ('head_sha', run['head_sha']),
                            ('run_attempt', run['run_attempt'])):
        if field in job and job[field] != expected:
            raise ValueError('job-lineage-mismatch')


def report(bundle, implementation_head, expected_head=None):
    if not re.fullmatch(r'[0-9a-f]{40}', implementation_head):
        raise ValueError('implementation head must be an exact 40-character SHA')
    if expected_head is not None and not re.fullmatch(r'[0-9a-f]{40}', expected_head):
        raise ValueError('expected head must be an exact 40-character SHA')
    if not isinstance(bundle, dict):
        raise ValueError('capture must be an object')
    runs = bundle.get('runs', [])
    if not isinstance(runs, list) or len(runs) > MAX_RUNS:
        raise ValueError('runs must be a bounded list')
    rows, groups, seen = [], defaultdict(lambda: defaultdict(list)), set()
    omissions = Counter()
    for run in runs:
        identity = (run.get('id'), run.get('run_attempt'))
        if not all(type(item) is int and item > 0 for item in identity):
            raise ValueError('run identity requires positive integer id and attempt')
        dedupe_key = (run.get('path'), *identity)
        if dedupe_key in seen:
            omissions['duplicate-run-attempt'] += 1
            continue
        seen.add(dedupe_key)
        sha = run.get('head_sha')
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('run head_sha is missing or invalid')
        jobs = run.get('jobs', [])
        if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
            raise ValueError('jobs must be a bounded list')
        row = {key: run.get(key) for key in ('id', 'run_attempt', 'workflow_id', 'path',
               'head_sha', 'event', 'status', 'conclusion', 'created_at', 'run_started_at', 'html_url')}
        row.update(stale_head=None if expected_head is None else sha != expected_head,
                   superseded='unknown; requires replacement-run evidence', jobs=[], missing=[])
        # updated_at is mutable metadata, never a workflow completion timestamp.
        row['workflow_wall_seconds'] = None
        row['missing'].append('workflow-completed-at-not-exposed')
        # For re-runs created_at belongs to attempt 1, so do not call it queue time.
        queue, reason = elapsed(run.get('created_at'), run.get('run_started_at'))
        row['initial_dispatch_delay_seconds'] = queue if identity[1] == 1 else None
        if identity[1] != 1:
            row['missing'].append('rerun-queue-origin-unavailable')
        elif reason:
            row['missing'].append('initial-dispatch-' + reason)
        group = (str(run.get('path')), str(run.get('event')), sha, str(run.get('conclusion')))
        if row['initial_dispatch_delay_seconds'] is not None:
            groups[group]['initial_dispatch_delay'].append(queue)
        job_ids = set()
        finishes = []
        for job in jobs:
            validate_job_lineage(job, run)
            if job.get('id') in job_ids:
                row['missing'].append('duplicate-job-id')
                continue
            job_ids.add(job.get('id'))
            item = {key: job.get(key) for key in ('id', 'name', 'status', 'conclusion')}
            duration, why = elapsed(job.get('started_at'), job.get('completed_at'))
            if job.get('status') != 'completed' or job.get('conclusion') == 'skipped':
                duration, why = None, 'incomplete-or-skipped'
            job_queue, queue_reason = elapsed(job.get('created_at'), job.get('started_at'))
            item.update(duration_seconds=duration, missing=why, queue_delay_seconds=job_queue,
                        queue_missing=queue_reason, steps=[])
            if job_queue is not None:
                groups[group]['job-queue:' + str(job.get('name'))].append(job_queue)
            if duration is not None:
                groups[group]['job:' + str(job.get('name'))].append(duration)
                finishes.append(timestamp(job['completed_at']))
            steps = job.get('steps', [])
            if not isinstance(steps, list) or len(steps) > MAX_STEPS:
                raise ValueError('steps must be a bounded list')
            numbers = set()
            for step in steps:
                if step.get('number') in numbers:
                    row['missing'].append('duplicate-step-number')
                    continue
                numbers.add(step.get('number'))
                seconds, missing = elapsed(step.get('started_at'), step.get('completed_at'))
                if step.get('status') != 'completed' or step.get('conclusion') == 'skipped':
                    seconds, missing = None, 'incomplete-or-skipped'
                phase = step_phase(str(step.get('name', '')))
                item['steps'].append(dict(number=step.get('number'), name=step.get('name'),
                    phase_heuristic=phase, duration_seconds=seconds, missing=missing))
                if seconds is not None:
                    groups[group]['step:' + str(job.get('name')) + ':' + str(step.get('name'))].append(seconds)
            row['jobs'].append(item)
        # This lower bound is not workflow finish time and is not used as wall-clock baseline.
        row['created_to_last_completed_job_lower_bound_seconds'] = None
        created = timestamp(run.get('created_at'))
        if created and finishes and run.get('status') == 'completed' and identity[1] == 1:
            lower_bound = (max(finishes) - created).total_seconds()
            if lower_bound >= 0:
                row['created_to_last_completed_job_lower_bound_seconds'] = lower_bound
        for reason in row['missing']:
            omissions[reason] += 1
        for job in row['jobs']:
            if job['queue_missing']:
                omissions['job-queue:' + job['queue_missing']] += 1
            if job['missing']:
                omissions['job:' + job['missing']] += 1
            for step in job['steps']:
                if step['missing']:
                    omissions['step:' + step['missing']] += 1
        rows.append(row)
    summaries = []
    for (workflow, event, sha, conclusion), metrics in sorted(groups.items()):
        summaries.append(dict(workflow=workflow, event=event, head_sha=sha, conclusion=conclusion,
                              metrics={key: distribution(values) for key, values in sorted(metrics.items())}))
    return dict(schema_version=1, authority='advisory-only', implementation_head=implementation_head,
                expected_head=expected_head, repository=bundle.get('repository'), window=bundle.get('window'),
                collection=bundle.get('collection', {'status': 'unknown'}), run_attempt_count=len(rows),
                missing_data=dict(sorted(omissions.items())), summaries=summaries, runs=rows,
                limitations=['p90 uses nearest rank; each metric reports its own n',
                    'Window filters original run creation, not execution: older-run reruns are excluded; included attempts can run outside window',
                    'Summary groups preserve workflow/event/SHA/conclusion; workflow configuration is not verified',
                    'Job/step durations overlap in parallel; do not sum into workflow wall time',
                    'Step phase names are heuristics, not validated suite or CPU timing',
                    'Cancelled and repeated attempts remain distinct; supersession requires external evidence',
                    'Run inventory completeness and exact attempt-job provenance are caller obligations for offline input'])


def markdown(result):
    lines = ['# GitHub Actions timing (advisory)', '', f"Implementation head: `{result['implementation_head']}`",
             f"Run attempts: {result['run_attempt_count']}; collection: {result['collection'].get('status', 'unknown')}",
             '', 'Detailed job/step identities, missing-data reasons, sample counts and SHA-separated distributions are in JSON.',
             '', '| Workflow | SHA | Event / conclusion | Metric | n | Median s | p90 s |',
             '|---|---|---|---|---:|---:|---:|']
    for group in result['summaries']:
        for metric, stats in group['metrics'].items():
            if metric.startswith('step:'):
                continue  # Keep Markdown bounded; JSON retains every raw step.
            clean = lambda value: str(value).replace('|', '\\|').replace('\n', ' ')
            lines.append('| ' + ' | '.join(clean(value) for value in (group['workflow'], group['head_sha'],
                group['event'] + ' / ' + group['conclusion'], metric, stats['n'],
                stats['median_seconds'], stats['p90_seconds'])) + ' |')
    lines.extend(['', '## Limitations', *['- ' + item for item in result['limitations']],
                  '- Fewer than 20 observations per group is low confidence. Even n ≥ 20 does not prove representative sampling.',
                  '- No speedup, authoritative validation or population baseline is claimed.'])
    return '\n'.join(lines) + '\n'


class ApiError(RuntimeError):
    def __init__(self, code):
        allowed = {'native-api-transport-unavailable', 'native-api-rate-limited',
                   'native-api-access-denied', 'native-api-provider-failure',
                   'native-api-invalid-json', 'invalid-inventory-page', 'native-api-provenance-mismatch'}
        self.code = code if code in allowed else 'native-api-provider-failure'
        super().__init__(self.code)


def gh_get(endpoint):
    try:
        process = subprocess.run(['gh', 'api', '--method', 'GET', endpoint],
                                 capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ApiError('native-api-transport-unavailable') from error
    if process.returncode:
        # Never echo stderr: provider diagnostics can contain sensitive data.
        diagnostic = process.stderr.casefold()
        if 'rate limit' in diagnostic or 'http 429' in diagnostic:
            raise ApiError('native-api-rate-limited')
        if any(code in diagnostic for code in ('http 401', 'http 403', 'http 404')):
            raise ApiError('native-api-access-denied')
        raise ApiError('native-api-provider-failure')
    try:
        return json.loads(process.stdout)
    except (ValueError, TypeError) as error:
        raise ApiError('native-api-invalid-json') from error


def collect(repository, start, end, workflow, max_pages=10, max_runs=20, get=gh_get):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('invalid repository')
    a, b = timestamp(start), timestamp(end)
    if not a or not b or not 0 < (b-a).total_seconds() <= 30*86400:
        raise ValueError('window must be timezone-aware and at most 30 days')
    if not 1 <= max_pages <= 10 or not 1 <= max_runs <= MAX_RUNS:
        raise ValueError('collection bounds exceeded')
    result = dict(schema_version=1, repository=repository, window=dict(start=start, end=end),
                  collection=dict(status='complete', reason_codes=[], inventory_pages=0), runs=[])
    inventory = []
    try:
        for page in range(1, max_pages + 1):
            query = urlencode(dict(per_page=100, page=page, created=f'{start}..{end}'))
            data = get(f'repos/{repository}/actions/runs?{query}')
            page_runs = data['workflow_runs']
            if not isinstance(page_runs, list) or len(page_runs) > 100:
                raise ApiError('invalid-inventory-page')
            result['collection']['inventory_pages'] = page
            inventory.extend(r for r in page_runs if r.get('path') == workflow)
            if len(page_runs) < 100:
                break
        else:
            result['collection']['status'] = 'partial'
            result['collection']['reason_codes'].append('inventory-page-limit; API search caps may apply')
        if len(inventory) > max_runs:
            result['collection']['status'] = 'partial'
            result['collection']['reason_codes'].append('run-limit; latest subset is not representative')
        for run in inventory[:max_runs]:
            for attempt in range(1, int(run.get('run_attempt', 1)) + 1):
                if len(result['runs']) >= max_runs:
                    result['collection']['status'] = 'partial'
                    result['collection']['reason_codes'].append('attempt-limit')
                    break
                attempt_run = run if attempt == run.get('run_attempt', 1) else get(
                    f'repos/{repository}/actions/runs/{run["id"]}/attempts/{attempt}')
                if (attempt_run.get('id') != run['id']
                        or attempt_run.get('run_attempt') != attempt
                        or attempt_run.get('head_sha') != run.get('head_sha')
                        or attempt_run.get('path') != run.get('path')):
                    raise ApiError('native-api-provenance-mismatch')
                jobs = []
                for page in range(1, 11):
                    data = get(f'repos/{repository}/actions/runs/{run["id"]}/attempts/{attempt}/jobs?per_page=100&page={page}')
                    for job in data['jobs']:
                        try:
                            validate_job_lineage(job, attempt_run)
                        except ValueError as error:
                            raise ApiError('native-api-provenance-mismatch') from error
                    jobs.extend(data['jobs'])
                    if len(data['jobs']) < 100:
                        break
                else:
                    result['collection']['status'] = 'partial'
                    result['collection']['reason_codes'].append('job-page-limit')
                result['runs'].append({**attempt_run, 'jobs': jobs})
    except (ApiError, KeyError, TypeError, ValueError) as error:
        result['collection']['status'] = 'error' if not result['runs'] else 'partial'
        result['collection']['reason_codes'].append(error.code if isinstance(error, ApiError) else 'native-api-schema-failure')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input', type=Path, help='saved native-API capture bundle')
    source.add_argument('--repository', help='collect through existing gh authentication (GET only)')
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--workflow', default='.github/workflows/agent-os-validation.yml')
    parser.add_argument('--max-pages', type=int, default=10)
    parser.add_argument('--max-runs', type=int, default=20)
    parser.add_argument('--implementation-head', required=True)
    parser.add_argument('--expected-head')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.input:
            if args.input.stat().st_size > MAX_INPUT_BYTES:
                raise ValueError('input too large')
            bundle = json.loads(args.input.read_text())
        else:
            bundle = collect(args.repository, args.start, args.end, args.workflow, args.max_pages, args.max_runs)
        result = report(bundle, args.implementation_head, args.expected_head)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'timing.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        (args.output / 'timing.md').write_text(markdown(result))
        return 2 if result['collection'].get('status') in ('error', 'partial') else 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, 'timing report failed: ' + type(error).__name__ + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
