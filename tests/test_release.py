import os
import tempfile
import unittest

TEMP = tempfile.TemporaryDirectory(prefix='dashboard-acceptance-')
os.environ['DASHBOARD_DATA_DIR'] = TEMP.name
os.environ['DASHBOARD_PASSWORD'] = 'isolated-test-password'

from app import catalog
from app.main import LoginBody
from pydantic import ValidationError


class ReleaseBasics(unittest.TestCase):
    def test_clean_catalog_only_dashboard(self):
        self.assertEqual(list(catalog.SERVICE_BY_ID), ['host-service-dashboard.service'])

    def test_password_boundaries(self):
        for value in ('a', 'a' * 256, '😀' * 256):
            self.assertEqual(LoginBody(password=value).password, value)
        for value in ('', 'a' * 257, 'a\nb', 'a\x00b', '\ud800'):
            with self.assertRaises(ValidationError):
                LoginBody(password=value)

class StorageSafety(unittest.TestCase):
    def setUp(self):
        from app import storage
        self.storage = storage
        self.temp = tempfile.TemporaryDirectory()
        self.original = storage.DATA_DIR
        storage.DATA_DIR = __import__('pathlib').Path(self.temp.name)

    def tearDown(self):
        self.storage.DATA_DIR = self.original
        self.temp.cleanup()

    def test_parallel_updates(self):
        from concurrent.futures import ThreadPoolExecutor
        def update(i):
            with self.storage.LOCK:
                values = self.storage.read('counter.json', {})
                values[str(i)] = i
                self.storage.write('counter.json', values)
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(update, range(100)))
        self.assertEqual(len(self.storage.read('counter.json', {})), 100)

    def test_transaction_failure_and_recovery(self):
        from unittest.mock import patch
        for failed in range(3):
            for i in range(3): self.storage.write(f'{i}.json', {'old': i})
            real = self.storage._replace_bytes
            calls = 0
            def fail_once(path, content):
                nonlocal calls
                if path.name in ('0.json', '1.json', '2.json'):
                    calls += 1
                    if calls == failed + 1: raise OSError('injected')
                return real(path, content)
            with patch.object(self.storage, '_replace_bytes', side_effect=fail_once):
                with self.assertRaises(OSError):
                    with self.storage.transaction():
                        for i in range(3): self.storage.write(f'{i}.json', {'new': i})
            for i in range(3): self.assertEqual(self.storage.read(f'{i}.json', {}), {'old': i})

class StreamingLimits(unittest.IsolatedAsyncioTestCase):
    async def test_oversize_stream_stops_reading(self):
        from app.main import _read_service_config
        from fastapi import HTTPException
        from starlette.requests import Request
        chunks = [b' ' * (1024 * 1024), b'x', b'never read']
        reads = 0
        async def receive():
            nonlocal reads
            data = chunks[reads]; reads += 1
            return {'type': 'http.request', 'body': data, 'more_body': True}
        scope = {'type': 'http', 'method': 'POST', 'path': '/', 'scheme': 'http', 'headers': [(b'host', b'localhost'), (b'origin', b'http://localhost')]}
        with self.assertRaises(HTTPException) as caught:
            await _read_service_config(Request(scope, receive))
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(reads, 2)

    async def test_silent_stream_revocation_terminates_process(self):
        import asyncio, sys
        from unittest.mock import patch
        from app import systemd
        valid = True
        processes = []
        spawn = asyncio.create_subprocess_exec
        async def tracked(*args, **kwargs):
            process = await spawn(*args, **kwargs); processes.append(process); return process
        async def disconnected(): return False
        async def revoke():
            nonlocal valid
            await asyncio.sleep(.1); valid = False
        with patch.object(systemd, '_journal_command', return_value=[sys.executable, '-u', '-c', 'import time; time.sleep(60)']), patch.object(systemd.asyncio, 'create_subprocess_exec', tracked):
            iterator = systemd.stream_logs('example.service', session_valid=lambda: valid, disconnected=disconnected, check_interval=.02)
            task = asyncio.create_task(revoke())
            async def consume():
                return [line async for line in iterator]
            self.assertEqual(await asyncio.wait_for(consume(), 2), [])
            await task
        self.assertIsNotNone(processes[0].returncode)

