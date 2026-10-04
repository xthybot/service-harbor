"""Persist user-assigned service ports without probing network sockets."""
import os
from pathlib import Path
from .catalog import SERVICE_BY_ID
from . import storage
from . import registry

DATA_DIR = Path(os.environ.get('DASHBOARD_DATA_DIR', Path(__file__).resolve().parent.parent / 'data'))
PORTS_FILE = DATA_DIR / 'service-ports.json'


@storage.locked
def get_ports() -> dict[str, int | None]:
    value = storage.read('service-ports.json', {})
    if not isinstance(value, dict):
        raise ValueError("Invalid saved settings; restore the JSON file before editing.")
    return {service_id: port for service_id, port in value.items()
            if service_id in SERVICE_BY_ID and (port is None or type(port) is int and 1 <= port <= 65535)}


@storage.locked
def set_port(service_id: str, port: int | None) -> int | None:
    if service_id not in SERVICE_BY_ID:
        raise KeyError('Unknown service')
    if port is not None and (type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('Port must be between 1 and 65535.')
    with registry.LOCK:
        ports = get_ports()
        ports[service_id] = port
        storage.write('service-ports.json', ports)
    return port
