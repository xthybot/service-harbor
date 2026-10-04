"""Journal continuation and identity isolation; no systemd or SSH is invoked."""
import asyncio
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import storage, systemd


def record(cursor, message='same message'):
    return json.dumps({'__CURSOR': cursor, '__REALTIME_TIMESTAMP': '1700000000000000',
                       'MESSAGE': message, 'SYSLOG_IDENTIFIER': 'demo', 'PRIORITY': '6'}) + '\n'


class JournalSnapshot(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, 'DATA_DIR', Path(self.temp.name)))
        self.services = {'demo': {'id': 'demo', 'unit': 'demo.service', 'scope': 'system', 'name': 'Demo'}}
        self.enterContext(patch.object(systemd, 'SERVICE_BY_ID', self.services))

    def test_recent_returns_unfiltered_last_cursor_and_preserves_same_text_events(self):
        with patch.object(systemd, '_run', return_value=subprocess.CompletedProcess([], 0, record('c1')+record('c2')+record('c3','other'), '')):
            result = systemd.get_recent_log_snapshot('demo', 150, 'same')
        self.assertEqual(len(result['lines']), 2)
        self.assertEqual(result['lines'][0], result['lines'][1])
        self.assertEqual(result['cursor'], 'c3')
        self.assertTrue(result['identity'])

    def test_remote_command_keeps_cursor_as_one_quoted_transport_argument(self):
        self.services['demo'].update(service_type='remote', host_id='remote')
        with patch.object(systemd.ssh_hosts, 'ssh_command', side_effect=lambda host, args: ['ssh-mock', *args]):
            command = systemd._journal_command('demo', 0, True, cursor='s=123;i=456', json_output=True)
        self.assertIn('--cursor=s=123;i=456', command)
        self.assertIn('json', command)
        self.assertEqual(command[0], 'ssh-mock')
        self.assertIn('--follow', command)

    def test_cursor_cannot_inject_sse_lines(self):
        for cursor in ('evil\nid: injected', 'a'*4097, '\x00', '非ASCII'):
            with self.subTest(cursor=cursor[:10]), self.assertRaises(ValueError):
                systemd._journal_command('demo', 0, True, cursor=cursor, json_output=True)

    def test_snapshot_rejects_identity_changed_while_probe_is_running(self):
        def run(*args, **kwargs):
            self.services['demo']['unit'] = 'other.service'
            return subprocess.CompletedProcess([], 0, record('c1'), '')
        with patch.object(systemd, '_run', side_effect=run), self.assertRaisesRegex(ValueError, 'changed'):
            systemd.get_recent_log_snapshot('demo')

    def test_service_list_exposes_execution_identity_that_changes_with_remote_host(self):
        self.services['demo'].update(service_type='remote', host_id='remote')
        host = {'id':'remote','address':'192.0.2.1','username':'operator','port':22,'trusted':True}
        with patch.object(systemd.registry, 'hosts', side_effect=lambda:[dict(host)]), \
             patch.object(systemd.registry, 'host', side_effect=lambda _:dict(host)), \
             patch.object(systemd, '_group_properties', return_value={}):
            first = systemd.get_services(only_id='demo')[0]['execution_identity']
            host['address'] = '192.0.2.2'
            second = systemd.get_services(only_id='demo')[0]['execution_identity']
        self.assertNotEqual(first, second)


class FakeProcess:
    def __init__(self, lines=(), *, eof=True):
        self.stdout = asyncio.StreamReader()
        for line in lines: self.stdout.feed_data(line.encode())
        if eof: self.stdout.feed_eof()
        self.returncode = None
        self.terminated = False
    def terminate(self): self.terminated = True; self.returncode = -15; self.stdout.feed_eof()
    def kill(self): self.returncode = -9; self.stdout.feed_eof()
    async def wait(self): return self.returncode


