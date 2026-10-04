"""Shared HTTP URL validation; parsing plus IP/IDNA authority validation."""
import ipaddress
import re
import unicodedata
from urllib.parse import urlsplit


def validate_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError('Enter an HTTP or HTTPS URL.')
    # Check before urlsplit: it silently strips some control characters.
    if any(unicodedata.category(c) in {'Cc', 'Cs'} for c in url) or '\\' in url:
        raise ValueError('The URL contains invalid characters.')
    url = url.strip()
    if not url:
        return ''
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
        if (len(url) > 2048 or parsed.scheme.lower() not in {'http', 'https'} or not host
                or '@' in parsed.netloc or parsed.netloc.endswith(':')
                or port is not None and not 1 <= port <= 65535
                or any(c.isspace() for c in parsed.netloc) or '%' in parsed.netloc):
            raise ValueError()
        if ':' in host:
            ipaddress.IPv6Address(host)
            if not parsed.netloc.startswith('['):
                raise ValueError()
        else:
            ascii_host = host.encode('idna').decode('ascii').rstrip('.')
            labels = ascii_host.split('.')
            if len(ascii_host) > 253 or any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in labels):
                raise ValueError()
            if all(c.isdigit() or c == '.' for c in ascii_host):
                ipaddress.IPv4Address(ascii_host)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Enter an HTTP or HTTPS URL with a valid host and port, without embedded credentials.') from error
    return url
