"""Real loopback HTTP/TLS/TCP probes and isolated service API round trips."""
import json
import http.cookiejar
import threading
import urllib.request
import urllib.error
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from app import registry, storage, website_checks
from website_fixture import Targets


class WebsiteChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.targets = Targets().__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.targets.__exit__()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(patch.object(storage, 'DATA_DIR', Path(temp.name)))
        self.enterContext(patch.dict(os.environ, {'SSL_CERT_FILE': str(self.targets.cert)}))
        self.targets.counts.clear()
        self.targets.headers.clear()
        self.targets.dynamic = 200

    def body(self, method='http', **kwargs):
        return {'service_type': 'external', 'scope': 'external', 'unit': '',
                'display_name': 'Example website', 'description': 'Fictional test', 'category': 'Websites',
                'open_url': self.targets.http + '/dynamic', 'website_check': {'method': method}, **kwargs}

    def test_real_http_status_codes_redirect_and_no_body(self):
        for code in (200, 204, 301, 302, 401, 403, 404, 429, 500, 503):
            with self.subTest(code=code):
                result = website_checks.check({'method': 'http'}, self.targets.http + f'/status/{code}')
                self.assertEqual(result['http_status'], code)
                self.assertEqual(result['status'], 'Running' if code < 400 or code in (401, 403) else 'Stopped')
                self.assertTrue(result['checked_at'])
        website_checks.check({'method': 'http'}, self.targets.http + '/redirect')
        self.assertEqual(self.targets.counts['/redirect-destination'], 0)
        start = time.monotonic()
        self.assertEqual(website_checks.check({'method': 'http'}, self.targets.http + '/headers-only')['status'], 'Running')
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(all('Cookie' not in headers and 'Authorization' not in headers for headers in self.targets.headers))

    def test_real_https_trust_and_hostname_validation(self):
        self.assertEqual(website_checks.check({'method': 'http'}, self.targets.https)['status'], 'Running')
        mismatch = website_checks.check({'method': 'http'}, self.targets.bad_https)
        self.assertEqual(mismatch['status'], 'Stopped')
        self.assertIn('CERTIFICATE_VERIFY_FAILED', mismatch['error'])
        # Restore default trust: this temporary CA must not be accepted globally.
        with patch.dict(os.environ, {'SSL_CERT_FILE': '/does-not-exist'}):
            self.assertEqual(website_checks.check({'method': 'http'}, self.targets.https)['status'], 'Stopped')

    def test_real_tcp_explicit_url_defaults_and_refused(self):
        result = website_checks.check({'method': 'tcp', 'address': '127.0.0.1', 'port': self.targets.tcp_port}, '')
        self.assertEqual(result['status'], 'Running')
        self.assertEqual(website_checks.check({'method': 'tcp'}, self.targets.http)['status'], 'Running')
        with socket.socket() as closed:
            closed.bind(('127.0.0.1', 0)); port = closed.getsockname()[1]
        result = website_checks.check({'method': 'tcp', 'address': '127.0.0.1', 'port': port}, '')
        self.assertEqual(result['status'], 'Stopped')
        self.assertTrue(result['error'])

    def test_timeout_and_disabled_do_not_download_or_connect(self):
        with patch.object(website_checks, 'TIMEOUT', .1):
            result = website_checks.check({'method': 'http'}, self.targets.http + '/slow')
        self.assertEqual(result['status'], 'Stopped')
        self.assertTrue(result['error'])
        self.assertIsNone(website_checks.check({}, self.targets.http + '/disabled'))
        self.assertEqual(self.targets.counts['/disabled'], 0)

    def test_validation_rejects_incomplete_tcp_and_invalid_settings(self):
        for value in ({'method': 'tcp', 'address': 'localhost'}, {'method': 'tcp', 'port': 1234},
                      {'method': 'tcp', 'address': 'localhost', 'port': True}, {'method': 'wrong'},
                      {'method': 'http'}, {'method': 'tcp', 'address': 'host;command', 'port': 1234}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                website_checks.normalize(value)
        self.assertEqual(website_checks.normalize(None), {'method': 'disabled'})
        self.assertEqual(website_checks.normalize({'method': 'http'}, managed=True, url=self.targets.http), {'method': 'http'})

    def test_real_api_add_edit_live_status_and_no_control_or_journal(self):
        import uvicorn
        from app import main
        server = uvicorn.Server(uvicorn.Config(main.app, host='127.0.0.1', port=0, log_level='error'))
        sock = socket.socket(); sock.bind(('127.0.0.1', 0))
        origin = f'http://127.0.0.1:{sock.getsockname()[1]}'
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def request(path, body=None, method=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(origin + path, data=data, method=method,
                                         headers={'Origin': origin, 'Content-Type': 'application/json'})
            try:
                response = opener.open(req, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.loads(response.read())
        with patch.dict(os.environ, {'DASHBOARD_PASSWORD': 'isolated-test-password'}):
            thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 5
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(server.started)
                self.assertEqual(request('/api/services')[0], 401)
                self.assertEqual(request('/api/login', {'password': 'isolated-test-password'})[0], 200)
                code, added = request('/api/services', self.body())
                self.assertEqual(code, 200, added)
                sid = added['service']['id']
                live = request(f'/api/services/{sid}/live')[1]['service']
                self.assertEqual(live['status'], 'Running')
                self.assertFalse(live['managed']); self.assertFalse(live['controllable'])
                self.targets.dynamic = 503
                live = request(f'/api/services/{sid}/live')[1]['service']
                self.assertEqual(live['status'], 'Stopped'); self.assertEqual(live['website_result']['http_status'], 503)
                self.assertIn('HTTP 503', request(f'/api/services/{sid}/status')[1]['status'])
                self.assertEqual(request(f'/api/services/{sid}/logs')[0], 400)
                for action in ('start', 'stop', 'restart'):
                    self.assertEqual(request(f'/api/services/{sid}/actions/{action}', {}, method='POST')[0], 400)
                edited = self.body('tcp', open_url=f'http://127.0.0.1:{self.targets.tcp_port}')
                code, result = request(f'/api/services/{sid}/edit', edited, method='PUT')
                self.assertEqual(code, 200, result)
                self.assertEqual(request(f'/api/services/{sid}/live')[1]['service']['status'], 'Running')
                self.assertEqual(registry.hosts(), [])
                request('/api/logout', {})
            finally:
                server.should_exit = True; thread.join(5); sock.close()
                self.assertFalse(thread.is_alive())

    def test_legacy_data_no_migration_and_json_export_import(self):
        from app import config_transfer, main
        entry = registry.add_service(self.body('disabled'))
        records = registry.registered_services(); records[0].pop('website_check')
        storage.write('registered-services.json', records)
        before = (storage.DATA_DIR / 'registered-services.json').read_bytes()
        with patch.object(website_checks, 'check', side_effect=AssertionError('Disabled service must not connect')):
            self.assertEqual(main._decorate_services(main.systemd.get_services(entry['id']))[0]['status'], 'Linked')
        self.assertEqual((storage.DATA_DIR / 'registered-services.json').read_bytes(), before)
        registry.update_service(entry['id'], self.body('tcp', open_url=f'http://127.0.0.1:{self.targets.tcp_port}'))
        document = config_transfer.export_config('service', entry['id'])
        settings = document['services'][0]['website_check']
        self.assertEqual(settings['port'], self.targets.tcp_port)
        storage.write('registered-services.json', [])
        config_transfer.import_config(document)
        self.assertEqual(registry.registered_services()[0]['website_check'], settings)
        document['services'][0].pop('website_check')
        preview = config_transfer.import_config(document, dry_run=True)
        config_transfer.import_config(document, overwrite=True, preview_token=preview['preview_token'])
        self.assertEqual(registry.registered_services()[0]['website_check'], {'method': 'disabled'})