# Child processes import this module under spawn, so all actual work uses the explicit isolated path.
def process_update(directory, index):
    from pathlib import Path
    from app import storage
    storage.DATA_DIR = Path(directory)
    for offset in range(8):
        with storage.LOCK:
            record = storage.read('processes.json', {})
            record[f'{index}-{offset}'] = True
            storage.write('processes.json', record)


def process_crash(directory):
    from pathlib import Path
    from app import storage
    storage.DATA_DIR = Path(directory)
    real = storage._replace_bytes
    def interrupted(path, content):
        real(path, content)
        if path.name == 'a.json': os._exit(23)
    storage._replace_bytes = interrupted
    with storage.transaction():
        storage.write('a.json', {'new': True})
        storage.write('b.json', {'new': True})


class MoreStorageSafety(StorageSafety):
    def test_process_lock(self):
        import multiprocessing
        ctx = multiprocessing.get_context('spawn')
        workers = [ctx.Process(target=process_update, args=(self.temp.name, i)) for i in range(4)]
        for worker in workers: worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(len(self.storage.read('processes.json', {})), 32)

    def test_crash_recovery(self):
        import multiprocessing
        self.storage.write('a.json', {'old': True})
        self.storage.write('b.json', {'old': True})
        worker = multiprocessing.get_context('spawn').Process(target=process_crash, args=(self.temp.name,))
        worker.start(); worker.join(10)
        self.assertEqual(worker.exitcode, 23)
        self.assertEqual(self.storage.read('a.json', {}), {'old': True})
        self.assertEqual(self.storage.read('b.json', {}), {'old': True})

    def test_import_each_file_failure(self):
        from app import config_transfer
        from unittest.mock import patch
        record = {'service_type':'external','scope':'external','unit':'','display_name':'Example site','category':'Websites','open_url':'https://example.com','favorite':True}
        document = {'format':config_transfer.FORMAT,'version':1,'services':[record]}
        files = {'hosts.json':[], 'registered-services.json':[], 'service-metadata.json':{}, 'service-names.json':{}, 'service-open-urls.json':{}, 'service-ports.json':{}, 'service-favorites.json':[]}
        for failed in range(len(files)):
            for name,value in files.items(): self.storage.write(name,value)
            count = 0
            original = self.storage._replace_bytes
            def fail_once(path, content):
                nonlocal count
                if path.name in files:
                    count += 1
                    if count == failed+1: raise OSError('injected import error')
                return original(path,content)
            with patch.object(self.storage,'_replace_bytes', side_effect=fail_once):
                with self.assertRaises(OSError): config_transfer.import_config(document)
            for name,value in files.items(): self.assertEqual(self.storage.read(name,None),value)
        result=config_transfer.import_config(document)
        self.assertEqual(result['added'],1)
        self.assertEqual(len(self.storage.read('registered-services.json',[])),1)

    def test_alias_and_favorite_parallel_updates(self):
        from concurrent.futures import ThreadPoolExecutor
        from app import service_names, service_favorites, service_ports, service_urls
        entries=[{'id':f'example-{i}.service','scope':'user','name':f'Example {i}','category':'Tools'} for i in range(30)]
        self.storage.write('local-catalog.json',entries)
        def update(entry):
            service_names.set_display_name(entry['id'], 'Alias '+entry['id'])
            service_favorites.set_favorite(entry['id'],True)
            service_ports.set_port(entry['id'],9000)
            service_urls.set_url(entry['id'],'https://example.com')
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(update,entries))
        for name in ('service-names.json','service-favorites.json','service-ports.json','service-open-urls.json'):
            self.assertEqual(len(self.storage.read(name,None)),30)

    def test_local_catalog_and_generic_export(self):
        self.storage.write('local-catalog.json',[{'id':'example-web.service','scope':'user','name':'Example web','category':'Websites','control_allowed':False}])
        from app import catalog,config_transfer
        self.assertEqual(len(catalog.SERVICE_BY_ID),2)
        self.assertFalse(catalog.SERVICE_BY_ID['example-web.service']['control_allowed'])
        self.assertEqual(len(config_transfer.export_config()['services']),2)


