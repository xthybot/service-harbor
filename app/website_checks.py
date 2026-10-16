"""Opt-in website reachability from the Dashboard host; no SSH or unit control."""
import http.client
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .service_url_validation import validate_url

TIMEOUT = 4


def normalize(value, *, managed=False, url=''):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - {'method', 'address', 'port'}:
        raise ValueError('Invalid website check settings.')
    method = value.get('method', 'disabled')
    if method not in ('disabled', 'http', 'tcp'):
        raise ValueError('Choose Disabled, HTTP / HTTPS, or TCP.')
    if managed:
        return {'method': 'disabled'}
    if method == 'disabled':
        return {'method': method}
    url = validate_url(url)
    parsed = urlsplit(url)
    if method == 'http':
        if not url:
            raise ValueError('HTTP / HTTPS checks require an Open URL.')
        return {'method': method}
    from .manual_ports import _address
    address = value.get('address', '')
    if not isinstance(address, str):
        raise ValueError('Enter a TCP hostname or IP address.')
    address = _address(address) if address.strip() else ''
    port = value.get('port')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('TCP port must be between 1 and 65535.')
    if not (address or parsed.hostname) or not (port or parsed.port or parsed.scheme):
        raise ValueError('Specify a TCP host and port, or an Open URL.')
    return {'method': method, 'address': address, 'port': port}


def check(settings, url):
    method = settings.get('method', 'disabled')
    if method == 'disabled':
        return None
    result = {'method': method, 'status': 'Stopped', 'error': '', 'http_status': None}
    connection = None
    try:
        parsed = urlsplit(validate_url(url))
        if method == 'http':
            connection_type = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
            kwargs = {'context': ssl.create_default_context()} if parsed.scheme == 'https' else {}
            connection = connection_type(parsed.hostname, parsed.port, timeout=TIMEOUT, **kwargs)
            # GET headers only: no response-body download, cookies, proxy environment,
            # authentication or redirect following. TLS verification remains enabled.
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            result['target'] = url
            connection.request('GET', target, headers={'User-Agent': 'ServiceHarbor-Check/1', 'Connection': 'close'})
            response = connection.getresponse()
            code = response.status
            result['http_status'] = code
            result['status'] = 'Running' if 200 <= code < 400 or code in (401, 403) else 'Stopped'
            if result['status'] == 'Stopped':
                result['error'] = f'HTTP {code}'
        else:
            address = settings.get('address') or parsed.hostname
            port = settings.get('port') or parsed.port or (443 if parsed.scheme == 'https' else 80)
            result['target'] = f'{address}:{port}'
            with socket.create_connection((address, port), timeout=TIMEOUT):
                result['status'] = 'Running'
    except (OSError, ValueError, UnicodeError, http.client.HTTPException) as error:
        result['error'] = str(error)[:300]
    finally:
        if connection:
            connection.close()
    result['checked_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return result


def details(result):
    if not result:
        return 'Website checks disabled. No systemd unit configured; journal and controls are unavailable.'
    return '\n'.join([f"Check: {result['method'].upper()}", f"Target: {result.get('target', 'Unavailable')}",
                      f"Status: {result['status']}", f"Last checked: {result['checked_at']}",
                      f"HTTP status: {result['http_status']}" if result['http_status'] else '',
                      f"Reason: {result['error']}" if result['error'] else '',
                      'Checked from the Dashboard host. Journal and controls are unavailable.'])