class JournalStream(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.enterContext(patch.object(storage, 'DATA_DIR', Path(self.temp.name)))
        self.services = {'demo': {'id': 'demo', 'unit': 'demo.service', 'scope': 'system', 'name': 'Demo'}}
        self.enterContext(patch.object(systemd, 'SERVICE_BY_ID', self.services))

    async def consume(self, process, **kwargs):
        with patch.object(systemd.asyncio, 'create_subprocess_exec', return_value=process):
            return [event async for event in systemd.stream_logs('demo', 0, structured=True, check_interval=.01, **kwargs)]

    async def test_resume_skips_only_exact_cursor_and_keeps_equal_text(self):
        process = FakeProcess([record('c1'), record('c2'), record('c3')])
        events = await self.consume(process, cursor='c1')
        self.assertEqual([event['cursor'] for event in events if event['event']=='message'], ['c2','c3'])
        self.assertTrue(process.terminated)

    async def test_vacuumed_cursor_reports_gap_before_new_records(self):
        events = await self.consume(FakeProcess([record('c3')]), cursor='c1')
        self.assertEqual([event['event'] for event in events], ['gap','message'])
        self.assertEqual(events[1]['cursor'], 'c3')

    async def test_deleted_service_closes_silent_stream(self):
        process = FakeProcess(eof=False)
        async def remove():
            await asyncio.sleep(.03)
            self.services.clear()
        task = asyncio.create_task(remove())
        events = await asyncio.wait_for(self.consume(process, cursor='c1'), 1)
        await task
        self.assertEqual(events[-1]['event'], 'identity_changed')
        self.assertTrue(process.terminated)

    async def test_obsolete_identity_never_spawns_old_or_new_unit(self):
        with patch.object(systemd.asyncio, 'create_subprocess_exec') as spawn:
            events = [event async for event in systemd.stream_logs('demo', 0, structured=True, identity='obsolete')]
        self.assertEqual(events[0]['event'], 'identity_changed')
        spawn.assert_not_called()

class JournalAdditionalSnapshot(JournalSnapshot):
    def test_status_rejects_unit_changed_during_command(self):
        def execute(*args, **kwargs):
            self.services['demo']['unit'] = 'new.service'
            return subprocess.CompletedProcess([], 0, 'old unit status', '')
        with patch.object(systemd, '_execute', side_effect=execute), self.assertRaisesRegex(ValueError, 'changed'):
            systemd.get_status('demo')

    def test_snapshot_does_not_hold_storage_lock_while_waiting(self):
        import concurrent.futures
        def run(*args, **kwargs):
            def read():
                return storage.read('unrelated.json', {})
            with concurrent.futures.ThreadPoolExecutor() as pool:
                self.assertEqual(pool.submit(read).result(timeout=.5), {})
            return subprocess.CompletedProcess([], 0, record('c1'), '')
        with patch.object(systemd, '_run', side_effect=run):
            self.assertEqual(systemd.get_recent_log_snapshot('demo')['cursor'], 'c1')

    def test_permissions_diagnostics_visible_as_gap(self):
        with patch.object(systemd, '_run', return_value=subprocess.CompletedProcess([], 1, '', 'Permission denied')):
            snapshot = systemd.get_recent_log_snapshot('demo')
        self.assertEqual(snapshot['lines'], [])
        self.assertIsNone(snapshot['cursor'])
        self.assertIn('Permission denied', snapshot['gap'])

    def test_sse_framing_keeps_multiline_log_in_one_json_event(self):
        output = systemd.encode_log_event({'event':'message','cursor':'c2','line':'first\nsecond'})
        self.assertEqual(output, 'id: c2\ndata: {"line": "first\\nsecond"}\n\n')


class JournalAdditionalStream(JournalStream):
    async def test_remote_host_address_user_port_and_trust_changes_stop_stream(self):
        self.services['demo'].update(service_type='remote', host_id='remote')
        for field, new in [('address','192.0.2.2'), ('username','other'), ('port',2222), ('trusted',False), ('fingerprint','changed')]:
            with self.subTest(field=field):
                host = {'address':'192.0.2.1','username':'example','port':22,'trusted':True,'fingerprint':'old'}
                process = FakeProcess(eof=False)
                async def modify():
                    await asyncio.sleep(.03)
                    host[field] = new
                with patch.object(systemd.registry, 'host', side_effect=lambda _: dict(host)), patch.object(systemd.ssh_hosts, 'ssh_command', side_effect=lambda h,args:args):
                    task = asyncio.create_task(modify())
                    events = await asyncio.wait_for(self.consume(process,cursor='c1'),1)
                    await task
                self.assertEqual(events[-1]['event'], 'identity_changed')
                self.assertTrue(process.terminated)

    async def test_scope_unit_and_unmanaged_changes_discard_buffered_log(self):
        for field,new in [('scope','user'),('unit','new.service'),('unit','')]:
            with self.subTest(field=field):
                self.services['demo'].update(scope='system',unit='demo.service')
                process = FakeProcess(eof=False)
                async def modify():
                    await asyncio.sleep(.015)
                    self.services['demo'][field] = new
                    process.stdout.feed_data(record('c2','old buffered log').encode())
                task = asyncio.create_task(modify())
                events = await asyncio.wait_for(self.consume(process,cursor='c1'),1)
                await task
                self.assertEqual(events, [{'event':'identity_changed','message':'Service or SSH host changed. Reload its details.'}])
                self.assertTrue(process.terminated)

    async def test_silent_structured_stream_session_revocation_cleans_process(self):
        valid = True
        process = FakeProcess(eof=False)
        async def revoke():
            nonlocal valid
            await asyncio.sleep(.03)
            valid = False
        task=asyncio.create_task(revoke())
        events=await asyncio.wait_for(self.consume(process,cursor='c1',session_valid=lambda:valid),1)
        await task
        self.assertEqual(events, [])
        self.assertTrue(process.terminated)

    async def test_invalid_session_never_spawns(self):
        with patch.object(systemd.asyncio,'create_subprocess_exec') as spawn:
            events=[e async for e in systemd.stream_logs('demo',structured=True,session_valid=lambda:False)]
        self.assertEqual(events,[])
        spawn.assert_not_called()

    async def test_no_cursor_reports_gap_and_requests_no_historical_replay(self):
        process=FakeProcess([record('c1')])
        command=[]
        async def spawn(*args,**kwargs):
            command.extend(args)
            return process
        with patch.object(systemd.asyncio,'create_subprocess_exec',side_effect=spawn):
            events=[e async for e in systemd.stream_logs('demo',0,structured=True)]
        self.assertEqual(events[0]['event'],'gap')
        self.assertEqual(command[command.index('-n')+1],'0')
        self.assertEqual(events[1]['cursor'],'c1')
