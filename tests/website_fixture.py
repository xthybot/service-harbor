"""Temporary HTTP/TLS/TCP targets for website checks; never uses installed data."""
import collections
import json
import os
from pathlib import Path
import socketserver
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class Targets:
    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory(prefix='harbor-web-targets-')
        self.root = Path(self.temp.name)
        self.counts = collections.Counter()
        self.headers = []
        self.dynamic = 200
        self.servers = []
        self.threads = []
        targets = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                path = urlsplit(self.path).path
                if path == '/_metrics':
                    body = json.dumps(dict(targets.counts)).encode()
                    self.send_response(200); self.end_headers(); self.wfile.write(body)
                    return
                if path.startswith('/_set/'):
                    targets.dynamic = int(path.rsplit('/', 1)[-1])
                    self.send_response(204); self.end_headers()
                    return
                targets.counts[path] += 1
                targets.headers.append(dict(self.headers))
                if path == '/slow':
                    time.sleep(1)
                code = targets.dynamic if path == '/dynamic' else 302 if path == '/redirect' else int(path.rsplit('/', 1)[-1]) if path.startswith('/status/') else 200
                self.send_response(code)
                if path == '/redirect':
                    self.send_header('Location', '/redirect-destination')
                if path == '/headers-only':
                    self.send_header('Content-Length', '100000000')
                self.end_headers()
                # Deliberately no body: clients must not download it.
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self._start(http)
        self.http = f'http://127.0.0.1:{http.server_port}'
        cert, key = self.root / 'cert.pem', self.root / 'key.pem'
        subprocess.run(['/usr/bin/openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost'], check=True, capture_output=True)
        self.cert = cert
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        https = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        https.socket = context.wrap_socket(https.socket, server_side=True)
        self._start(https)
        self.https = f'https://localhost:{https.server_port}'
        self.bad_https = f'https://127.0.0.1:{https.server_port}'
        class TCP(socketserver.BaseRequestHandler):
            def handle(self):
                pass
        tcp = socketserver.ThreadingTCPServer(('127.0.0.1', 0), TCP)
        self._start(tcp)
        self.tcp_port = tcp.server_address[1]
        return self

    def _start(self, server):
        self.servers.append(server)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start(); self.threads.append(thread)

    def __exit__(self, *args):
        for server in self.servers:
            server.shutdown(); server.server_close()
        for thread in self.threads:
            thread.join(2)
        self.temp.cleanup()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18769)
    parser.add_argument('--managed', action='store_true', help='Synthetic units; never executes systemd or SSH')
    args = parser.parse_args()
    with Targets() as targets:
        os.environ['DASHBOARD_DATA_DIR'] = str(targets.root / 'data')
        os.environ['DASHBOARD_PASSWORD'] = 'isolated-browser-only'
        os.environ['DASHBOARD_PORT'] = str(args.port)
        os.environ['SSL_CERT_FILE'] = str(targets.cert)
        from app import catalog, storage
        # No installed systemd/SSH services are queried by this fixture.
        catalog.SERVICES.clear()
        storage.write('registered-services.json', [
            {'id': 'svc-legacy', 'name': 'Legacy website', 'scope': 'external', 'unit': '',
             'service_type': 'external', 'category': 'Websites', 'description': 'Old record without website_check',
             'open_url': targets.http + '/legacy', 'favorite': True},
        ])
        if args.managed:
            from app import systemd, manual_ports
            from datetime import datetime, timezone
            import socket
            closed_ports = []
            for _ in range(2):
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0)); closed_ports.append(sock.getsockname()[1])
            def fixture_properties(entries):
                return {entry['id']: {'props': {'Id': entry.get('unit', entry['id']), 'LoadState': 'loaded',
                          'ActiveState': entry.get('fixture_state', 'active'), 'SubState': entry.get('fixture_state', 'active'),
                          'Description': 'Synthetic fixture unit', 'ActiveEnterTimestamp': '2026-10-17 00:00:00 UTC'},
                          'error': '', 'checked_at': datetime.now(timezone.utc).isoformat()} for entry in entries}
            systemd._group_properties = fixture_properties
            def no_commands(*args, **kwargs):
                raise ValueError('Fixture forbids real systemd/SSH execution.')
            systemd._execute = no_commands
            systemd._run = no_commands
            systemd.control_service = no_commands
            systemd.get_status = lambda service_id: 'Synthetic systemd unit status (no real commands executed)'
            systemd.get_recent_log_snapshot = lambda service_id, *args, **kwargs: {'lines': ['Synthetic fixture log'], 'cursor': None, 'identity': systemd.journal_identity(service_id)}
            async def fixture_stream(*args, session_valid=None, disconnected=None, **kwargs):
                import asyncio
                while True:
                    if session_valid and not session_valid(): return
                    if disconnected and await disconnected(): return
                    await asyncio.sleep(1)
                    if False: yield None
            systemd.stream_logs = fixture_stream
            rows = []
            for suffix, state in [('running', 'active'), ('failed', 'failed'), ('stopped', 'inactive')]:
                rows.append({'id': 'svc-managed-' + suffix, 'name': 'Managed ' + suffix, 'scope': 'user',
                             'unit': 'fixture-' + suffix + '.service', 'service_type': 'local', 'host_id': 'local',
                             'category': 'Websites', 'description': 'Synthetic unit with real HTTP check',
                             'open_url': targets.http + '/status/503', 'port': closed_ports[0] if suffix == 'running' else None,
                             'website_check': {'method': 'http'}, 'fixture_state': state, 'control_allowed': False})
            rows.append({'id': 'svc-website', 'name': 'Website only', 'scope': 'external', 'unit': '',
                         'service_type': 'external', 'category': 'Websites', 'description': 'Unmanaged HTTP check',
                         'open_url': targets.http + '/status/503', 'website_check': {'method': 'http'}})
            storage.write('registered-services.json', rows)
            storage.write('manual-ports.json', [
                {'id': 'port-standalone', 'name': 'Standalone port', 'host_id': 'local', 'host_name': 'This host', 'address': '127.0.0.1', 'port': closed_ports[1], 'source': 'fixture'},
                {'id': 'port-associated', 'name': 'Associated port', 'host_id': 'local', 'host_name': 'This host', 'address': '127.0.0.1', 'port': closed_ports[0], 'source': 'fixture'},
            ])
            original_probe = manual_ports._probe
            def counted_probe(address, port):
                targets.counts['/_tcp_probe'] += 1
                return original_probe(address, port)
            manual_ports._probe = counted_probe
        print(json.dumps({'dashboard': f'http://127.0.0.1:{args.port}', 'http': targets.http,
                          'https': targets.https, 'bad_https': targets.bad_https,
                          'tcp_port': targets.tcp_port, 'data': str(storage.DATA_DIR)}), flush=True)
        import uvicorn
        uvicorn.run('app.main:app', host='0.0.0.0', port=args.port, log_level='warning')
