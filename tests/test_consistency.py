"""Concurrency and round-trip regressions; all records are disposable."""
import os
import tempfile
_BOOT = tempfile.TemporaryDirectory(prefix='consistency-import-')
os.environ['DASHBOARD_DATA_DIR'] = _BOOT.name
os.environ['DASHBOARD_PASSWORD'] = 'isolated-test-password'
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException, Response
from app import storage, registry, config_transfer, main, security, service_urls, service_names
from app.service_url_validation import validate_url


def body(**changes):
    return dict(service_type='external', display_name='Example', scope='external', unit='', category='Websites', open_url='https://example.com', **changes)


def request():
    return Request({'type':'http', 'method':'PUT', 'path':'/', 'scheme':'http', 'headers':[(b'host',b'localhost'),(b'origin',b'http://localhost')]})


class Consistency(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(storage, 'DATA_DIR', Path(self.temp.name)); self.patch.start()
    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()
    def doc(self):
        return {'format':config_transfer.FORMAT, 'version':1, 'services':[body()]}

    def test_logout_reply_never_clears_a_later_login_cookie(self):
        token=security.login('isolated-test-password','isolated')
        scope={'type':'http','method':'POST','path':'/api/logout','scheme':'http',
               'headers':[(b'host',b'localhost'),(b'origin',b'http://localhost'),
                          (b'cookie',(security.SESSION_COOKIE+'='+token).encode())]}
        response=Response()
        main.logout(Request(scope),response,token)
        self.assertFalse(security.token_is_valid(token))
        self.assertNotIn('set-cookie',response.headers,
                         'A late logout response could delete a newer login cookie')

    def test_external_settings_cannot_erase_url(self):
        entry=registry.add_service(body())
        with self.assertRaises(HTTPException) as caught:
            main.set_service_settings(entry['id'], main.ServiceSettingsBody(display_name='Changed',open_url=''), request(), 'dummy')
        self.assertEqual(caught.exception.status_code,400)
        exported=config_transfer.export_config('service',entry['id'])
        self.assertEqual(exported['services'][0]['display_name'],'Example')
        config_transfer.import_config(exported, dry_run=True)

    def test_export_rejects_legacy_invalid_external_record(self):
        entry=registry.add_service(body())
        storage.write('service-open-urls.json',{entry['id']:''})
        with self.assertRaisesRegex(ValueError,'Cannot export'):
            config_transfer.export_config('service',entry['id'])

    def test_edit_repairs_legacy_external_record_that_cannot_export(self):
        entry=registry.add_service(body())
        storage.write('service-open-urls.json',{entry['id']:''})
        payload=main.AddServiceBody(**body())
        self.assertEqual(main.edit_service(entry['id'],payload,request(),'dummy')['ok'],True)
        self.assertEqual(config_transfer.export_config('service',entry['id'])['services'][0]['open_url'],'https://example.com')

    def test_url_authority_validation(self):
        for value in ['https://exa mple.com/', 'https://example.com:/', 'https://example.com\\evil/', 'https://%65xample.com/', 'https://example..com/', 'https://-bad.com/', 'https://example.com\x7f/','https://@example.com/', 'https://example.com:0/']:
            with self.subTest(value=value), self.assertRaises(ValueError):validate_url(value)
        for value in ['http://localhost:8765/', 'http://127.0.0.1:80/', 'https://[::1]:8765/', 'https://例子.測試/path?q=hello%20world', 'https://example.com./', 'https://example.com/path?q=a b']:
            self.assertEqual(validate_url(value),value)

    def test_preview_conflict_added_later_is_rejected(self):
        document=self.doc(); preview=config_transfer.import_config(document,True,True)
        registry.add_service(body())
        with self.assertRaises(config_transfer.ImportConflict):
            config_transfer.import_config(document,False,False,preview['preview_token'])
        self.assertEqual(len(registry.registered_services()),1)

    def test_overwrite_requires_exact_preview_and_unchanged_data(self):
        entry=registry.add_service(body())
        document=self.doc(); preview=config_transfer.import_config(document,True,True)
        service_urls.set_url(entry['id'],'https://new.example.com')
        with self.assertRaises(config_transfer.ImportConflict):
            config_transfer.import_config(document,True,False,preview['preview_token'])
        with self.assertRaises(config_transfer.ImportConflict):config_transfer.import_config(document,True)
        fresh=config_transfer.import_config(document,True,True)
        altered=self.doc(); altered['services'][0]['display_name']='Surprise'
        with self.assertRaises(config_transfer.ImportConflict):
            config_transfer.import_config(altered,True,False,fresh['preview_token'])

    def test_confirmed_overwrite_and_skip(self):
        entry=registry.add_service(body()); document=self.doc()
        document['services'][0]['display_name']='Approved'
        preview=config_transfer.import_config(document,True,True)
        result=config_transfer.import_config(document,False,False,preview['preview_token'])
        self.assertEqual(result['skipped'],1)
        self.assertEqual(config_transfer.export_config('service',entry['id'])['services'][0]['display_name'],'Example')
        preview=config_transfer.import_config(document,True,True)
        self.assertEqual(config_transfer.import_config(document,True,False,preview['preview_token'])['updated'],1)
        self.assertEqual(config_transfer.export_config('service',entry['id'])['services'][0]['display_name'],'Approved')

    def test_probe_does_not_hold_storage_and_rechecks_host(self):
        host={'id':'a'*32, 'name':'Remote','address':'192.0.2.1','port':22,'username':'demo','trusted':True,'fingerprint':'test'}
        storage.write('hosts.json',[host])
        started=threading.Event();release=threading.Event();read_done=threading.Event();errors=[]
        def probe(entry):
            started.set();self.assertTrue(release.wait(3));return {}
        payload=main.AddServiceBody(service_type='remote',display_name='Remote service',host_id=host['id'],scope='system',unit='demo.service')
        def register():
            try:main.register_service(payload,request(),'dummy')
            except Exception as e:errors.append(e)
        def concurrent():
            token=security.login('isolated-test-password','isolated')
            security.logout(token)
            registry.update_host(host['id'],{'address':'192.0.2.2','trusted':False})
            registry.registered_services();read_done.set()
        with patch.object(main.systemd,'inspect_unit',side_effect=probe):
            writer=threading.Thread(target=register);writer.start()
            self.assertTrue(started.wait(2))
            reader=threading.Thread(target=concurrent);reader.start()
            unlocked=read_done.wait(.6)
            release.set();writer.join(4);reader.join(4)
        self.assertTrue(unlocked,'slow probe blocks login/logout/read under global lock')
        self.assertEqual(registry.registered_services(),[])
        self.assertEqual(len(errors),1)
        self.assertEqual(errors[0].status_code,409)

    def test_edit_probe_rejects_service_changed_while_command_runs(self):
        entry=registry.add_service(dict(service_type='local',display_name='Original',host_id='local',
                                        scope='user',unit='old.service',category='Tools',open_url=''))
        payload=main.AddServiceBody(service_type='local',display_name='New',host_id='local',
                                    scope='user',unit='new.service',category='Tools',open_url='')
        started=threading.Event();release=threading.Event();errors=[]
        def probe(_):
            started.set();self.assertTrue(release.wait(3));return {}
        def edit():
            try:main.edit_service(entry['id'],payload,request(),'dummy')
            except Exception as error:errors.append(error)
        with patch.object(main.systemd,'inspect_unit',side_effect=probe):
            writer=threading.Thread(target=edit);writer.start()
            self.assertTrue(started.wait(2))
            service_names.set_display_name(entry['id'],'Changed concurrently')
            release.set();writer.join(4)
        self.assertEqual(len(errors),1)
        self.assertEqual(errors[0].status_code,409)
        self.assertEqual(registry.registered_services()[0]['unit'],'old.service')
