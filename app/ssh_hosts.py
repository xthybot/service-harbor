"""Host registration, dedicated identity and fixed noninteractive SSH transport."""
import base64
import hashlib
import ipaddress
import os
import re
import shlex
import subprocess
import uuid
import tempfile
from datetime import datetime, timezone
from . import registry

SSH_DIR = registry.DATA_DIR / 'ssh'
PRIVATE_KEY = SSH_DIR / 'dashboard_ed25519'
PUBLIC_KEY = SSH_DIR / 'dashboard_ed25519.pub'


def public_key() -> dict:
    try:
        value = PUBLIC_KEY.read_text().strip()
    except FileNotFoundError:
        return {'public_key': '', 'fingerprint': ''}
    return {'public_key': value, 'fingerprint': fingerprint(value)}


def ensure_key() -> dict:
    with registry.LOCK:
        SSH_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(SSH_DIR, 0o700)
        if not PRIVATE_KEY.exists():
            result = subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'host-service-dashboard', '-f', str(PRIVATE_KEY)], capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise ValueError('Could not create the dashboard SSH key.')
        os.chmod(PRIVATE_KEY, 0o600)
        if not PUBLIC_KEY.exists():
            result = subprocess.run(['/usr/bin/ssh-keygen', '-y', '-f', str(PRIVATE_KEY)], capture_output=True, text=True, timeout=5)
            if result.returncode:
                raise ValueError('Could not recover the public key.')
            PUBLIC_KEY.write_text(result.stdout.strip() + ' host-service-dashboard\n')
        os.chmod(PUBLIC_KEY, 0o600)
        return public_key()


def fingerprint(key: str) -> str:
    parts = key.split()
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (IndexError, ValueError) as error:
        raise ValueError('Invalid SSH public key.') from error
    return 'SHA256:' + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')


def _validate_host(body: dict) -> dict:
    address = body.get('address', '').strip()
    try:
        address = str(ipaddress.ip_address(address))
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?', address):
            raise ValueError('Enter a valid IP address or hostname, without a URL or shell characters.')
    user = body.get('username', '').strip()
    if not re.fullmatch(r'[a-z_][a-z0-9_\-]{0,31}\$?', user):
        raise ValueError('Enter a valid Linux account name.')
    if user == 'root':
        raise ValueError('Use a non-root SSH account and exact sudo permissions for service controls.')
    name = ' '.join(body.get('name', '').split())[:80]
    if not name:
        raise ValueError('Enter a host display name.')
    port = body.get('port', 22)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('SSH port must be between 1 and 65535.')
    return {'name': name, 'address': address, 'username': user, 'port': port}


def save_host(body: dict, host_id: str | None = None) -> dict:
    config = _validate_host(body)
    with registry.LOCK:
        records = registry.hosts()
        if host_id:
            item = registry.host(host_id)
            reset = any(item[k] != config[k] for k in ('address', 'port'))
            item.update(config)
            item.update({'connection': 'Unchecked', 'checked_at': None, 'last_error': '', 'journal_access': None})
            if reset:
                item.update({'trusted': False, 'host_key': '', 'fingerprint': '', 'pending_key': '', 'pending_fingerprint': ''})
                _known_hosts(host_id).unlink(missing_ok=True)
            records = [item if row['id'] == host_id else row for row in records]
        else:
            if len(records) >= 50:
                raise ValueError('Host limit reached (50).')
            item = {'id': uuid.uuid4().hex, **config, 'trusted': False, 'connection': 'Unchecked', 'checked_at': None,
                    'last_error': '', 'journal_access': None, 'fingerprint': ''}
            records.append(item)
        registry.write('hosts.json', records)
        return safe_host(item)


def safe_host(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in {'host_key', 'pending_key'}}


