"""Read-only service status and configured ports plus allowlisted unit control."""

import asyncio
import anyio
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from . import registry, ssh_hosts

from .catalog import SERVICE_BY_ID, SYSTEM_ACTIONS

COMMAND_TIMEOUT = 8
MAX_LOG_LINES = 1000


def _run(args: list[str], timeout: int = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def is_managed(service: dict) -> bool:
    return service['scope'] != 'external' and bool(service.get('unit', service['id']))


def _unit(service: dict) -> str:
    unit = service.get('unit', service['id'])
    if not registry.UNIT_PATTERN.fullmatch(unit):
        raise ValueError('Invalid systemd unit')
    return unit


def _systemctl(service_id: str, *args: str) -> list[str]:
    service = SERVICE_BY_ID[service_id]
    if not is_managed(service):
        raise ValueError('No systemd unit configured; controls and journal are unavailable.')
    base = ['/usr/bin/systemctl']
    if service['scope'] == 'user':
        base.append('--user')
    return [*base, *args, _unit(service)]


def _execute(service: dict, args: list[str], timeout: int = COMMAND_TIMEOUT):
    if service.get('service_type') == 'remote':
        return ssh_hosts.run(service['host_id'], args, timeout=max(timeout, 12))
    return _run(args, timeout)


def get_port_inventory() -> dict:
    """Check configured TCP ports from this dashboard host."""
    from .manual_ports import list_configured_checked
    return list_configured_checked()


PROPERTIES = 'Id,Description,ActiveState,SubState,ActiveEnterTimestamp,FragmentPath,LoadState'


def _parse_properties(output: str) -> list[dict]:
    results = []
    for block in output.strip().split('\n\n'):
        props = {}
        for line in block.splitlines():
            key, sep, value = line.partition('=')
            if sep:
                props[key] = value
        if props:
            results.append(props)
    return results


def _group_properties(entries: list[dict]) -> dict:
    first = entries[0]
    args = ['/usr/bin/systemctl'] + (['--user'] if first['scope'] == 'user' else [])
    args += ['show', '--no-pager', '--property=' + PROPERTIES] + [_unit(item) for item in entries]
    try:
        result = _execute(first, args)
        checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        props = _parse_properties(result.stdout)
        # systemctl emits blocks in the same order as requested units, including aliases.
        return {entry['id']: {'props': props[index] if index < len(props) else {},
                              'error': result.stderr.strip()[:1200] if result.returncode else '',
                              'checked_at': checked_at}
                for index, entry in enumerate(entries)}
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        checked_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
        return {entry['id']: {'props': {}, 'error': str(error)[:1200], 'checked_at': checked_at} for entry in entries}


def inspect_unit(entry: dict) -> dict:
    result = _group_properties([entry])[entry['id']]
    if result['error'] or result['props'].get('LoadState') in {None, 'not-found', 'error', 'masked'}:
        raise ValueError(result['error'] or 'Unit not found, masked, or unavailable on the selected host.')
    return result['props']


def get_services(only_id: str | None = None) -> list[dict]:
    entries = [SERVICE_BY_ID[only_id]] if only_id else list(SERVICE_BY_ID.values())
    from .service_ports import get_ports
    assigned_ports = get_ports()
    groups = {}
    for entry in entries:
        if is_managed(entry):
            groups.setdefault((entry.get('host_id', 'local'), entry['scope']), []).append(entry)
    all_props = {}
    if groups:
        with ThreadPoolExecutor(max_workers=4) as executor:
            for result in executor.map(_group_properties, groups.values()):
                all_props.update(result)
    hosts = {item['id']: item for item in registry.hosts()}
    snapshot_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    rows = []
    for entry in entries:
        external = entry['scope'] == 'external'
        managed = is_managed(entry)
        record = all_props.get(entry['id'], {'props': {}, 'error': ''})
        props = record['props']
        active = props.get('ActiveState', 'not-found')
        host = hosts.get(entry.get('host_id'), {})
        missing_unit = props.get('LoadState') in {'not-found', 'error'}
        unavailable = bool(record['error']) or (managed and (not props or missing_unit))
        if missing_unit and not record['error']:
            record['error'] = 'Systemd unit not found or could not be loaded on this host.'
        rows.append({**entry,
            'execution_identity': journal_identity(entry['id']),
            'unit': entry.get('unit', entry['id']) if not external else '',
            'service_type': entry.get('service_type', 'local'),
            'host_name': host.get('name', 'This host') if not external else 'External website',
            'status': ('Linked' if entry.get('open_url') else 'Unmanaged') if not managed else 'Unavailable' if unavailable else 'Running' if active == 'active' else 'Failed' if active == 'failed' else 'Stopped',
            'substate': props.get('SubState', 'not-found'),
            'active_since': props.get('ActiveEnterTimestamp') or None,
            'checked_at': record.get('checked_at', snapshot_at),
            'system_description': props.get('Description', ''),
            'error': record['error'],
            'managed': managed,
            'controllable': managed and not unavailable and entry.get('control_allowed', True),
            'registered': entry['id'].startswith('svc-'),
            'configured_port': assigned_ports.get(entry['id'], entry.get('port')),
            'ports': [],
        })
    return rows


def get_service(service_id: str) -> dict:
    return get_services(only_id=service_id)[0]


def control_service(service_id: str, action: str) -> dict:
    if service_id not in SERVICE_BY_ID or action not in SYSTEM_ACTIONS:
        raise ValueError('Unknown service or unsupported action')
    service = SERVICE_BY_ID[service_id]
    if not is_managed(service):
        raise ValueError('No systemd unit configured; service controls are unavailable.')
    if not service.get('control_allowed', True):
        return {'ok': False, 'message': 'Service controls are disabled for this service.'}
    args = _systemctl(service_id, action)
    if service['scope'] == 'system':
        args = ['/usr/bin/sudo', '-n', *args]
    try:
        result = _execute(service, args, timeout=30)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        return {'ok': False, 'message': str(error)}
    output = (result.stdout or result.stderr).strip()
    if result.returncode and 'a password is required' in output.lower():
        output = 'Control permission missing. Install exact NOPASSWD sudo rules on the service host.'
    return {'ok': result.returncode == 0, 'message': output or ('Operation completed' if result.returncode == 0 else 'Operation failed')}


def get_status(service_id: str) -> str:
    if service_id not in SERVICE_BY_ID:
        raise ValueError('Unknown service')
    service = SERVICE_BY_ID[service_id]
    if not is_managed(service):
        return f"Service: {service['name']}\nLocation: {service.get('service_type', 'local')}\nSystemd unit: Not configured\nStatus monitoring, journal logs and controls are unavailable."
    identity = journal_identity(service_id)
    result = _execute(service, _systemctl(service_id, 'status', '--no-pager', '-n', '35'))
    if not _identity_matches(service_id, identity):
        raise ValueError('Service identity changed while loading status; reload the service.')
    return (result.stdout or result.stderr).strip() or 'No status output available.'


def _journal_command(service_id: str, lines: int, follow: bool = False, *, cursor: str = "", json_output: bool = False) -> list[str]:
    if service_id not in SERVICE_BY_ID:
        raise ValueError("Unknown service")
    unit = SERVICE_BY_ID[service_id]
    if not is_managed(unit):
        raise ValueError("No systemd unit configured; journal logs are unavailable.")
    args = ["/usr/bin/journalctl"]
    if unit["scope"] == "user":
        args.append("--user")
    cursor = validate_journal_cursor(cursor)
    # With a cursor, include its entry once to verify it still exists. The event
    # adapter discards only that exact cursor, never equal message text.
    # With --cursor, --no-tail starts at that exact entry and streams every
    # following record. Combining --cursor with a fixed -n can silently skip
    # earlier records when more than n arrived while disconnected.
    args.extend(["-u", _unit(unit), "--no-pager", "-o", "json" if json_output else "short-iso"])
    if cursor and follow:
        args.append('--no-tail')
    else:
        count = 0 if follow and not cursor else max(1, min(lines, MAX_LOG_LINES))
        args.extend(['-n', str(count)])
    if json_output:
        args.append("--output-fields=MESSAGE,SYSLOG_IDENTIFIER,_COMM,_PID,PRIORITY")
    if cursor:
        args.append("--cursor=" + cursor)
    if follow:
        args.append("--follow")
    if unit.get("service_type") == "remote":
        return ssh_hosts.ssh_command(unit["host_id"], args)
    return args


def get_recent_logs(service_id: str, lines: int = 200, query: str = "") -> list[str]:
    result = _run(_journal_command(service_id, lines), timeout=15)
    output = result.stdout.splitlines()
    if result.returncode and result.stderr:
        output.append(result.stderr.strip())
    if query:
        needle = query.casefold()
        output = [line for line in output if needle in line.casefold()]
    return output[-max(1, min(lines, MAX_LOG_LINES)):]


def validate_journal_cursor(cursor: str) -> str:
    """Opaque journal cursors may not inject options, transport or SSE framing."""
    if not isinstance(cursor, str) or len(cursor) > 4096 or any(not 32 < ord(c) < 127 for c in cursor):
        raise ValueError("Invalid journal cursor")
    return cursor


def journal_identity(service_id: str) -> str:
    """Execution identity, including transport/trust; display-only edits are safe."""
    from .storage import LOCK
    with LOCK:
        try:
            service = SERVICE_BY_ID[service_id]
        except KeyError as error:
            raise ValueError("Service identity changed or service was removed.") from error
        values = {key: service.get(key) for key in ('scope', 'host_id', 'service_type')}
        values.update(unit=service.get('unit', service['id']), managed=is_managed(service))
        if service.get('service_type') == 'remote':
            host = registry.host(service['host_id'])
            values['host'] = {key: host.get(key) for key in ('address', 'port', 'username', 'trusted', 'host_key', 'fingerprint')}
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _identity_matches(service_id: str, expected: str) -> bool:
    try:
        return journal_identity(service_id) == expected
    except (ValueError, KeyError):
        return False


def _journal_text(value) -> str:
    if isinstance(value, list):
        if all(isinstance(part, int) and 0 <= part <= 255 for part in value):
            return bytes(value).decode('utf-8', errors='replace')
        return ' '.join(str(part) for part in value)
    return str(value) if value is not None else ''


def _journal_record(raw: str) -> dict | None:
    try:
        entry = json.loads(raw)
        if not isinstance(entry, dict):
            return None
        cursor = validate_journal_cursor(entry.get('__CURSOR', ''))
        if not cursor:
            return None
        timestamp = datetime.fromtimestamp(int(entry['__REALTIME_TIMESTAMP']) / 1000000, timezone.utc).isoformat(timespec='seconds')
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return None
    name = _journal_text(entry.get('SYSLOG_IDENTIFIER') or entry.get('_COMM'))
    pid = _journal_text(entry.get('_PID'))
    name += f'[{pid}]' if pid else ''
    message = _journal_text(entry.get('MESSAGE'))
    priority = str(entry.get('PRIORITY', ''))
    level = 'ERROR ' if priority in {'0', '1', '2', '3'} else 'WARNING ' if priority == '4' else ''
    line = f"{timestamp} {name + ': ' if name else ''}{level}{message}"
    return {'event': 'message', 'line': line, 'cursor': cursor}


def get_recent_log_snapshot(service_id: str, lines: int = 200, query: str = "") -> dict:
    from .storage import LOCK
    with LOCK:
        identity = journal_identity(service_id)
        command = _journal_command(service_id, lines, json_output=True)
    # External I/O must not hold the global storage lock.
    result = _run(command, timeout=15)
    if not _identity_matches(service_id, identity):
        raise ValueError('Service identity changed while loading logs; reload the service.')
    records = []
    diagnostics = []
    for raw in result.stdout.splitlines():
        entry = _journal_record(raw)
        if entry:
            records.append(entry)
        elif raw.strip():
            diagnostics.append(raw[:1200])
    if result.stderr.strip():
        diagnostics.append(result.stderr.strip()[:1200])
    output = [entry['line'] for entry in records]
    if query:
        output = [line for line in output if query.casefold() in line.casefold()]
    snapshot = {'lines': output[-max(1, min(lines, MAX_LOG_LINES)):],
                'cursor': records[-1]['cursor'] if records else None, 'identity': identity}
    if diagnostics or result.returncode:
        snapshot['gap'] = 'Journal continuity unavailable: ' + ('; '.join(diagnostics) or 'journalctl failed.')
    return snapshot


def encode_log_event(event: dict) -> str:
    kind = event.get('event', 'message')
    prefix = '' if kind == 'message' else f'event: {kind}\n'
    if event.get('cursor'):
        prefix += 'id: ' + validate_journal_cursor(event['cursor']) + '\n'
    body = {key: value for key, value in event.items() if key not in {'event', 'cursor'}}
    return prefix + 'data: ' + json.dumps(body, ensure_ascii=False) + '\n\n'


async def stream_logs(service_id: str, lines: int = 100, *, session_valid=None, disconnected=None,
                      check_interval=5.0, structured=False, cursor='', identity=''):
    """Poll authorization and execution identity even while journal/SSH is silent.

    Structured consumers resume using the journal's identity, not message text.
    Legacy plain-text consumers retain their existing interface.
    """
    if session_valid is not None and not await asyncio.to_thread(session_valid):
        return
    expected = None
    if structured:
        validate_journal_cursor(cursor)
        try:
            expected = await asyncio.to_thread(journal_identity, service_id)
        except (ValueError, KeyError):
            yield {'event': 'identity_changed', 'message': 'Service was changed or removed. Reload its details.'}
            return
        if identity and expected != identity:
            yield {'event': 'identity_changed', 'message': 'Service identity changed. Reload its details.'}
            return
        def prepare():
            from .storage import LOCK
            with LOCK:
                if not _identity_matches(service_id, expected):
                    return None
                return _journal_command(service_id, lines, follow=True, cursor=cursor, json_output=True)
        command = await asyncio.to_thread(prepare)
        if command is None:
            yield {'event': 'identity_changed', 'message': 'Service identity changed. Reload its details.'}
            return
    else:
        command = _journal_command(service_id, lines, follow=True)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    read_task = None
    first_record = True
    try:
        assert process.stdout
        deadline = 0.0
        if structured and not cursor:
            yield {'event': 'gap', 'message': 'No journal cursor available; continuity with earlier logs cannot be verified.'}
        while True:
            now = asyncio.get_running_loop().time()
            if now >= deadline:
                if session_valid is not None and not await asyncio.to_thread(session_valid): break
                if disconnected is not None and await disconnected(): break
                if expected is not None and not await asyncio.to_thread(_identity_matches, service_id, expected):
                    yield {'event': 'identity_changed', 'message': 'Service or SSH host changed. Reload its details.'}
                    break
                deadline = asyncio.get_running_loop().time() + check_interval
            if read_task is None:
                read_task = asyncio.create_task(process.stdout.readline())
            try:
                data = await asyncio.wait_for(asyncio.shield(read_task), max(.001, deadline - asyncio.get_running_loop().time()))
            except asyncio.TimeoutError:
                continue
            read_task = None
            if not data:
                if structured and first_record:
                    yield {'event': 'gap', 'message': 'Journal stream ended before its cursor could be verified; continuity is unknown.'}
                break
            raw = data.decode("utf-8", errors="replace").rstrip("\r\n")
            if not structured:
                yield raw
                continue
            # A cross-tab mutation must not leak buffered old-unit output.
            if not await asyncio.to_thread(_identity_matches, service_id, expected):
                yield {'event': 'identity_changed', 'message': 'Service or SSH host changed. Reload its details.'}
                break
            event = _journal_record(raw)
            if event is None:
                yield {'event': 'gap', 'message': 'Journal continuity unavailable: ' + raw[:1200]}
                continue
            if first_record:
                first_record = False
                if cursor:
                    if event['cursor'] == cursor:
                        continue
                    yield {'event': 'gap', 'message': 'Previous journal cursor is no longer available; some events may be missing.'}
            yield event
    finally:
        # ASGI disconnect cancels the enclosing AnyIO scope; cleanup must still finish.
        with anyio.CancelScope(shield=True):
            if read_task is not None:
                read_task.cancel()
                await asyncio.gather(read_task, return_exceptions=True)
            if process.returncode is None:
                try: process.terminate()
                except ProcessLookupError: pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    try: process.kill()
                    except ProcessLookupError: pass
                    await process.wait()
