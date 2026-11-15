"""Credential-free loopback integration checks for issue #3761."""
import io
import threading
import unittest
import urllib.error
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from scripts import agent_os_ci_evidence_collector as collector

TOKEN = 'synthetic-redirect-probe-not-a-credential'
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, 'w') as archive:
    archive.writestr('diagnostic.txt', 'synthetic archive')
BODY = buffer.getvalue()


class DownloadRedirectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                cls.events.append((self.path, self.headers.get('Authorization')))
                if self.path.startswith('/redirect/'):
                    kind = self.path.removeprefix('/redirect/')
                    port = cls.origin.server_port if kind == 'same-origin' else cls.destination.server_port
                    host = '127.0.0.1' if kind in ('same-origin', 'different-port') else 'localhost'
                    target = '/always-401' if kind == '401' else '/redirect/cross-host' if kind == 'chain' else '/archive'
                    self.send_response(302)
                    self.send_header('Location', f'http://{host}:{port}{target}?sig=synthetic' if target == '/archive' else f'http://{host}:{port}{target}')
                    self.end_headers()
                    return
                if self.path == '/always-401' or (self.path.startswith('/archive') and self.headers.get('Authorization')):
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                self.wfile.write(BODY)

        cls.origin = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.destination = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.threads = []
        for server in (cls.origin, cls.destination):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.origin, cls.destination):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=5)

    def setUp(self):
        self.events.clear()

    def download(self, path):
        return collector._api_get_bytes(f'http://127.0.0.1:{self.origin.server_port}{path}', TOKEN)

    def assert_redirect(self, kind, expected_requests=2):
        self.assertEqual(self.download('/redirect/' + kind), BODY)
        self.assertEqual(len(self.events), expected_requests)
        self.assertEqual(self.events[0][1], 'Bearer ' + TOKEN)
        self.assertTrue(all(auth is None for _, auth in self.events[1:]), self.events)

    def test_initial_request_authenticates(self):
        self.assertEqual(self.download('/direct'), BODY)
        self.assertEqual(self.events, [('/direct', 'Bearer ' + TOKEN)])

    def test_cross_hostname_signed_url_has_no_bearer(self):
        self.assert_redirect('cross-host')

    def test_same_hostname_different_port_has_no_bearer(self):
        self.assert_redirect('different-port')

    def test_same_origin_redirect_has_no_bearer(self):
        self.assert_redirect('same-origin')

    def test_chain_does_not_reintroduce_bearer(self):
        self.assert_redirect('chain', expected_requests=3)

    def test_direct_401_remains_error(self):
        with self.assertRaisesRegex(RuntimeError, '^provider download failed: HTTP 401$'):
            self.download('/always-401')

    def test_redirected_401_remains_error(self):
        with self.assertRaisesRegex(RuntimeError, '^provider download failed: HTTP 401$'):
            self.download('/redirect/401')
        self.assertEqual(self.events[0][1], 'Bearer ' + TOKEN)
        self.assertIsNone(self.events[1][1])

    def test_size_limit_still_rejects_extra_byte(self):
        with patch.object(collector, 'MAX_ARCHIVE_BYTES', len(BODY) - 1):
            with self.assertRaisesRegex(RuntimeError, '^artifact archive exceeds size cap$'):
                self.download('/direct')

    def test_size_limit_accepts_exact_boundary(self):
        with patch.object(collector, 'MAX_ARCHIVE_BYTES', len(BODY)):
            self.assertEqual(self.download('/direct'), BODY)


if __name__ == '__main__':
    unittest.main()
