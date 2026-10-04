"""Private manual port inventory with bounded TCP reachability checks."""

import fcntl
import ipaddress
import re
import socket
import struct
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import registry, service_ports
from .catalog import SERVICE_BY_ID

FILE_NAME = 'manual-ports.json'
MAX_RECORDS = 100
ADDRESS_PATTERN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\Z')


class DuplicatePortError(ValueError):
    pass


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _address(value: str) -> str:
    value = value.strip().lower()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        if not ADDRESS_PATTERN.fullmatch(value) or '..' in value:
            raise ValueError('Enter an IP address or hostname without a URL.')
        return value
    if address.is_unspecified or address.is_multicast:
        raise ValueError('Enter a host address, not a wildcard or multicast address.')
    return str(address)


def _local_addresses() -> set[str]:
    addresses = {'localhost', '127.0.0.1', '::1'}
    try:
        interfaces = socket.if_nameindex()
    except OSError:
        interfaces = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in interfaces:
            try:
                address = fcntl.ioctl(sock.fileno(), 0x8915, struct.pack('256s', name.encode()[:15]))[20:24]
                addresses.add(str(ipaddress.ip_address(address)))
            except OSError:
                continue
    try:
        for line in Path('/proc/net/if_inet6').read_text().splitlines():
            addresses.add(str(ipaddress.ip_address(int(line.split()[0], 16))))
    except OSError:
        pass
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None):
            addresses.add(result[4][0].split('%', 1)[0])
    except OSError:
        pass
    return addresses


def _host_key(address: str, aliases: set[str] | None = None) -> str:
    return 'local' if address in (aliases if aliases is not None else _local_addresses()) else address


def _target(body: dict) -> dict:
    host_id = body.get('host_id', 'local')
    if host_id == 'local':
        return {'host_id': 'local', 'host_name': 'This host', 'address': '127.0.0.1', 'key': 'local'}
    if host_id == 'custom':
        address = _address(body.get('address') or '')
        return {'host_id': 'custom:' + address, 'host_name': address, 'address': address,
                'key': _host_key(address)}
    host = registry.host(host_id)
    address = _address(host['address'])
    return {'host_id': host_id, 'host_name': host['name'], 'address': address, 'key': _host_key(address)}


def _config(body: dict) -> dict:
    name = ' '.join((body.get('name') or '').split())
    source = (body.get('source') or '').strip()
    port = body.get('port')
    if not name or len(name) > 80:
        raise ValueError('Enter a service name (up to 80 characters).')
    if len(source) > 240:
        raise ValueError('Service / source must be at most 240 characters.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Port must be between 1 and 65535.')
    return {'name': name, 'source': source, 'port': port, **_target(body)}


def _key_for_host(host_id: str, hosts: dict, aliases: set[str]) -> str:
    if host_id == 'local':
        return 'local'
    host = hosts.get(host_id)
    return _host_key(_address(host['address']), aliases) if host else host_id


def _duplicates(config: dict, records: list[dict], exclude_id: str | None = None) -> list[str]:
    host_map = {host['id']: host for host in registry.hosts()}
    aliases = _local_addresses()
    overrides = service_ports.get_ports()
    duplicates = []
    for service in SERVICE_BY_ID.values():
        port = overrides.get(service['id'], service.get('port'))
        if port == config['port'] and _key_for_host(service.get('host_id', 'local'), host_map, aliases) == config['key']:
            duplicates.append(service['name'])
    for item in records:
        item_key = _key_for_host(item['host_id'], host_map, aliases) if not item['host_id'].startswith('custom:') else _host_key(item['address'], aliases)
        if item['id'] != exclude_id and item['port'] == config['port'] and item_key == config['key']:
            duplicates.append(item['name'])
    return duplicates


def _probe(address: str, port: int) -> dict:
    checked_at = _timestamp()
    try:
        with socket.create_connection((address, port), timeout=1):
            return {'status': 'Open', 'checked_at': checked_at, 'error': ''}
    except OSError as error:
        return {'status': 'Unreachable', 'checked_at': checked_at, 'error': str(error)[:160]}


def check(body: dict, exclude_id: str | None = None) -> dict:
    config = _config(body)
    duplicates = _duplicates(config, registry.read(FILE_NAME), exclude_id)
    return {**_probe(config['address'], config['port']), 'duplicates': duplicates}


