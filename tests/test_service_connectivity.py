"""Systemd and website checks remain independent; all storage is temporary."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import registry, storage, website_checks, config_transfer, manual_ports


class ServiceConnectivity(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.enterContext(patch.object(storage, 'DATA_DIR', Path(temp.name)))

    def body(self, **changes):
        return dict(service_type='local',host_id='local',unit='example.service',scope='user',
                    display_name='Example',category='Websites',description='',port=3000,
                    open_url='https://example.invalid',website_check={'method':'http'},**changes)

    def test_managed_check_settings_are_preserved(self):
        self.assertEqual(website_checks.normalize({'method':'http'},managed=True,url='https://example.invalid'),{'method':'http'})
        entry=registry.add_service(self.body())
        self.assertEqual(entry['website_check'],{'method':'http'})
        exported=config_transfer.export_config('service',entry['id'])
        self.assertEqual(exported['services'][0]['website_check'],{'method':'http'})
        storage.write('registered-services.json',[])
        config_transfer.import_config(exported)
        self.assertEqual(registry.registered_services()[0]['website_check'],{'method':'http'})

    def test_builtin_check_settings_survive_edit_and_import(self):
        from app.catalog import SERVICE_BY_ID
        builtin=SERVICE_BY_ID['host-service-dashboard.service']
        body=self.body();body.update(unit=builtin['id'],scope=builtin['scope'])
        registry.update_service(builtin['id'],body)
        self.assertEqual(SERVICE_BY_ID[builtin['id']]['website_check'],{'method':'http'})
        from app import service_urls
        service_urls.set_url(builtin['id'],body['open_url'])
        document=config_transfer.export_config('service',builtin['id'])
        document['services'][0]['website_check']={'method':'tcp','address':'localhost','port':443}
        preview=config_transfer.import_config(document,dry_run=True)
        config_transfer.import_config(document,overwrite=True,preview_token=preview['preview_token'])
        self.assertEqual(SERVICE_BY_ID[builtin['id']]['website_check']['port'], document['services'][0]['port'])

    def test_probe_never_overwrites_systemd_state_time_or_error(self):
        from app import main
        result={'method':'http','status':'Stopped','http_status':503,'checked_at':'2026-10-17T01:00:00Z','error':'HTTP 503'}
        for status in ('Running','Failed','Stopped','Unavailable'):
            with self.subTest(status=status), patch.object(website_checks,'check',return_value=result):
                row={**self.body(),'id':'svc-test','name':'Example','managed':True,'status':status,
                     'checked_at':'2026-10-17T00:00:00Z','error':'original systemd diagnostic'}
                decorated=main._decorate_services([row])[0]
                self.assertEqual(decorated['status'],status)
                self.assertEqual(decorated['checked_at'],'2026-10-17T00:00:00Z')
                self.assertEqual(decorated['error'],'original systemd diagnostic')
                self.assertEqual(decorated['website_result'],result)

    def test_service_live_never_probes_recorded_port_implicitly(self):
        from app import main
        entry=registry.add_service(self.body())
        row={**entry,'managed':True,'status':'Running','configured_port':3000,'checked_at':None,'error':''}
        with patch.object(main.systemd,'get_service',return_value=row), patch.object(website_checks,'check',return_value={'method':'http','status':'Running','http_status':200,'checked_at':'now','error':''}), patch.object(manual_ports,'check_configured',side_effect=AssertionError('Recorded port must not be probed')):
            self.assertIsNone(main.service_live(entry['id'],'fixture')['port'])

    def test_metadata_only_port_inventory_does_not_connect(self):
        registry.add_service(self.body())
        storage.write('manual-ports.json',[{'id':'port-test','name':'Only port','source':'fixture','host_id':'local','host_name':'This host','address':'127.0.0.1','port':5555}])
        with patch.object(manual_ports,'_probe',side_effect=AssertionError('Unexpected TCP probe')):
            self.assertEqual(manual_ports.list_configured_checked(probe=False)['ports'][0]['status'],'Not checked')
            self.assertEqual(manual_ports.list_checked(probe=False)['ports'][0]['status'],'Not checked')

    def test_legacy_url_update_cannot_invalidate_http_check(self):
        from app import service_urls
        entry=registry.add_service(self.body())
        with self.assertRaises(ValueError): service_urls.set_url(entry['id'],'')
        self.assertEqual(website_checks.check({'method':'http'},'')['status'],'Stopped')