def _known_hosts(host_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', host_id):
        raise ValueError('Invalid host ID')
    return SSH_DIR / (host_id + '.known_hosts')


def scan_host(host_id: str) -> dict:
    item = registry.host(host_id)
    result = subprocess.run(['/usr/bin/ssh-keyscan', '-T', '4', '-p', str(item['port']), '-t', 'ed25519,ecdsa,rsa', item['address']], capture_output=True, text=True, timeout=16)
    keys = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in {'ssh-ed25519', 'ecdsa-sha2-nistp256', 'ssh-rsa'}:
            key = ' '.join(parts[1:])
            keys.append((parts[1] != 'ssh-ed25519', key))
    if not keys:
        raise ValueError('No SSH host key received. Check the address, SSH port and network.')
    key = sorted(keys)[0][1]
    value = fingerprint(key)
    with registry.LOCK:
        current = registry.host(host_id)
        if any(current[k] != item[k] for k in ('address', 'port')):
            raise ValueError('Host address changed during scanning. Scan it again.')
        registry.update_host(host_id, {'pending_key': key, 'pending_fingerprint': value})
    return {'fingerprint': value, 'algorithm': key.split()[0], 'address': item['address'], 'port': item['port']}


def trust_host(host_id: str, expected: str) -> dict:
    with registry.LOCK:
        item = registry.host(host_id)
        if not expected or expected != item.get('pending_fingerprint') or not item.get('pending_key'):
            raise ValueError('Scan the host key and confirm the displayed fingerprint first.')
        SSH_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        address = item['address'] if item['port'] == 22 else f"[{item['address']}]:{item['port']}"
        path = _known_hosts(host_id)
        fd, temp = tempfile.mkstemp(prefix='known-host-', dir=SSH_DIR)
        try:
            with os.fdopen(fd, 'w') as file:
                file.write(address + ' ' + item['pending_key'] + '\n')
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        saved = registry.update_host(host_id, {'trusted': True, 'host_key': item['pending_key'], 'fingerprint': expected,
                                              'pending_key': '', 'pending_fingerprint': '', 'connection': 'Unchecked', 'last_error': ''})
        return safe_host(saved)


def ssh_command(host_id: str, command: list[str]) -> list[str]:
    item = registry.host(host_id)
    if not item.get('trusted'):
        raise ValueError('Host fingerprint has not been confirmed in Hosts.')
    if not PRIVATE_KEY.exists() or not _known_hosts(host_id).exists():
        raise ValueError('SSH key or trusted host key is missing. Configure it in Hosts.')
    # SSH transmits a command string to the remote noninteractive command session.
    # All commands are built by backend code, with strict unit validation and quoting.
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-n', '-a', '-x',
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', f'UserKnownHostsFile={_known_hosts(host_id)}',
            '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
            '-o', 'ClearAllForwardings=yes', '-o', 'LogLevel=ERROR',
            '-i', str(PRIVATE_KEY), '-p', str(item['port']), '-l', item['username'], item['address'], shlex.join(command)]


def run(host_id: str, command: list[str], timeout: int = 12):
    return subprocess.run(ssh_command(host_id, command), capture_output=True, text=True, timeout=timeout, check=False)


def check_host(host_id: str) -> dict:
    original = registry.host(host_id)
    changes = {'checked_at': datetime.now(timezone.utc).isoformat(), 'journal_access': False, 'systemd_available': False}
    try:
        result = run(host_id, ['/usr/bin/id'])
        if result.returncode:
            raise ValueError(result.stderr.strip()[:1200] or 'SSH connection failed.')
        version = run(host_id, ['/usr/bin/systemctl', '--version'])
        journal = run(host_id, ['/usr/bin/journalctl', '--system', '--no-pager', '-n', '1', '-o', 'short-iso'])
        restricted = any(text in (journal.stdout + journal.stderr).lower() for text in ('not seeing messages', 'permission denied', 'no journal files', 'insufficient permissions'))
        groups = re.findall(r'\(([^)]+)\)', result.stdout)
        access = journal.returncode == 0 and not restricted and any(g in groups for g in ('adm', 'systemd-journal'))
        changes.update({'connection': 'Connected', 'account': result.stdout.strip()[:500],
                        'systemd_available': version.returncode == 0, 'journal_access': access,
                        'last_error': '' if access else 'SSH works. System journal access is unverified or limited; grant systemd-journal membership if needed.'})
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        changes.update({'connection': 'Unavailable', 'last_error': 'SSH command timed out.' if isinstance(error, subprocess.TimeoutExpired) else str(error)[:1200]})
    with registry.LOCK:
        current = registry.host(host_id)
        if any(current.get(k) != original.get(k) for k in ('address', 'port', 'username', 'trusted', 'fingerprint')):
            raise ValueError('Host settings changed during the connection check. Check the connection again.')
        return safe_host(registry.update_host(host_id, changes))


def delete_host(host_id: str) -> None:
    with registry.LOCK:
        registry.host(host_id)
        if any(item.get('host_id') == host_id for item in registry.registered_services()):
            raise ValueError('Remove this host’s registered services before deleting the host.')
        if any(item.get('host_id') == host_id for item in registry.read('manual-ports.json')):
            raise ValueError('Remove this host’s manual port entries in Open ports before deleting the host.')
        registry.write('hosts.json', [item for item in registry.hosts() if item['id'] != host_id])
        _known_hosts(host_id).unlink(missing_ok=True)
