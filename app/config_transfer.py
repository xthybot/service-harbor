"""Portable, secret-free service configuration export and import."""

from datetime import datetime, timezone
import uuid

from . import storage, registry, service_favorites, service_names, service_ports, service_urls, ssh_hosts
from .catalog import SERVICES, SERVICE_BY_ID
from .service_url_validation import validate_url

FORMAT = 'host-service-dashboard-services'
VERSION = 1
MAX_IMPORT_SERVICES = 250
CATEGORIES = {'Websites', 'Tools', 'Automation', 'Gateways', 'Monitoring', 'Network', 'Remote Access', 'Management', 'Other'}


@storage.locked
def export_config(selection: str = 'all', value: str = '') -> dict:
    if selection not in {'all', 'favorites', 'registered', 'category', 'service'}:
        raise ValueError('Unknown export selection.')
    if selection == 'category' and value not in CATEGORIES:
        raise ValueError('Choose a valid category.')
    if selection == 'service' and value not in SERVICE_BY_ID:
        raise ValueError('Choose a valid service.')
    hosts = {host['id']: host for host in registry.hosts()}
    names = service_names.get_names()
    urls = service_urls.get_urls()
    ports = service_ports.get_ports()
    favorites = service_favorites.get_favorites()
    services = []
    for entry in SERVICE_BY_ID.values():
        if selection == 'favorites' and entry['id'] not in favorites:
            continue
        if selection == 'registered' and not entry['id'].startswith('svc-'):
            continue
        if selection == 'category' and entry['category'] != value:
            continue
        if selection == 'service' and entry['id'] != value:
            continue
        kind = entry.get('service_type', 'local')
        host = None
        if kind == 'remote':
            item = hosts.get(entry.get('host_id'))
            if item is None:
                raise ValueError(f"Remote host is missing for {entry['id']}.")
            host = {'address': item['address'], 'username': item['username'], 'port': item['port']}
        services.append({
            'source_id': entry['id'], 'service_type': kind, 'host': host,
            'unit': entry.get('unit', entry['id']) if kind != 'external' else '',
            'scope': entry['scope'], 'display_name': names.get(entry['id'], entry['name']),
            'description': entry.get('description', ''), 'category': entry['category'],
            'port': ports.get(entry['id'], entry.get('port')),
            'open_url': urls.get(entry['id'], entry.get('open_url', '')),
            'favorite': entry['id'] in favorites,
        })
    return {'format': FORMAT, 'version': VERSION, 'exported_at': datetime.now(timezone.utc).isoformat(), 'services': services}


def _text(value, label: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'Invalid {label}.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{label} is required.')
    return value


def _normalized_service(raw: dict, index: int) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f'Service {index}: expected an object.')
    kind = raw.get('service_type')
    if not isinstance(kind, str) or kind not in {'local', 'remote', 'external'}:
        raise ValueError(f'Service {index}: invalid service type.')
    source_id = _text(raw.get('source_id', ''), 'source ID', 80)
    name = ' '.join(_text(raw.get('display_name'), 'display name', 80, required=True).split())
    description = _text(raw.get('description', ''), 'description', 240)
    category = raw.get('category')
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError(f'Service {index}: invalid category.')
    scope = raw.get('scope')
    unit = _text(raw.get('unit', ''), 'systemd unit', 200)
    if kind == 'external':
        if scope != 'external' or unit or raw.get('host') is not None:
            raise ValueError(f'Service {index}: invalid external website fields.')
    elif not isinstance(scope, str) or scope not in {'user', 'system'} or (unit and not registry.UNIT_PATTERN.fullmatch(unit)):
        raise ValueError(f'Service {index}: invalid unit or scope.')
    port = raw.get('port')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535 or not unit):
        raise ValueError(f'Service {index}: invalid service port.')
    url = validate_url(_text(raw.get('open_url', ''), 'Open URL', 2048))
    if kind == 'external' and not url:
        raise ValueError(f'Service {index}: external website requires an Open URL.')
    favorite = raw.get('favorite', False)
    if type(favorite) is not bool:
        raise ValueError(f'Service {index}: invalid favorite value.')
    host = None
    if kind == 'remote':
        raw_host = raw.get('host')
        if not isinstance(raw_host, dict):
            raise ValueError(f'Service {index}: remote host address and SSH username are required.')
        ssh_port = raw_host.get('port', 22)
        if type(ssh_port) is not int or not 1 <= ssh_port <= 65535:
            raise ValueError(f'Service {index}: invalid SSH port.')
        host = ssh_hosts._validate_host({
            'name': _text(raw_host.get('username'), 'SSH username', 33, required=True),
            'address': _text(raw_host.get('address'), 'host address', 253, required=True),
            'username': _text(raw_host.get('username'), 'SSH username', 33, required=True),
            'port': ssh_port,
        })
    elif raw.get('host') is not None:
        raise ValueError(f'Service {index}: only remote services may include a host.')
    return {'source_id': source_id, 'service_type': kind, 'host': host, 'unit': unit,
            'scope': scope, 'display_name': name, 'description': description,
            'category': category, 'port': port, 'open_url': url, 'favorite': favorite}


