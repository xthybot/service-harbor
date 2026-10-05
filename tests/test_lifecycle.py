"""Isolated lifecycle regression; never executes real system operations."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('lifecycle_under_test', Path(__file__).parents[1] / 'scripts/lifecycle.py')
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)


class LifecycleSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.app = self.home / 'project'
        self.app.mkdir(parents=True)
        self.config = self.home / '.config/dashboard'
        self.config.mkdir(parents=True)
        self.data = self.app / 'data'
        self.data.mkdir()
        self.patches = [patch.object(lc, name, value) for name, value in {
            'HOME': self.home, 'APP': self.app, 'CONFIG_BASE': self.home / '.config',
            'CONFIG': self.config, 'ENV': self.config / 'dashboard.env',
            'RECEIPT': self.config / 'install.json',
            'UNITS': {'user': self.home / '.config/systemd/user' / lc.UNIT,
                      'system': self.root / 'system' / lc.UNIT},
        }.items()]
        self.patches += [patch.object(lc.storage, 'DATA_DIR', self.data),
                         patch.object(lc, 'run', side_effect=AssertionError('Unmocked subprocess prohibited')),
                         patch.object(lc, 'sudo', side_effect=AssertionError('Unmocked sudo prohibited'))]
        for item in self.patches: item.start()
        self.addCleanup(self.tmp.cleanup)
        for item in self.patches: self.addCleanup(item.stop)

    def receipt(self, data=None):
        lc.RECEIPT.write_text(json.dumps({'version': 1, 'project': str(self.app), 'user': lc.ACCOUNT,
                                        'data': str(data or self.data), 'mode': 'user', 'backend': 'venv'}))
        lc.ENV.write_text('DASHBOARD_DATA_DIR="' + str(data or self.data) + '"\n')

    def test_dotdot_rejected(self):
        with self.assertRaises(RuntimeError): lc.data_path({'DASHBOARD_DATA_DIR': str(self.data / '..')})

    def test_source_subdirectory_rejected(self):
        with self.assertRaises(RuntimeError): lc.data_path({'DASHBOARD_DATA_DIR': str(self.app / 'app')})

    def test_env_receipt_mismatch_rejected(self):
        self.receipt()
        with self.assertRaises(RuntimeError): lc.data_path({'DASHBOARD_DATA_DIR': str(self.home / 'other')})

    def test_missing_env_data_does_not_fallback(self):
        self.receipt()
        with self.assertRaises(RuntimeError): lc.data_path({})

    def test_offline_revocation_recovers_first(self):
        token = {'fake-test-token': 123}
        (self.data / 'sessions.json').write_text('{}')
        (self.data / lc.storage.JOURNAL).write_text(json.dumps({'sessions.json': base64.b64encode(json.dumps(token).encode()).decode()}))
        lc.revoke_sessions(self.data)
        self.assertEqual(lc.storage.read('sessions.json', None), {})
        self.assertFalse((self.data / lc.storage.JOURNAL).exists())

    def owned(self):
        lc.require_owner(self.data, create=True)
        self.receipt()

    def fake_ctl(self, *args, **kwargs):
        from subprocess import CompletedProcess
        return CompletedProcess(args, 0, 'inactive' if 'ActiveState' in args else '', '')

    def test_unknown_ssh_files_are_retained(self):
        self.owned()
        ssh = self.data / 'ssh'; ssh.mkdir()
        (ssh / 'personal_key').write_text('fake unrelated')
        (ssh / 'dashboard_ed25519').write_text('fake dashboard')
        (ssh / ('a' * 32 + '.known_hosts')).write_text('fake pin')
        (ssh / ('b' * 32 + '.known_hosts')).write_text('unrelated pin')
        lc.storage.write('hosts.json', [{'id': 'a' * 32}])
        lc.cleanup_data(self.data)
        self.assertEqual(sorted(p.name for p in ssh.iterdir()), sorted(['personal_key', 'b' * 32 + '.known_hosts']))

    def test_uninstall_includes_host_with_pending_pin_deletion(self):
        self.owned()
        ssh = self.data / 'ssh'; ssh.mkdir()
        pin = ssh / ('a' * 32 + '.known_hosts')
        unrelated = ssh / ('b' * 32 + '.known_hosts')
        pin.write_text('fictional pending pin')
        unrelated.write_text('fictional unrelated pin')
        lc.storage.write('hosts.json', [{'id': 'a' * 32, 'trusted': False,
                                         'pin_cleanup_pending': 'delete'}])
        lc.cleanup_data(self.data)
        self.assertFalse(pin.exists())
        self.assertEqual(unrelated.read_text(), 'fictional unrelated pin')

    def test_directory_impersonating_json_is_never_deleted(self):
        self.owned()
        item = self.data / 'sessions.json'; item.mkdir()
        (item / 'important').write_text('keep')
        with self.assertRaises(RuntimeError): lc.cleanup_data(self.data)
        self.assertTrue((item / 'important').exists())

    def test_symlink_data_and_json_are_rejected(self):
        self.owned()
        external = self.root / 'external'; external.write_text('keep')
        (self.data / 'sessions.json').symlink_to(external)
        with self.assertRaises(RuntimeError): lc.cleanup_data(self.data)
        self.assertEqual(external.read_text(), 'keep')
        (self.data / 'sessions.json').unlink()
        alias = self.home / 'alias'; alias.symlink_to(self.data)
        with self.assertRaises(RuntimeError): lc.data_path({'DASHBOARD_DATA_DIR': str(alias)})

    def test_known_temporaries_only(self):
        self.owned()
        (self.data / '.json-write-abcd1234').write_text('incomplete')
        (self.data / '.json-write-unrecognized').write_text('keep')
        lc.cleanup_data(self.data)
        self.assertFalse((self.data / '.json-write-abcd1234').exists())
        self.assertTrue((self.data / '.json-write-unrecognized').exists())

    def test_corrupt_recovery_is_preserved_and_stops_cleanup(self):
        self.owned()
        (self.data / lc.storage.JOURNAL).write_text('bad json')
        (self.data / 'sessions.json').write_text('{}')
        with self.assertRaises(ValueError): lc.cleanup_data(self.data)
        self.assertTrue((self.data / 'sessions.json').exists())
        self.assertEqual((self.data / lc.storage.JOURNAL).read_text(), 'bad json')

    def test_unowned_nonempty_directory_requires_explicit_adoption(self):
        (self.data / 'sessions.json').write_text('{}')
        with self.assertRaises(RuntimeError): lc.require_owner(self.data, create=True)
        self.assertFalse((self.data / lc.OWNER_FILE).exists())

    def test_uninstall_failure_keeps_records_and_retry_clears_original_target(self):
        self.owned(); self.receipt()
        (self.data / 'sessions.json').write_text('{}')
        original_unlink = Path.unlink
        def fail_sessions(path, *args, **kwargs):
            if path == self.data / 'sessions.json': raise PermissionError('injected')
            return original_unlink(path, *args, **kwargs)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(Path, 'unlink', fail_sessions):
                with self.assertRaises(PermissionError): lc.uninstall()
            self.assertTrue(lc.ENV.exists()); self.assertTrue(lc.RECEIPT.exists())
            self.assertEqual(json.loads(lc.RECEIPT.read_text())['data'], str(self.data))
            lc.uninstall()
        self.assertFalse(lc.RECEIPT.exists()); self.assertFalse(self.data.exists())

    def test_uninstall_retry_removes_registered_pin_after_hosts_file_was_deleted(self):
        self.owned(); self.receipt()
        ssh = self.data / 'ssh'; ssh.mkdir()
        known = ssh / ('a' * 32 + '.known_hosts')
        unknown = ssh / ('b' * 32 + '.known_hosts')
        personal = ssh / 'personal_key'
        known.write_text('fictional dashboard pin')
        unknown.write_text('fictional unrelated pin')
        personal.write_text('fictional personal file')
        lc.storage.write('hosts.json', [{'id': 'a' * 32}])
        original_unlink = Path.unlink
        def fail_pin(path, *args, **kwargs):
            if path == known: raise PermissionError('injected registered pin deletion failure')
            return original_unlink(path, *args, **kwargs)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(Path, 'unlink', fail_pin):
                with self.assertRaises(PermissionError): lc.uninstall()
            self.assertFalse((self.data / 'hosts.json').exists())
            self.assertTrue(known.exists())
            self.assertTrue(lc.RECEIPT.exists())
            self.assertTrue((self.data / '.dashboard-uninstall-pins.json').exists())
            lc.uninstall()
        self.assertFalse(known.exists())
        self.assertFalse((self.data / '.dashboard-uninstall-pins.json').exists())
        self.assertFalse(lc.RECEIPT.exists())
        self.assertEqual(unknown.read_text(), 'fictional unrelated pin')
        self.assertEqual(personal.read_text(), 'fictional personal file')

    def test_corrupt_pin_cleanup_record_stops_retry_before_unknown_deletion(self):
        self.owned(); self.receipt()
        ssh = self.data / 'ssh'; ssh.mkdir()
        known = ssh / ('a' * 32 + '.known_hosts')
        unknown = ssh / ('b' * 32 + '.known_hosts')
        known.write_text('fictional dashboard pin')
        unknown.write_text('fictional unrelated pin')
        lc.storage.write('hosts.json', [{'id': 'a' * 32}])
        original_unlink = Path.unlink
        def fail_pin(path, *args, **kwargs):
            if path == known: raise PermissionError('injected')
            return original_unlink(path, *args, **kwargs)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(Path, 'unlink', fail_pin):
                with self.assertRaises(PermissionError): lc.uninstall()
            record = self.data / '.dashboard-uninstall-pins.json'
            pristine = record.read_text()
            record.write_text(pristine.replace('a' * 32, 'b' * 32))
            with self.assertRaises(RuntimeError): lc.uninstall()
            self.assertTrue(known.exists())
            self.assertEqual(unknown.read_text(), 'fictional unrelated pin')
            record.write_text('{broken json')
            with self.assertRaises((RuntimeError, ValueError)):
                lc.uninstall()
            self.assertTrue(known.exists())
            self.assertTrue(unknown.exists())
            crafted = json.loads(pristine)
            crafted['pins'] = ['../personal.known_hosts']
            content = json.dumps(crafted, sort_keys=True, separators=(',', ':')) + '\n'
            record.write_text(content)
            receipt = json.loads(lc.RECEIPT.read_text())
            receipt['pin_cleanup_sha256'] = hashlib.sha256(content.encode()).hexdigest()
            lc.RECEIPT.write_text(json.dumps(receipt))
            with self.assertRaises(RuntimeError): lc.uninstall()
            self.assertTrue(known.exists())
            self.assertTrue(unknown.exists())
            wrong_owner = json.loads(pristine)
            wrong_owner['owner']['uid'] = lc.UID + 1
            content = json.dumps(wrong_owner, sort_keys=True, separators=(',', ':')) + '\n'
            record.write_text(content)
            receipt['pin_cleanup_sha256'] = hashlib.sha256(content.encode()).hexdigest()
            lc.RECEIPT.write_text(json.dumps(receipt))
            with self.assertRaises(RuntimeError): lc.uninstall()
            self.assertTrue(known.exists())
            self.assertTrue(unknown.exists())

    def test_pin_cleanup_record_symlink_stops_retry(self):
        self.owned(); self.receipt()
        ssh = self.data / 'ssh'; ssh.mkdir()
        known = ssh / ('a' * 32 + '.known_hosts')
        known.write_text('fictional dashboard pin')
        lc.storage.write('hosts.json', [{'id': 'a' * 32}])
        original_unlink = Path.unlink
        def fail_pin(path, *args, **kwargs):
            if path == known: raise PermissionError('injected')
            return original_unlink(path, *args, **kwargs)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(Path, 'unlink', fail_pin):
                with self.assertRaises(PermissionError): lc.uninstall()
            record = self.data / '.dashboard-uninstall-pins.json'
            outside = self.root / 'personal'; outside.write_text('untouched')
            record.unlink(); record.symlink_to(outside)
            with self.assertRaises(RuntimeError): lc.uninstall()
        self.assertTrue(known.exists())
        self.assertEqual(outside.read_text(), 'untouched')

    def test_retry_finishes_record_deletion_after_data_cleanup_completed(self):
        self.owned(); self.receipt()
        ssh = self.data / 'ssh'; ssh.mkdir()
        known = ssh / ('a' * 32 + '.known_hosts')
        known.write_text('fictional dashboard pin')
        lc.storage.write('hosts.json', [{'id': 'a' * 32}])
        record = self.data / '.dashboard-uninstall-pins.json'
        original_unlink = Path.unlink
        def fail_record(path, *args, **kwargs):
            if path == record: raise PermissionError('injected record removal failure')
            return original_unlink(path, *args, **kwargs)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(Path, 'unlink', fail_record):
                with self.assertRaises(PermissionError): lc.uninstall()
            self.assertFalse(known.exists())
            self.assertEqual(json.loads(lc.RECEIPT.read_text())['uninstall_stage'], 'data-cleared')
            self.assertTrue(record.exists())
            lc.uninstall()
        self.assertFalse(record.exists())
        self.assertFalse(lc.RECEIPT.exists())

    def test_retry_reconstructs_record_if_creation_failed_before_any_data_deletion(self):
        self.owned(); self.receipt()
        ssh = self.data / 'ssh'; ssh.mkdir()
        known = ssh / ('a' * 32 + '.known_hosts')
        known.write_text('fictional dashboard pin')
        lc.storage.write('hosts.json', [{'id': 'a' * 32}])
        record = self.data / '.dashboard-uninstall-pins.json'
        original_atomic = lc.atomic
        failed = False
        def fail_record_creation(path, content):
            nonlocal failed
            if path == record and not failed:
                failed = True; raise PermissionError('injected record creation failure')
            return original_atomic(path, content)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(lc, 'atomic', side_effect=fail_record_creation):
                with self.assertRaises(PermissionError): lc.uninstall()
            self.assertTrue((self.data / 'hosts.json').exists())
            self.assertFalse(record.exists())
            self.assertIn('pin_cleanup_sha256', json.loads(lc.RECEIPT.read_text()))
            lc.uninstall()
        self.assertFalse(known.exists())
        self.assertFalse(lc.RECEIPT.exists())

    def test_final_stage_failure_can_retry_after_env_and_marker_are_gone(self):
        self.owned(); self.receipt()
        original_unlink = Path.unlink
        failed = False
        def fail_receipt(path, *args, **kwargs):
            nonlocal failed
            if path == lc.RECEIPT and not failed:
                failed = True; raise PermissionError('injected')
            return original_unlink(path, *args, **kwargs)
        with patch.object(lc, 'ctl', side_effect=self.fake_ctl), patch('builtins.input', return_value='REMOVE'):
            with patch.object(Path, 'unlink', fail_receipt):
                with self.assertRaises(PermissionError): lc.uninstall()
            self.assertFalse(lc.ENV.exists()); self.assertTrue(lc.RECEIPT.exists())
            lc.uninstall()
        self.assertFalse(lc.RECEIPT.exists())

    def test_wrong_owner_marker_does_not_authorize_deletion(self):
        self.owned()
        marker = self.data / lc.OWNER_FILE
        value = json.loads(marker.read_text()); value['project'] = '/different/project'
        marker.write_text(json.dumps(value))
        with self.assertRaises(RuntimeError): lc.cleanup_data(self.data)

    def test_revoke_corrupt_recovery_never_deletes_journal(self):
        (self.data / lc.storage.JOURNAL).write_text('broken')
        with self.assertRaises(ValueError): lc.revoke_sessions(self.data)
        self.assertTrue((self.data / lc.storage.JOURNAL).exists())

    def test_rollback_recovery_failure_still_restores_settings_and_unit_but_never_starts(self):
        self.receipt()
        (self.data / lc.storage.JOURNAL).write_text('broken')
        calls = []
        def ctl(*args, **kwargs): calls.append(args)
        installed = {'user': 'original unit'}
        previous = {'user': {'active': True, 'enabled': True}}
        with patch.object(lc, 'ctl', side_effect=ctl), patch.object(lc, 'remove_unit'), patch.object(lc, 'put_unit') as put:
            results = lc.rollback_install(installed, previous, {'system'}, {lc.ENV: b'old settings'}, self.data)
        self.assertEqual(lc.ENV.read_text(), 'old settings')
        put.assert_called_once_with('user', 'original unit')
        self.assertIn(('recover data and revoke sessions', False), results)
        self.assertFalse(any('start' in call for call in calls))
        self.assertTrue(any('daemon-reload' in call for call in calls))

    def test_rollback_failed_stop_does_not_prevent_other_restorations(self):
        calls = []
        def ctl(*args, **kwargs):
            calls.append(args)
            if '--now' in args: raise OSError('injected')
        with patch.object(lc, 'ctl', side_effect=ctl), patch.object(lc, 'put_unit') as put:
            result = lc.rollback_install({'user': 'old'}, {'user': {'active': True, 'enabled': True}}, {'user'}, {lc.ENV: b'old'}, self.data)
        put.assert_called_once_with('user', 'old')
        self.assertEqual(lc.ENV.read_text(), 'old')
        self.assertIn(('stop new user unit', False), result)
        self.assertFalse(any('start' in call for call in calls))

    def test_rollback_never_revalidates_old_sessions(self):
        (self.data / 'sessions.json').write_text('{"fake-old-token":123}')
        with patch.object(lc, 'ctl'), patch.object(lc, 'put_unit'):
            lc.rollback_install({}, {}, set(), {self.data / 'sessions.json': b'{"fake-old-token":123}'}, self.data)
        self.assertEqual(lc.storage.read('sessions.json', None), {})

    def test_unit_directive_encoding(self):
        source = Path(__file__).parents[1] / 'systemd' / lc.UNIT
        (self.app / 'systemd').mkdir()
        (self.app / 'systemd' / lc.UNIT).write_text(source.read_text())
        weird = self.home / 'space % dollar$ quote" slash\\'
        with patch.object(lc, 'ENV', weird / 'dashboard.env'):
            text = lc.make_unit('user', weird / 'data')
        self.assertIn('WorkingDirectory="' + str(self.app) + '"', text)
        self.assertIn('space %% dollar$ quote\\" slash\\\\', text)
        self.assertNotIn('@ENV@', text)

    def test_unit_search_path_must_match_real_manager(self):
        from subprocess import CompletedProcess
        with patch.object(lc, 'ctl', return_value=CompletedProcess([], 0, '/other/xdg/systemd/user', '')):
            with self.assertRaises(RuntimeError): lc.check_unit_paths('user')
        with patch.object(lc, 'ctl', return_value=CompletedProcess([], 0, str(lc.UNITS['user'].parent), '')):
            lc.check_unit_paths('user')

    def test_system_roots_and_control_paths_rejected(self):
        for value in ('/var', '/tmp', '/etc/custom', '/usr/share/custom', str(self.app / '.git'), str(self.home), str(self.data) + '\n'):
            with self.subTest(value=value), self.assertRaises(RuntimeError): lc.data_path({'DASHBOARD_DATA_DIR': value})

    def prepare_install(self):
        from contextlib import ExitStack
        from subprocess import CompletedProcess
        source = Path(__file__).parents[1] / 'systemd' / lc.UNIT
        (self.app / 'systemd').mkdir(exist_ok=True)
        (self.app / 'systemd' / lc.UNIT).write_text(source.read_text())
        (self.app / '.venv/bin').mkdir(parents=True)
        (self.app / '.venv/bin/python').write_text('fake-not-executable')
        values = {'DASHBOARD_PASSWORD': 'fake-test-password', 'DASHBOARD_BIND': '127.0.0.1',
                  'DASHBOARD_PORT': '18765', 'DASHBOARD_DATA_DIR': str(self.data)}
        stack = ExitStack(); self.addCleanup(stack.close)
        stack.enter_context(patch.object(lc, 'get_settings', return_value=(values, 'user')))
        stack.enter_context(patch.object(lc.shutil, 'which', side_effect=lambda name: '/fake/' + name))
        stack.enter_context(patch.object(lc, 'ensure_user_manager'))
        stack.enter_context(patch.object(lc, 'check_unit_paths'))
        stack.enter_context(patch.object(lc, 'port_available'))
        stack.enter_context(patch.object(lc, 'verify'))
        stack.enter_context(patch.object(lc, 'ctl', side_effect=self.fake_ctl))
        calls = []
        def run(args, **kwargs):
            calls.append([str(x) for x in args]); return CompletedProcess(args, 0, '', '')
        stack.enter_context(patch.object(lc, 'run', side_effect=run))
        return calls

    def test_uv_install_never_requires_pip_or_ensurepip(self):
        calls = self.prepare_install()
        with patch('importlib.util.find_spec', side_effect=AssertionError('uv must not inspect ensurepip/venv')):
            lc.install(backend='uv')
        self.assertTrue(any(call[:3] == ['/fake/uv', 'pip', 'install'] for call in calls))
        self.assertFalse(any('-m' in call and 'pip' in call for call in calls))
        self.assertEqual(json.loads(lc.RECEIPT.read_text())['backend'], 'uv')

    def test_venv_install_keeps_standard_pip_backend(self):
        calls = self.prepare_install()
        lc.install(backend='venv')
        self.assertTrue(any(call[1:4] == ['-m', 'pip', 'install'] for call in calls))
        self.assertEqual(json.loads(lc.RECEIPT.read_text())['backend'], 'venv')

    def test_corrupt_recovery_prevents_install_stop_or_manager_side_effects(self):
        self.prepare_install()
        self.owned()
        (self.data / lc.storage.JOURNAL).write_text('broken')
        with patch.object(lc, 'ctl') as ctl, patch.object(lc, 'ensure_user_manager') as manager:
            with self.assertRaises(ValueError): lc.install(backend='uv')
        ctl.assert_not_called(); manager.assert_not_called()

    def test_legacy_adoption_requires_offline_and_explicit_confirmation(self):
        self.receipt()
        (self.data / 'hosts.json').write_text('[]')
        with patch.object(lc, 'require_offline') as offline, patch('builtins.input', return_value='ADOPT'):
            lc.adopt_data()
        offline.assert_called_once()
        lc.require_owner(self.data)

    def test_offline_check_rejects_active_or_unreachable_manager(self):
        from subprocess import CompletedProcess
        for code, state in ((0, 'active'), (0, 'activating'), (1, '')):
            with self.subTest(state=state), patch.object(lc, 'ctl', return_value=CompletedProcess([], code, state, '')):
                with self.assertRaises(RuntimeError): lc.require_offline()
