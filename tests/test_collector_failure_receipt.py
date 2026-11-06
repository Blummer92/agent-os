"""Download failures must persist truthful receipts and remain unsuccessful."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from scripts import agent_os_ci_evidence_collector as collector

HEAD = 'b' * 40
PRIVATE = 'synthetic-private-marker'


def archive(name, data):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr(name, data)
    return output.getvalue()


def report(tool='pyan3'):
    return archive(tool + '-advisory.json', json.dumps({
        'schema': 'agent-os-' + tool + '-advisory/1', 'tool': tool,
        'status': 'ok', 'head_sha': HEAD,
    }))


def artifact(artifact_id, name, **fields):
    return dict(id=artifact_id, name=name, expired=False,
                workflow_run={'id': 100, 'head_sha': HEAD},
                archive_download_url=f'https://example.invalid/{artifact_id}?sig={PRIVATE}',
                **fields)


class FailureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.run = {'id': 100, 'head_sha': HEAD, 'status': 'completed',
                    'path': '.github/workflows/agent-os-validation.yml'}
        self.jobs = [dict(id=i, name=name, run_id=100, run_attempt=2,
                          status='completed', conclusion='success', steps=[])
                     for i, name in enumerate(['pyan3 call-graph advisory',
                         'jscpd duplicate-code advisory', 'Run aggregate validation'], 1)]
        self.artifacts = [artifact(11, 'pyan3-advisory-1-attempt-2')]

    def invoke(self, download):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'nested/collector-receipt.json'
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {'GITHUB_TOKEN': PRIVATE,
                    'GITHUB_REPOSITORY': 'Blummer92/agent-os', 'GITHUB_SHA': 'c' * 40}, clear=True), \
                 patch.object(collector, '_api_get', return_value=(self.run, {})), \
                 patch.object(collector, '_paginate', side_effect=[self.jobs, self.artifacts]), \
                 patch.object(collector, '_api_get_bytes', side_effect=download), \
                 contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = collector.main(['--source-run-id', '100', '--source-head', HEAD,
                    '--source-attempt', '2', '--output', str(output)])
            receipt = json.loads(output.read_text()) if output.exists() else None
            logs = stdout.getvalue() + stderr.getvalue()
            self.assertNotIn(PRIVATE, logs)
            self.assertNotIn('example.invalid', logs)
            return code, receipt

    def assert_failed_receipt(self, download, status=None):
        code, receipt = self.invoke(download)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['collection_status'], 'DOWNLOAD_FAILED')
        self.assertEqual(receipt['download_errors'], [{'artifact_id': '11',
            'stage': 'artifact_download', 'http_status': status}])
        self.assertEqual(receipt['streams']['pyan']['classification'], 'PROVIDER_UNAVAILABLE')
        self.assertEqual(receipt['source_run_id'], 100)
        self.assertEqual(receipt['source_run_attempt'], 2)
        self.assertEqual(receipt['source_head'], HEAD)
        self.assertFalse(receipt['sheets_written'])
        return receipt

    def test_wrapped_http_401_preserves_status_without_error_text(self):
        def download(*args):
            try:
                raise urllib.error.HTTPError('https://example.invalid/?sig=' + PRIVATE,
                    401, PRIVATE, {}, None)
            except urllib.error.HTTPError as error:
                raise RuntimeError(PRIVATE) from error
        self.assert_failed_receipt(download, 401)

    def test_direct_http_403(self):
        self.assert_failed_receipt(urllib.error.HTTPError('https://example.invalid', 403, PRIVATE, {}, None), 403)

    def test_transport_timeout_and_size_errors_write_receipts(self):
        for error in [urllib.error.URLError(PRIVATE), TimeoutError(PRIVATE),
                      ConnectionResetError(PRIVATE), RuntimeError('artifact archive exceeds size cap')]:
            with self.subTest(error=type(error).__name__):
                self.assert_failed_receipt(error)

    def test_other_downloads_continue_and_keep_verified_evidence(self):
        self.artifacts.append(artifact(12, 'junit-aggregate-2'))
        junit = archive('junit.xml', '<testsuite name="suite" tests="1" failures="0" errors="0" skipped="0"><testcase classname="c" name="test"/></testsuite>')
        code, receipt = self.invoke([RuntimeError(PRIVATE), junit])
        self.assertEqual(code, 1)
        self.assertEqual(receipt['streams']['pyan']['classification'], 'PROVIDER_UNAVAILABLE')
        self.assertEqual(receipt['streams']['aggregate']['classification'], 'EVIDENCE_VALID')
        self.assertEqual(len(receipt['download_errors']), 1)

    def test_multiple_failures_are_each_recorded(self):
        self.artifacts.append(artifact(12, 'jscpd-advisory-1-attempt-2'))
        code, receipt = self.invoke([RuntimeError(PRIVATE), TimeoutError(PRIVATE)])
        self.assertEqual(code, 1)
        self.assertEqual([e['artifact_id'] for e in receipt['download_errors']], ['11', '12'])
        self.assertEqual(receipt['streams']['jscpd']['classification'], 'PROVIDER_UNAVAILABLE')

    def test_success_receipt_keeps_original_shape(self):
        code, receipt = self.invoke([report()])
        self.assertEqual(code, 0)
        self.assertNotIn('download_errors', receipt)
        self.assertNotIn('collection_status', receipt)
        self.assertEqual(receipt['streams']['pyan']['classification'], 'EVIDENCE_VALID')

    def test_integrity_rejections_survive_other_download_failure(self):
        data = report('jscpd')
        for fields, expected in [
            ({'digest': 'sha256:' + '0' * 64}, 'REJECT_DIGEST'),
            ({'workflow_run': {'id': 100, 'head_sha': 'a' * 40}}, 'REJECT_WRONG_HEAD'),
            ({'name': 'jscpd-advisory-1-attempt-1'}, 'REJECT_WRONG_ATTEMPT'),
        ]:
            with self.subTest(expected=expected):
                other = artifact(12, 'jscpd-advisory-1-attempt-2')
                other.update(fields)
                self.artifacts = [self.artifacts[0], other]
                code, receipt = self.invoke([RuntimeError(PRIVATE), data])
                self.assertEqual(code, 1)
                self.assertEqual(receipt['streams']['jscpd']['classification'], expected)

    def test_verified_scanner_failure_keeps_precedence(self):
        self.artifacts.append(artifact(13, 'pyan3-health-1-attempt-2'))
        health = archive('pyan3-health.json', json.dumps({
            'schema': 'agent-os-ci-evidence-health/1', 'run_id': 100,
            'run_attempt': 2, 'head_sha': HEAD, 'classification': 'REJECT_SCANNER_ERROR'}))
        code, receipt = self.invoke([RuntimeError(PRIVATE), health])
        self.assertEqual(code, 1)
        self.assertEqual(receipt['streams']['pyan']['classification'], 'REJECT_SCANNER_ERROR')
        self.assertEqual(receipt['collection_status'], 'DOWNLOAD_FAILED')

    def test_real_http_401_produces_receipt(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(401)
                self.end_headers()

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        actual_download = collector._api_get_bytes
        self.artifacts[0]['archive_download_url'] = f'http://127.0.0.1:{server.server_port}/archive?sig={PRIVATE}'
        try:
            # Keep this controlled request on loopback even when the host
            # has proxy configuration and the credential fixture clears env.
            opener = collector.urllib.request.build_opener(collector.urllib.request.ProxyHandler({}))
            with patch.object(collector.urllib.request, 'urlopen', side_effect=opener.open):
                self.assert_failed_receipt(actual_download, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_missing_artifact_run_id_cannot_match_run_one(self):
        item = artifact(11, 'pyan3-advisory-1-attempt-2')
        item['workflow_run'] = {'head_sha': HEAD}
        result = collector.classify_advisory_artifact(
            stream='pyan', artifact=item, zip_bytes=report(), expected_head=HEAD,
            job=self.jobs[0], source_run_id=1, source_attempt=2,
        )
        self.assertEqual(result['classification'], 'REJECT_WRONG_HEAD')

    def test_missing_or_malformed_download_url_writes_receipt(self):
        actual_download = collector._api_get_bytes
        for value in (None, '://malformed-' + PRIVATE):
            with self.subTest(url_present=value is not None):
                if value is None:
                    self.artifacts[0].pop('archive_download_url', None)
                else:
                    self.artifacts[0]['archive_download_url'] = value
                self.assert_failed_receipt(actual_download)

    def test_http_protocol_errors_write_receipts(self):
        for error in (http.client.IncompleteRead(b'partial', 10),
                      http.client.BadStatusLine(PRIVATE)):
            with self.subTest(error=type(error).__name__):
                self.assert_failed_receipt(error)

    def test_real_truncated_chunked_response_writes_receipt(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                # Declare five bytes, supply three, and close without a
                # terminating chunk. HTTPResponse.read raises IncompleteRead.
                self.wfile.write(b'5\r\nabc')
                self.wfile.flush()
                self.close_connection = True

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        actual_download = collector._api_get_bytes
        self.artifacts[0]['archive_download_url'] = f'http://127.0.0.1:{server.server_port}/archive?sig={PRIVATE}'
        try:
            opener = collector.urllib.request.build_opener(collector.urllib.request.ProxyHandler({}))
            with patch.object(collector.urllib.request, 'urlopen', side_effect=opener.open):
                self.assert_failed_receipt(actual_download)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
