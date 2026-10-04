"""Private JSON records for SSH hosts and explicitly registered services."""
import os
import re
import uuid
from pathlib import Path
from .service_url_validation import validate_url

DATA_DIR = Path(os.environ.get('DASHBOARD_DATA_DIR', Path(__file__).resolve().parent.parent / 'data'))
from . import storage
LOCK = storage.LOCK
UNIT_PATTERN = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_@:.\-]*\.(?:service|socket)$')


def read(name: str) -> list[dict]:
    value = storage.read(name, [])
    if not isinstance(value, list):
        raise ValueError(f'Invalid {name}; restore the configuration before writing changes.')
    return value


def write(name: str, value) -> None:
    storage.write(name, value)


def local_catalog():
    records = read('local-catalog.json')
    seen = {'host-service-dashboard.service'}
    for item in records:
        if not isinstance(item, dict) or not UNIT_PATTERN.fullmatch(item.get('id', '')) or item.get('scope') not in ('user', 'system') or not isinstance(item.get('name'), str) or not isinstance(item.get('category'), str) or item['id'] in seen:
            raise ValueError('Invalid private local catalog')
        seen.add(item['id'])
    return records


def hosts() -> list[dict]:
    with LOCK:
        return read('hosts.json')


def host(host_id: str) -> dict:
    for item in hosts():
        if item['id'] == host_id:
            return item
    raise ValueError('Unknown host')


def update_host(host_id: str, changes: dict) -> dict:
    with LOCK:
        records = hosts()
        for item in records:
            if item['id'] == host_id:
                item.update(changes)
                write('hosts.json', records)
                return item
        raise ValueError('Unknown host')


def registered_services() -> list[dict]:
    with LOCK:
        return read('registered-services.json')


@storage.locked
def service_metadata() -> dict[str, dict]:
    value = storage.read('service-metadata.json', {})
    if not isinstance(value, dict):
        raise ValueError('Invalid service metadata; restore the configuration before editing.')
    result = {}
    for service_id, item in value.items():
        if not isinstance(service_id, str) or not isinstance(item, dict):
            raise ValueError('Invalid service metadata; restore the configuration before editing.')
        category = item.get('category')
        description = item.get('description')
        if category not in {'Websites', 'Tools', 'Automation', 'Gateways', 'Monitoring', 'Network', 'Remote Access', 'Management', 'Other'} or not isinstance(description, str) or len(description) > 240:
            raise ValueError('Invalid service metadata; restore the configuration before editing.')
        result[service_id] = {'category': category, 'description': description}
    return result


CATEGORIES = {'Websites', 'Tools', 'Automation', 'Gateways', 'Monitoring', 'Network', 'Remote Access', 'Management', 'Other'}


def normalize_service_fields(body: dict) -> dict:
    """One set of stored-field invariants for add/edit/settings/import."""
    name = ' '.join(body.get('display_name', '').split())
    category = body.get('category')
    description = body.get('description', '').strip()
    kind = body.get('service_type')
    scope = body.get('scope')
    unit = body.get('unit', '').strip()
    port = body.get('port')
    url = validate_url(body.get('open_url', ''))
    if not name or len(name) > 80:
        raise ValueError('Enter a display name (up to 80 characters).')
    if category not in {'Websites', 'Tools', 'Automation', 'Gateways', 'Monitoring', 'Network', 'Remote Access', 'Management', 'Other'}:
        raise ValueError('Invalid category.')
    if len(description) > 240:
        raise ValueError('Description must be at most 240 characters.')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('Port must be between 1 and 65535.')
    if kind not in {'local', 'remote', 'external'}:
        raise ValueError('Invalid service location.')
    if kind == 'external':
        if not url or unit or port is not None:
            raise ValueError('External links need an Open URL and cannot have a unit or Port.')
        host_id, scope = '', 'external'
    else:
        host_id = body.get('host_id', 'local') if kind == 'remote' else 'local'
        if scope not in {'user', 'system'} or unit and not UNIT_PATTERN.fullmatch(unit):
            raise ValueError('Enter a valid service scope and unit.')
        if port is not None and not unit:
            raise ValueError('A systemd unit is required to assign a service port.')
    return {**body, 'display_name': name, 'description': description, 'category': category,
            'service_type': kind, 'scope': scope, 'unit': unit, 'host_id': host_id,
            'open_url': url, 'port': port}


