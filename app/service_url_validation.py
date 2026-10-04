"""Shared URL validation with no catalog/storage dependency."""
from urllib.parse import urlsplit


def validate_url(url: str) -> str:
    url = url.strip()
    if url:
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as error:
            raise ValueError('The URL contains an invalid host or port.') from error
        if len(url) > 2048 or parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in url):
            raise ValueError('Enter an HTTP or HTTPS URL without embedded credentials.')
    return url
