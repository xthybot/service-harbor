"""Explicit service allowlist and dashboard metadata."""

import os

SERVICES = [
    {"id": "host-service-dashboard.service", "name": "Host Service Dashboard", "scope": os.environ.get("DASHBOARD_INSTALL_MODE", "user"), "description": "This service dashboard", "category": "Management", "port": int(os.environ.get("DASHBOARD_PORT", "8765")), "web": True, "control_allowed": os.environ.get("DASHBOARD_INSTALL_MODE", "user") == "user"},

]

# A read-through mapping keeps persisted registrations visible to existing callers.
from collections.abc import Mapping


class ServiceCatalog(Mapping):
    def _snapshot(self):
        from .storage import LOCK
        with LOCK:
            return self._locked_snapshot()

    def _locked_snapshot(self):
        from .registry import registered_services, service_metadata, local_catalog
        metadata = service_metadata()
        return {**{item['id']: {**item, **metadata.get(item['id'], {})} for item in [*SERVICES, *local_catalog()]},
                **{item['id']: item for item in registered_services()}}

    def __getitem__(self, key):
        return self._snapshot()[key]

    def __iter__(self):
        return iter(self._snapshot())

    def __len__(self):
        return len(self._snapshot())

    def values(self):
        return self._snapshot().values()


SERVICE_BY_ID = ServiceCatalog()
SYSTEM_ACTIONS = {'start', 'stop', 'restart'}