def _inspect_record(item: dict, hosts: dict) -> dict:
    host = hosts.get(item['host_id'])
    address = _address(host['address']) if host else item['address']
    host_name = host['name'] if host else item['host_name']
    result = _probe(address, item['port']) if item['host_id'].startswith('custom:') or item['host_id'] == 'local' or host else {
        'status': 'Unavailable', 'checked_at': _timestamp(), 'error': 'Registered host was removed.'}
    return {**item, 'host_name': host_name, 'address': address, **result, 'manual': True}


def check_record(record_id: str) -> dict:
    item = next((record for record in registry.read(FILE_NAME) if record['id'] == record_id), None)
    if item is None:
        raise ValueError('Manual port entry not found.')
    hosts = {host['id']: host for host in registry.hosts()}
    return _inspect_record(item, hosts)


def list_checked() -> dict:
    records = registry.read(FILE_NAME)
    hosts = {host['id']: host for host in registry.hosts()}

    with ThreadPoolExecutor(max_workers=12) as executor:
        ports = list(executor.map(lambda item: _inspect_record(item, hosts), records))
    return {'ports': ports, 'checked_at': _timestamp()}


def _inspect_configured(service: dict, assigned_ports: dict, hosts: dict, names: dict) -> dict | None:
    port = assigned_ports.get(service['id'], service.get('port'))
    if not port:
        return None
    host_id = service.get('host_id') or 'local'
    host = hosts.get(host_id)
    address = _address(host['address']) if host else '127.0.0.1' if host_id == 'local' else ''
    host_name = host['name'] if host else 'This host' if host_id == 'local' else 'Unknown host'
    result = _probe(address, port) if address else {
        'status': 'Unavailable', 'checked_at': _timestamp(), 'error': 'Registered host was removed.'}
    return {'id': 'service:' + service['id'], 'service_id': service['id'],
            'host_id': host_id, 'host_name': host_name, 'address': address,
            'name': names.get(service['id'], service['name']), 'source': service.get('unit', service['id']),
            'port': port, **result, 'manual': False}


def check_configured(service_id: str) -> dict | None:
    from .service_names import get_names
    service = SERVICE_BY_ID[service_id]
    hosts = {host['id']: host for host in registry.hosts()}
    return _inspect_configured(service, service_ports.get_ports(), hosts, get_names())


def list_configured_checked() -> dict:
    from .service_names import get_names
    assigned_ports = service_ports.get_ports()
    hosts = {host['id']: host for host in registry.hosts()}
    names = get_names()
    services = [service for service in SERVICE_BY_ID.values()
                if assigned_ports.get(service['id'], service.get('port'))]
    with ThreadPoolExecutor(max_workers=12) as executor:
        ports = [port for port in executor.map(
            lambda service: _inspect_configured(service, assigned_ports, hosts, names), services) if port]
    targets = [{'id': 'local', 'name': 'This host'}, *hosts.values()]
    host_counts = [{'id': target['id'], 'name': target['name'],
                    'port_count': sum(port['host_id'] == target['id'] and port['status'] == 'Open' for port in ports)}
                   for target in targets]
    return {'ports': ports, 'hosts': host_counts, 'checked_at': _timestamp()}


def save(body: dict, record_id: str | None = None, confirm_duplicate: bool = False) -> dict:
    with registry.LOCK:
        config = _config(body)
        records = registry.read(FILE_NAME)
        if record_id and not any(item['id'] == record_id for item in records):
            raise ValueError('Manual port entry not found.')
        if not record_id and len(records) >= MAX_RECORDS:
            raise ValueError('Manual port limit reached (100 entries).')
        duplicates = _duplicates(config, records, record_id)
        if duplicates and not confirm_duplicate:
            raise DuplicatePortError('This host and port already have a record: ' + ', '.join(duplicates[:4]))
        entry = {'id': record_id or 'port-' + uuid.uuid4().hex, **config}
        records = [entry if item['id'] == record_id else item for item in records] if record_id else [*records, entry]
        registry.write(FILE_NAME, records)
    return {**entry, **_probe(config['address'], config['port']), 'manual': True}


def delete(record_id: str) -> None:
    with registry.LOCK:
        records = registry.read(FILE_NAME)
        remaining = [item for item in records if item['id'] != record_id]
        if len(remaining) == len(records):
            raise ValueError('Manual port entry not found.')
        registry.write(FILE_NAME, remaining)
