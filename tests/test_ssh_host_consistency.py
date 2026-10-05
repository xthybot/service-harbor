"""Isolated host/pin failure windows; all host data and keys are fictional."""
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import registry, ssh_hosts, storage


HOST_ID = 'a' * 32
OTHER_ID = 'b' * 32


def interrupt_host_edit_before_pin_delete(directory):
    """A separate process exits after persisting the untrusted host phase."""
    root = Path(directory)
    storage.DATA_DIR = root
    ssh_hosts.SSH_DIR = root / 'ssh'
    pin = ssh_hosts.SSH_DIR / (HOST_ID + '.known_hosts')
    original = Path.unlink
    def crash(path, *args, **kwargs):
        if path == pin: os._exit(23)
        return original(path, *args, **kwargs)
    with patch.object(Path, 'unlink', crash):
        ssh_hosts.save_host({'name':'Example','address':'192.0.2.9','port':22,'username':'operator'}, HOST_ID)


class HostPinConsistency(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)
        self.ssh = self.data / 'ssh'
        self.ssh.mkdir()
        for target, value in ((storage, 'DATA_DIR'), (ssh_hosts, 'SSH_DIR')):
            self.enterContext(patch.object(target, value, self.data if target is storage else self.ssh))
        self.enterContext(patch.object(ssh_hosts, 'PRIVATE_KEY', self.ssh / 'dashboard_ed25519'))
        self.enterContext(patch.object(ssh_hosts, 'PUBLIC_KEY', self.ssh / 'dashboard_ed25519.pub'))
        self.pin = self.ssh / (HOST_ID + '.known_hosts')
        self.other_pin = self.ssh / (OTHER_ID + '.known_hosts')
        self.private_key = self.ssh / 'dashboard_ed25519'
        self.pin.write_text('fictional trusted key')
        self.other_pin.write_text('fictional unrelated key')
        self.private_key.write_text('fictional private key')
        self.host = {'id': HOST_ID, 'name': 'Example', 'address': '192.0.2.1', 'port': 22,
                     'username': 'operator', 'trusted': True, 'host_key': 'fictional',
                     'fingerprint': 'fictional fingerprint', 'connection': 'Connected'}
        storage.write('hosts.json', [self.host])

    def assert_unrelated_untouched(self):
        self.assertEqual(self.other_pin.read_text(), 'fictional unrelated key')
        self.assertEqual(self.private_key.read_text(), 'fictional private key')

    def test_delete_pin_failure_keeps_untrusted_host_for_retry_and_uninstall(self):
        original = Path.unlink
        def fail_pin(path, *args, **kwargs):
            if path == self.pin: raise PermissionError('injected pin deletion failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_pin), self.assertRaises(PermissionError):
            ssh_hosts.delete_host(HOST_ID)
        saved = registry.host(HOST_ID)
        self.assertFalse(saved['trusted'])
        self.assertEqual(saved['pin_cleanup_pending'], 'delete')
        self.assertTrue(self.pin.exists())
        from scripts import lifecycle
        self.assertIn(self.pin.name, lifecycle._pins_from_hosts(self.data))
        self.assert_unrelated_untouched()
        ssh_hosts.delete_host(HOST_ID)
        with self.assertRaises(ValueError): registry.host(HOST_ID)
        self.assertFalse(self.pin.exists())
        self.assert_unrelated_untouched()

    def test_address_or_port_write_failure_keeps_original_trust_and_pin(self):
        original = storage._replace_bytes
        def fail_host_write(path, content):
            if path.name == 'hosts.json': raise OSError('injected JSON write failure')
            return original(path, content)
        for changed in ({'address': '192.0.2.2'}, {'port': 2222}):
            with self.subTest(changed=changed):
                self.pin.write_text('fictional trusted key')
                storage.write('hosts.json', [self.host])
                with patch.object(storage, '_replace_bytes', side_effect=fail_host_write), self.assertRaises(OSError):
                    ssh_hosts.save_host({**self.host, **changed}, HOST_ID)
                saved = registry.host(HOST_ID)
                self.assertTrue(saved['trusted'])
                self.assertEqual(saved['address'], '192.0.2.1')
                self.assertEqual(saved['port'], 22)
                self.assertTrue(self.pin.exists())
                self.assert_unrelated_untouched()

    def test_reset_final_write_failure_and_process_interruption_are_retryable(self):
        original = storage._replace_bytes
        writes = 0
        def fail_second_write(path, content):
            nonlocal writes
            if path.name == 'hosts.json':
                writes += 1
                if writes == 2: raise OSError('injected final JSON write failure')
            return original(path, content)
        changed = {**self.host, 'address': '192.0.2.2'}
        with patch.object(storage, '_replace_bytes', side_effect=fail_second_write), self.assertRaises(OSError):
            ssh_hosts.save_host(changed, HOST_ID)
        saved = registry.host(HOST_ID)
        self.assertFalse(saved['trusted'])
        self.assertEqual(saved['pin_cleanup_pending'], 'reset')
        self.assertFalse(self.pin.exists())
        with self.assertRaises(ValueError): ssh_hosts.trust_host(HOST_ID, 'fictional fingerprint')
        ssh_hosts.save_host(changed, HOST_ID)
        saved = registry.host(HOST_ID)
        self.assertFalse(saved['trusted'])
        self.assertNotIn('pin_cleanup_pending', saved)
        self.assert_unrelated_untouched()

        self.pin.write_text('fictional stale key')
        changed_port = {**changed, 'port': 2222}
        original_unlink = Path.unlink
        def interrupt(path, *args, **kwargs):
            if path == self.pin: raise KeyboardInterrupt('simulated process interruption')
            return original_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', interrupt), self.assertRaises(KeyboardInterrupt):
            ssh_hosts.save_host(changed_port, HOST_ID)
        self.assertFalse(registry.host(HOST_ID)['trusted'])
        self.assertEqual(registry.host(HOST_ID)['pin_cleanup_pending'], 'reset')
        ssh_hosts.save_host(changed_port, HOST_ID)
        self.assertFalse(self.pin.exists())
        self.assertNotIn('pin_cleanup_pending', registry.host(HOST_ID))
        self.assert_unrelated_untouched()

    def test_delete_interrupted_after_pin_removal_keeps_retriable_host(self):
        original = storage._replace_bytes
        writes = 0
        def interrupt_second_write(path, content):
            nonlocal writes
            if path.name == 'hosts.json':
                writes += 1
                if writes == 2: raise KeyboardInterrupt('simulated process interruption')
            return original(path, content)
        with patch.object(storage, '_replace_bytes', side_effect=interrupt_second_write), self.assertRaises(KeyboardInterrupt):
            ssh_hosts.delete_host(HOST_ID)
        saved = registry.host(HOST_ID)
        self.assertFalse(saved['trusted'])
        self.assertEqual(saved['pin_cleanup_pending'], 'delete')
        self.assertFalse(self.pin.exists())
        ssh_hosts.delete_host(HOST_ID)
        with self.assertRaises(ValueError): registry.host(HOST_ID)
        self.assert_unrelated_untouched()

    def test_separate_process_crash_recovers_from_persisted_pending_reset(self):
        worker = multiprocessing.get_context('spawn').Process(
            target=interrupt_host_edit_before_pin_delete, args=(str(self.data),))
        worker.start(); worker.join(10)
        self.assertEqual(worker.exitcode, 23)
        saved = registry.host(HOST_ID)
        self.assertEqual(saved['address'], '192.0.2.9')
        self.assertFalse(saved['trusted'])
        self.assertEqual(saved['pin_cleanup_pending'], 'reset')
        self.assertTrue(self.pin.exists())
        ssh_hosts.save_host({'name':'Example','address':'192.0.2.9','port':22,'username':'operator'}, HOST_ID)
        self.assertFalse(self.pin.exists())
        self.assertNotIn('pin_cleanup_pending', registry.host(HOST_ID))
        self.assert_unrelated_untouched()

    def test_retrust_write_failure_never_leaves_old_trusted_record_with_new_pin(self):
        record = registry.host(HOST_ID)
        record.update({'pending_key': 'ssh-ed25519 fictional-new-key',
                       'pending_fingerprint': 'fictional new fingerprint'})
        storage.write('hosts.json', [record])
        original = storage._replace_bytes
        def fail_final_write(path, content):
            if path.name == 'hosts.json' and b'"trusted": true' in content:
                raise OSError('injected trust metadata write failure')
            return original(path, content)
        with patch.object(storage, '_replace_bytes', side_effect=fail_final_write), self.assertRaises(OSError):
            ssh_hosts.trust_host(HOST_ID, 'fictional new fingerprint')
        self.assertFalse(registry.host(HOST_ID)['trusted'])
        with self.assertRaises(ValueError): ssh_hosts.ssh_command(HOST_ID, ['/usr/bin/id'])
        self.assert_unrelated_untouched()
        ssh_hosts.trust_host(HOST_ID, 'fictional new fingerprint')
        self.assertTrue(registry.host(HOST_ID)['trusted'])
        self.assert_unrelated_untouched()