def _identity(entry: dict) -> tuple:
    kind = entry.get('service_type', 'local')
    return (kind, entry.get('host_id', 'local') if kind != 'external' else '',
            entry['scope'], entry.get('unit', entry['id']) if kind != 'external' else '')


def import_config(document: dict, overwrite: bool = False, dry_run: bool = False) -> dict:
    if not isinstance(document, dict) or document.get('format') != FORMAT or type(document.get('version')) is not int or document['version'] != VERSION:
        raise ValueError('Unsupported service configuration format or version.')
    raw_services = document.get('services')
    if not isinstance(raw_services, list) or len(raw_services) > MAX_IMPORT_SERVICES:
        raise ValueError('The service list is invalid or too large.')
    incoming = [_normalized_service(item, index + 1) for index, item in enumerate(raw_services)]

    with storage.transaction():
        hosts = registry.hosts()
        registered = registry.registered_services()
        metadata = registry.service_metadata()
        entries = {item['id']: item for item in SERVICE_BY_ID.values()}
        entries.update({item['id']: item for item in registered})
        names = service_names.get_names()
        urls = service_urls.get_urls()
        ports = service_ports.get_ports()
        favorites = service_favorites.get_favorites()
        host_lookup = {(item['address'], item['username'], item['port']): item for item in hosts}
        created_hosts = 0
        added = updated = skipped = 0
        conflicts = []
        for item in incoming:
            kind = item['service_type']
            host_id = 'local' if kind == 'local' else ''
            if kind == 'remote':
                requested = item['host']
                key = (requested['address'], requested['username'], requested['port'])
                target_host = host_lookup.get(key)
                if target_host is None:
                    if len(hosts) >= 50:
                        raise ValueError('Host limit reached (50). No changes were imported.')
                    same_account = any(host['address'] == requested['address'] and host['username'] == requested['username'] for host in hosts)
                    display_name = f"{requested['username']} ({requested['port']})" if same_account else requested['username']
                    target_host = {'id': uuid.uuid4().hex, 'name': display_name,
                                   'address': requested['address'], 'username': requested['username'],
                                   'port': requested['port'], 'trusted': False, 'connection': 'Unchecked',
                                   'checked_at': None, 'last_error': '', 'journal_access': None, 'fingerprint': ''}
                    hosts.append(target_host)
                    host_lookup[key] = target_host
                    created_hosts += 1
                host_id = target_host['id']
            identity = (kind, host_id, item['scope'], item['unit'])
            target = None
            source_id = item['source_id']
            if source_id in entries and _identity(entries[source_id]) == identity:
                target = entries[source_id]
            if target is None and source_id:
                target = next((entry for entry in entries.values() if entry.get('import_source_id') == source_id
                               and _identity(entry) == identity), None)
            if target is None and item['unit']:
                target = next((entry for entry in entries.values() if _identity(entry) == identity), None)
            if target is None and kind == 'external' and not source_id:
                target = next((entry for entry in entries.values() if entry.get('service_type') == 'external'
                               and urls.get(entry['id'], entry.get('open_url', '')) == item['open_url']), None)
            if target is None:
                if len(registered) >= 200:
                    raise ValueError('Service limit reached (200 registered entries). No changes were imported.')
                target = {'id': 'svc-' + uuid.uuid4().hex, 'name': item['display_name'],
                          'description': item['description'], 'category': item['category'],
                          'scope': item['scope'], 'unit': item['unit'], 'host_id': host_id,
                          'service_type': kind, 'port': item['port'],
                          'web': bool(item['open_url']) or (kind == 'local' and item['category'] == 'Websites'),
                          'open_url': item['open_url'], 'favorite': False}
                if source_id:
                    target['import_source_id'] = source_id
                registered.append(target)
                entries[target['id']] = target
                added += 1
            else:
                conflicts.append({'id': target['id'], 'name': item['display_name']})
                if not overwrite:
                    skipped += 1
                    continue
                updated += 1
                if target['id'].startswith('svc-'):
                    target['description'] = item['description']
                    target['category'] = item['category']
                    target['web'] = bool(item['open_url']) or (kind == 'local' and item['category'] == 'Websites')
                else:
                    metadata[target['id']] = {'description': item['description'], 'category': item['category']}
            service_id = target['id']
            if item['display_name'] == target['name']:
                names.pop(service_id, None)
            else:
                names[service_id] = item['display_name']
            urls[service_id] = item['open_url']
            ports[service_id] = item['port']
            if item['favorite']:
                favorites.add(service_id)
            else:
                favorites.discard(service_id)
        if not dry_run:
            registry.write('hosts.json', hosts)
            registry.write('registered-services.json', registered)
            registry.write('service-metadata.json', metadata)
            registry.write('service-names.json', names)
            registry.write('service-open-urls.json', urls)
            registry.write('service-ports.json', ports)
            registry.write('service-favorites.json', sorted(favorites))
    return {'added': added, 'updated': updated, 'hosts_added': created_hosts,
            'skipped': skipped, 'conflicts': conflicts,
            'untrusted_hosts_added': created_hosts, 'warnings': []}
