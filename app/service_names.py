"""Persist user-defined display aliases for catalogued services."""

import os
from pathlib import Path

from .catalog import SERVICE_BY_ID
from . import storage

DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
NAMES_FILE = DATA_DIR / "service-names.json"


@storage.locked
def get_names() -> dict[str, str]:
    value = storage.read('service-names.json', {})
    if not isinstance(value, dict):
        raise ValueError("Invalid saved settings; restore the JSON file before editing.")
    return {
        service_id: name
        for service_id, name in value.items()
        if service_id in SERVICE_BY_ID and isinstance(name, str) and name.strip()
    }


@storage.locked
def set_display_name(service_id: str, name: str) -> str:
    if service_id not in SERVICE_BY_ID:
        raise KeyError("Unknown service")
    name = " ".join(name.split())[:80]
    if any(ord(char) < 32 for char in name):
        raise ValueError("Display name contains an invalid character.")
    names = get_names()
    if not name or name == SERVICE_BY_ID[service_id]["name"]:
        names.pop(service_id, None)
        display_name = SERVICE_BY_ID[service_id]["name"]
    else:
        names[service_id] = name
        display_name = name
    _write(names)
    return display_name


def _write(names: dict[str, str]) -> None:
    storage.write('service-names.json', names)