def update_service(service_id: str, body: dict) -> dict:
    from .catalog import SERVICE_BY_ID
    body = normalize_service_fields(body)
    name, description, category = body['display_name'], body['description'], body['category']
    kind, scope, unit, host_id = (body[k] for k in ('service_type', 'scope', 'unit', 'host_id'))
    port, url = body['port'], body['open_url']
    with LOCK:
        current = SERVICE_BY_ID[service_id]
        registered = service_id.startswith('svc-')
        if not registered:
            current_kind = current.get('service_type', 'local')
            current_unit = current.get('unit', current['id'])
            if (kind, host_id, scope, unit) != (current_kind, current.get('host_id', 'local'), current['scope'], current_unit):
                raise ValueError('Host, scope and unit are fixed for built-in services.')
            metadata = service_metadata()
            metadata[service_id] = {'category': category, 'description': description}
            write('service-metadata.json', metadata)
            return {**current, 'category': category, 'description': description}
        if kind == 'remote':
            target = host(host_id)
            if unit and not target.get('trusted'):
                raise ValueError('Confirm this host fingerprint in Hosts first.')
        for other in SERVICE_BY_ID.values():
            if other['id'] != service_id and unit and other.get('host_id', 'local') == host_id and other['scope'] == scope and other.get('unit', other['id']) == unit:
                raise ValueError('This unit and scope are already registered on this host.')
        records = registered_services()
        for entry in records:
            if entry['id'] == service_id:
                entry.update({'description': description, 'category': category, 'scope': scope, 'unit': unit,
                              'host_id': host_id, 'service_type': kind, 'port': port,
                              'web': bool(url) or (kind == 'local' and category == 'Websites'), 'open_url': url})
                write('registered-services.json', records)
                return entry
        raise ValueError('Registered service not found.')


def add_service(body: dict) -> dict:
    from .catalog import SERVICE_BY_ID
    body = normalize_service_fields(body)
    name, kind, url = body['display_name'], body['service_type'], body['open_url']
    host_id, scope, unit, port = (body[k] for k in ('host_id', 'scope', 'unit', 'port'))
    with LOCK:
        # Host mutation/deletion and registration share this lock.
        if kind == 'remote':
            target = host(host_id)
            if unit and not target.get('trusted'):
                raise ValueError('Confirm this host fingerprint in Hosts first.')
        records = registered_services()
        if len(records) >= 200:
            raise ValueError('Service limit reached (200 registered entries).')
        for service in SERVICE_BY_ID.values():
            if unit and kind != 'external' and service.get('host_id', 'local') == host_id and service['scope'] == scope and service.get('unit', service['id']) == unit:
                raise ValueError('This unit and scope are already registered on this host.')
        entry = {'id': 'svc-' + uuid.uuid4().hex, 'name': name, 'description': body.get('description', '').strip()[:240],
                 'category': body.get('category', 'Other'), 'scope': scope, 'unit': unit, 'host_id': host_id,
                 'service_type': kind, 'port': port, 'web': bool(url) or (kind == 'local' and body.get('category') == 'Websites'), 'open_url': url, 'favorite': False}
        if entry['category'] not in {'Websites', 'Tools', 'Automation', 'Gateways', 'Monitoring', 'Network', 'Remote Access', 'Management', 'Other'}:
            raise ValueError('Invalid category.')
        records.append(entry)
        write('registered-services.json', records)
        return entry


def delete_service(service_id: str) -> None:
    with LOCK:
        records = registered_services()
        remaining = [item for item in records if item['id'] != service_id]
        if len(remaining) == len(records):
            raise ValueError('Only services registered through the dashboard can be removed.')
        write('registered-services.json', remaining)
