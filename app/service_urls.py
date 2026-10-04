"""Persist optional custom open URLs for catalogued services."""

import os
from pathlib import Path
from .service_url_validation import validate_url

from .catalog import SERVICE_BY_ID
from . import storage

DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
URLS_FILE = DATA_DIR / "service-open-urls.json"


@storage.locked
def get_urls() -> dict[str, str]:
    value = storage.read('service-open-urls.json', {})
    if not isinstance(value, dict):
        raise ValueError("Invalid saved settings; restore the JSON file before editing.")
    return {
        service_id: url
        for service_id, url in value.items()
        if service_id in SERVICE_BY_ID and isinstance(url, str)
    }


@storage.locked
def set_url(service_id: str, url: str) -> str:
    if service_id not in SERVICE_BY_ID:
        raise KeyError("Unknown service")
    url = validate_url(url)
    urls = get_urls()
    if url or service_id.startswith("svc-"):
        urls[service_id] = url
    else:
        urls.pop(service_id, None)
    _write(urls)
    return url


def _write(urls: dict[str, str]) -> None:
    storage.write('service-open-urls.json', urls)
