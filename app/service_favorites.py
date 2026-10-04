"""Persist favorite service IDs for the shared dashboard."""

import os
from pathlib import Path

from .catalog import SERVICE_BY_ID
from . import storage

DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
FAVORITES_FILE = DATA_DIR / "service-favorites.json"


@storage.locked
def get_favorites() -> set[str]:
    value = storage.read('service-favorites.json', [])
    if not isinstance(value, list):
        raise ValueError("Invalid saved favorites; restore the JSON file before editing.")
    return {service_id for service_id in value if isinstance(service_id, str) and service_id in SERVICE_BY_ID}


@storage.locked
def set_favorite(service_id: str, favorite: bool) -> bool:
    if service_id not in SERVICE_BY_ID:
        raise KeyError("Unknown service")
    favorites = get_favorites()
    if favorite:
        favorites.add(service_id)
    else:
        favorites.discard(service_id)
    _write(favorites)
    return favorite


def _write(favorites: set[str]) -> None:
    storage.write('service-favorites.json', sorted(favorites))