class SessionSafety(unittest.TestCase):
    def test_revocation_file_change_and_expiration(self):
        from app import security,storage
        from unittest.mock import patch
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temporary, patch.object(storage,'DATA_DIR',Path(temporary)):
            token=security.login('isolated-test-password','test-client')
            self.assertTrue(security.token_is_valid(token))
            security.logout(token)
            self.assertFalse(security.token_is_valid(token))
            token=security.login('isolated-test-password','test-client')
            storage.write('sessions.json',{})
            self.assertFalse(security.token_is_valid(token))
            token=security.login('isolated-test-password','test-client')
            with patch.object(security.time,'time',return_value=__import__('time').time()+security.SESSION_TTL+1):
                self.assertFalse(security.token_is_valid(token))

    def test_installer_rejects_invalid_before_confirmation(self):
        from scripts import lifecycle
        from unittest.mock import patch
        import io
        old={'DASHBOARD_PASSWORD':'valid-old'}
        with patch.object(lifecycle.getpass,'getpass',side_effect=['x'*257,'ok','ok']) as getpass, patch('builtins.input',side_effect=['','','','y']), patch('sys.stdout',new_callable=io.StringIO) as out:
            values,mode=lifecycle.get_settings(old,{},True)
        self.assertEqual(values['DASHBOARD_PASSWORD'],'ok')
        self.assertIn('1–256',out.getvalue())
        self.assertEqual(getpass.call_count,3)

class MoreStreamingLimits(unittest.IsolatedAsyncioTestCase):
    async def request_document(self, chunks, length=None):
        from starlette.requests import Request
        from app.main import _read_service_config
        headers=[(b'host',b'localhost'),(b'origin',b'http://localhost')]
        if length is not None: headers.append((b'content-length',str(length).encode()))
        self.reads=0
        async def receive():
            data=chunks[self.reads]; self.reads+=1
            return {'type':'http.request','body':data,'more_body':self.reads<len(chunks)}
        scope={'type':'http','method':'POST','path':'/','scheme':'http','headers':headers}
        return await _read_service_config(Request(scope,receive))

    async def test_body_boundaries_and_false_length(self):
        from fastapi import HTTPException
        self.assertEqual(await self.request_document([b'{}'+b' '*(1024*1024-2)]),{})
        with self.assertRaises(HTTPException) as caught:
            await self.request_document([b'{}'],1024*1024+1)
        self.assertEqual(caught.exception.status_code,413); self.assertEqual(self.reads,0)
        with self.assertRaises(HTTPException) as caught:
            await self.request_document([b' '*(1024*1024),b'x',b'not read'],1)
        self.assertEqual(caught.exception.status_code,413); self.assertEqual(self.reads,2)
        with self.assertRaises(HTTPException) as caught:
            await self.request_document([b'not json'])
        self.assertEqual(caught.exception.status_code,400)

    async def stream_scenario(self, code, reason, *, silent=False):
        import asyncio,sys,time
        from unittest.mock import patch
        from app import systemd,security,storage
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory, patch.object(storage,'DATA_DIR',Path(directory)):
            token=security.login('isolated-test-password','test-client')
            gone=False
            async def disconnected():return gone
            processes=[]
            spawn=asyncio.create_subprocess_exec
            async def tracked(*args,**kwargs):
                process=await spawn(*args,**kwargs);processes.append(process);return process
            with patch.object(systemd,'_journal_command',return_value=[sys.executable,'-u','-c',code]), patch.object(systemd.asyncio,'create_subprocess_exec',tracked):
                iterator=systemd.stream_logs('simulated-remote.service',session_valid=lambda:security.token_is_valid(token),disconnected=disconnected,check_interval=.02)
                async def consume(): return [line async for line in iterator]
                task=asyncio.create_task(consume())
                await asyncio.sleep(.12)
                if reason=='logout':security.logout(token)
                elif reason=='expired':storage.write('sessions.json',{security._token_hash(token):time.time()-1})
                elif reason=='disconnect':gone=True
                else:task.cancel()
                if reason=='cancel':
                    with self.assertRaises(asyncio.CancelledError):await asyncio.wait_for(task,4)
                else:
                    lines=await asyncio.wait_for(task,4)
                    if not silent:self.assertTrue(lines)
                self.assertIsNotNone(processes[0].returncode)
                return processes[0].returncode

    async def test_active_stream_logout(self):
        await self.stream_scenario('import time\nwhile True:\n print("sample");time.sleep(.01)','logout')

    async def test_silent_stream_expired(self):
        await self.stream_scenario('import time;time.sleep(60)','expired',silent=True)

    async def test_silent_stream_disconnect(self):
        await self.stream_scenario('import time;time.sleep(60)','disconnect',silent=True)

    async def test_cancel_cleans_process(self):
        await self.stream_scenario('import time;time.sleep(60)','cancel',silent=True)

    async def test_unresponsive_process_is_killed(self):
        import signal
        result=await self.stream_scenario('import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready");time.sleep(60)','logout')
        self.assertEqual(result,-signal.SIGKILL)

class HTTPAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import socket,subprocess,sys,time,urllib.request,json
        cls.temp=tempfile.TemporaryDirectory()
        cls.socket=socket.socket();cls.socket.bind(('127.0.0.1',0))
        cls.base=f'http://127.0.0.1:{cls.socket.getsockname()[1]}'
        env={**os.environ,'DASHBOARD_DATA_DIR':cls.temp.name,'DASHBOARD_PASSWORD':'isolated-http-password'}
        cls.log=tempfile.TemporaryFile()
        cls.process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--fd',str(cls.socket.fileno())],env=env,pass_fds=[cls.socket.fileno()],stdout=cls.log,stderr=cls.log)
        cls.socket.close()
        for _ in range(50):
            try:
                with urllib.request.urlopen(cls.base+'/api/session',timeout=.5) as r: json.load(r)
                break
            except OSError:time.sleep(.1)
        else:
            cls.process.terminate();cls.process.wait();raise RuntimeError('Isolated HTTP server failed to start')
        cls.cookie=''
        request=urllib.request.Request(cls.base+'/api/login',data=json.dumps({'password':'isolated-http-password'}).encode(),headers={'Content-Type':'application/json','Origin':cls.base})
        with urllib.request.urlopen(request) as r:cls.cookie=r.headers['Set-Cookie'].split(';')[0]

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate();cls.process.wait(timeout=5);cls.log.close();cls.temp.cleanup()

    def request(self,path,body=None,method=None):
        import urllib.request,json
        request=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Origin':self.base,'Cookie':self.cookie,'Content-Type':'application/json'},method=method)
        with urllib.request.urlopen(request,timeout=5) as result:return json.load(result)

    def test_clean_export_and_import_edit(self):
        exported=self.request('/api/services/export')
        self.assertEqual([s['unit'] for s in exported['services']],['host-service-dashboard.service'])
        record={'service_type':'external','scope':'external','unit':'','display_name':'Demo','category':'Websites','open_url':'https://example.com','favorite':True,'description':'Example','port':None}
        document={'format':'host-service-dashboard-services','version':1,'services':[record]}
        self.assertEqual(self.request('/api/services/import/preview',document)['added'],1)
        self.assertEqual(self.request('/api/services/import',document)['added'],1)
        self.assertEqual(self.request('/api/services/import/preview',document)['conflicts'][0]['name'],'Demo')
        entry=next(s for s in self.request('/api/services/export')['services'] if s['scope']=='external')
        record['display_name']='Edited'
        self.assertTrue(self.request('/api/services/'+entry['source_id']+'/edit',record,'PUT')['ok'])
        self.assertEqual(self.request('/api/services/export?selection=service&value='+entry['source_id'])['services'][0]['display_name'],'Edited')

    def test_api_password_and_size_rejection(self):
        import urllib.error,urllib.request
        for password in ('','a'*257,'a\nb'):
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/login',{'password':password})
            self.assertEqual(caught.exception.code,422)
        request=urllib.request.Request(self.base+'/api/services/import',data=b' '*(1024*1024+1),headers={'Origin':self.base,'Cookie':self.cookie,'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code,413)

class ASGICancellation(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_anyio_scope_still_reaps_child(self):
        import anyio,asyncio,sys
        from unittest.mock import patch
        from app import systemd
        processes=[];started=anyio.Event();spawn=asyncio.create_subprocess_exec
        async def tracked(*args,**kwargs):
            process=await spawn(*args,**kwargs);processes.append(process);started.set();return process
        async def consume():
            async for _ in systemd.stream_logs('example.service',session_valid=lambda:True,check_interval=.02):pass
        with patch.object(systemd,'_journal_command',return_value=[sys.executable,'-c','import time;time.sleep(60)']),patch.object(systemd.asyncio,'create_subprocess_exec',tracked):
            async with anyio.create_task_group() as group:
                group.start_soon(consume)
                await started.wait()
                await anyio.sleep(.03)
                group.cancel_scope.cancel()
        self.assertIsNotNone(processes[0].returncode)
