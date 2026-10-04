"""HTTP API and static app entry point."""
import json
import os
import subprocess
import copy
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool
from .password_policy import validate_password, MIN_LENGTH, MAX_LENGTH
from . import storage
from . import config_transfer, manual_ports, security, service_favorites, service_names, service_ports, service_urls, systemd, registry, ssh_hosts
from .catalog import SERVICE_BY_ID

APP_DIR = Path(__file__).resolve().parent
COOKIE_SECURE = os.environ.get("DASHBOARD_COOKIE_SECURE", "0") == "1"
app = FastAPI(title="Host Service Dashboard", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

@app.middleware("http")
async def disable_ui_asset_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response

class LoginBody(BaseModel):
    password: str = Field(min_length=MIN_LENGTH, max_length=MAX_LENGTH)

    @field_validator('password')
    @classmethod
    def valid_password(cls, value):
        return validate_password(value)

class ServiceNameBody(BaseModel):
    display_name: str = Field(max_length=80)

class ServiceSettingsBody(BaseModel):
    display_name: str = Field(max_length=80)
    open_url: str = Field(default="", max_length=2048)
    port: int | None = Field(default=None, ge=1, le=65535)

class ServiceFavoriteBody(BaseModel):
    favorite: bool

class HostBody(BaseModel):
    name: str = Field(max_length=80)
    address: str = Field(max_length=253)
    username: str = Field(max_length=33)
    port: int = Field(default=22, ge=1, le=65535)

class TrustBody(BaseModel):
    fingerprint: str = Field(max_length=100)

class AddServiceBody(BaseModel):
    service_type: str
    display_name: str = Field(max_length=80)
    host_id: str = Field(default='local', max_length=40)
    unit: str = Field(default='', max_length=200)
    scope: str = Field(default='user', max_length=20)
    description: str = Field(default='', max_length=240)
    category: str = Field(default='Other', max_length=40)
    open_url: str = Field(default='', max_length=2048)
    port: int | None = Field(default=None, ge=1, le=65535)
    favorite: bool = False

class ManualPortBody(BaseModel):
    name: str = Field(max_length=80)
    source: str = Field(default='', max_length=240)
    host_id: str = Field(default='local', max_length=80)
    address: str = Field(default='', max_length=253)
    port: int = Field(ge=1, le=65535)
    confirm_duplicate: bool = False


def _safe_call(function, *args):
    try:
        return function(*args)
    except config_transfer.ImportConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except subprocess.TimeoutExpired as error:
        raise HTTPException(status_code=504, detail='SSH command timed out. Check the host connection.') from error
    except OSError as error:
        raise HTTPException(status_code=503, detail='Host operation failed; check server logs and file permissions.') from error


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"

def _authenticated(request: Request) -> str:
    return security.require_session(request)

@app.get("/")
def home():
    return FileResponse(APP_DIR / "static" / "index.html")

@app.get("/api/session")
def session_status(request: Request):
    try:
        security.require_session(request)
        return {"authenticated": True, "password_configured": security.password_is_configured()}
    except HTTPException:
        return {"authenticated": False, "password_configured": security.password_is_configured()}

@app.post("/api/login")
def login(body: LoginBody, request: Request, response: Response):
    security.require_same_origin(request)
    token = security.login(body.password, _client_id(request))
    if not token:
        raise HTTPException(status_code=401, detail="Password is incorrect or login is temporarily rate limited.")
    response.set_cookie(security.SESSION_COOKIE, token, max_age=security.SESSION_TTL, httponly=True, secure=COOKIE_SECURE, samesite="strict", path="/")
    return {"ok": True}

@app.post("/api/logout")
def logout(request: Request, response: Response, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    security.logout(request.cookies.get(security.SESSION_COOKIE))
    # Revocation is authoritative. A late Set-Cookie deletion could erase a newer login.
    return {"ok": True}

def _decorate_services(rows: list[dict]) -> list[dict]:
    names = service_names.get_names()
    favorites = service_favorites.get_favorites()
    open_urls = service_urls.get_urls()
    for service in rows:
        service["display_name"] = names.get(service["id"], service["name"])
        service["favorite"] = service["id"] in favorites
        service["open_url"] = open_urls.get(service["id"], service.get("open_url", ""))
        if not service["managed"]:
            service["status"] = "Linked" if service["open_url"] else "Unmanaged"
    return rows


@app.get("/api/services")
def services(_token: str = Depends(_authenticated)):
    rows = _decorate_services(systemd.get_services())
    return {'services': rows, 'port_hosts': [{'id': 'local', 'name': 'This host'},
            *[{'id': host['id'], 'name': host['name']} for host in registry.hosts()]]}


@app.get('/api/services/{service_id}/live')
def service_live(service_id: str, _token: str = Depends(_authenticated)):
    if service_id not in SERVICE_BY_ID:
        raise HTTPException(status_code=404, detail='Unknown service')
    service = _decorate_services([systemd.get_service(service_id)])[0]
    port = manual_ports.check_configured(service_id) if service['configured_port'] else None
    return {'service': service, 'port': port}

@app.get('/api/services/export')
def export_services(response: Response, selection: str = 'all', value: str = '', _token: str = Depends(_authenticated)):
    response.headers['Cache-Control'] = 'no-store'
    return _safe_call(config_transfer.export_config, selection, value)

async def _read_service_config(request: Request) -> dict:
    security.require_same_origin(request)
    limit = 1024 * 1024
    declared = request.headers.get('content-length')
    if declared is not None:
        try: length = int(declared)
        except ValueError: raise HTTPException(status_code=400, detail='Invalid Content-Length')
        if length < 0: raise HTTPException(status_code=400, detail='Invalid Content-Length')
        if length > limit: raise HTTPException(status_code=413, detail='Configuration file is too large (maximum 1 MiB).')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > limit:
            raise HTTPException(status_code=413, detail='Configuration file is too large (maximum 1 MiB).')
        raw.extend(chunk)
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail='Invalid JSON configuration file.') from error
    return document

@app.post('/api/services/import/preview')
async def preview_services_import(request: Request, _token: str = Depends(_authenticated)):
    document = await _read_service_config(request)
    return await run_in_threadpool(_safe_call, config_transfer.import_config, document, True, True)

@app.post('/api/services/import')
async def import_services(request: Request, overwrite: bool = False, _token: str = Depends(_authenticated)):
    document = await _read_service_config(request)
    return await run_in_threadpool(_safe_call, config_transfer.import_config, document, overwrite, False, request.headers.get('x-import-preview'))

@app.put("/api/services/{service_id}/settings")
def set_service_settings(service_id: str, body: ServiceSettingsBody, request: Request, _token: str = Depends(_authenticated)):
    with storage.transaction():
        security.require_same_origin(request)
        try:
            open_url = service_urls.validate_url(body.open_url)
            if 'port' in body.model_fields_set and body.port is not None and not systemd.is_managed(SERVICE_BY_ID[service_id]):
                raise ValueError('A systemd unit is required to assign a service port.')
            display_name = service_names.set_display_name(service_id, body.display_name)
            service_urls.set_url(service_id, open_url)
            if 'port' in body.model_fields_set:
                service_ports.set_port(service_id, body.port)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"id": service_id, "display_name": display_name, "open_url": open_url,
                "configured_port": service_ports.get_ports().get(service_id, SERVICE_BY_ID[service_id].get("port"))}


def _service_snapshot(service_id):
    """Raw editable record under the caller's short lock, including invalid legacy values."""
    entry = copy.deepcopy(SERVICE_BY_ID[service_id])
    return (entry,
            service_names.get_names().get(service_id),
            service_urls.get_urls().get(service_id),
            service_ports.get_ports().get(service_id),
            service_id in service_favorites.get_favorites())


def _probe_host_snapshot(candidate):
    if candidate['service_type'] != 'remote':
        return None
    host = registry.host(candidate['host_id'])
    if candidate['unit'] and not host.get('trusted'):
        raise ValueError('Confirm this host fingerprint in Hosts first.')
    return {key: host.get(key) for key in ('id', 'address', 'username', 'port', 'trusted', 'fingerprint', 'host_key')}


def _probe_is_current(candidate, host_snapshot, service_id=None, service_snapshot=None):
    try:
        unchanged = _probe_host_snapshot(candidate) == host_snapshot
        if service_id is not None:
            unchanged = unchanged and _service_snapshot(service_id) == service_snapshot
    except (KeyError, ValueError):
        unchanged = False
    if not unchanged:
        raise HTTPException(status_code=409, detail='Service or host changed during verification. Reload and try again.')


@app.put('/api/services/{service_id}/edit')
def edit_service(service_id: str, body: AddServiceBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    try:
        candidate = registry.normalize_service_fields(body.model_dump())
        with storage.LOCK:
            snapshot = _service_snapshot(service_id)
            host_snapshot = _probe_host_snapshot(candidate)
        current = snapshot[0]
        old_identity = (current.get('service_type', 'local'), current.get('host_id', 'local'),
                        current['scope'], current.get('unit', current['id']))
        new_identity = tuple(candidate[k] for k in ('service_type', 'host_id', 'scope', 'unit'))
        if service_id.startswith('svc-') and candidate['unit'] and new_identity != old_identity:
            _safe_call(systemd.inspect_unit, {**candidate, 'id': service_id})
        with storage.transaction():
            _probe_is_current(candidate, host_snapshot, service_id, snapshot)
            registry.update_service(service_id, candidate)
            service_names.set_display_name(service_id, candidate['display_name'])
            service_urls.set_url(service_id, candidate['open_url'])
            service_ports.set_port(service_id, candidate['port'])
            service_favorites.set_favorite(service_id, body.favorite)
        return {'ok': True, 'id': service_id}
    except KeyError as error:
        raise HTTPException(status_code=404, detail='Unknown service') from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@app.put("/api/services/{service_id}/display-name")
def set_service_display_name(service_id: str, body: ServiceNameBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    try:
        display_name = service_names.set_display_name(service_id, body.display_name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"id": service_id, "display_name": display_name}

@app.put("/api/services/{service_id}/favorite")
def set_service_favorite(service_id: str, body: ServiceFavoriteBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    try:
        favorite = service_favorites.set_favorite(service_id, body.favorite)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"id": service_id, "favorite": favorite}

@app.get("/api/ports")
def ports(_token: str = Depends(_authenticated)):
    return systemd.get_port_inventory()


@app.get('/api/ports/check')
def check_saved_port(kind: str, id: str, _token: str = Depends(_authenticated)):
    if kind == 'manual':
        return _safe_call(manual_ports.check_record, id)
    if kind == 'service':
        if id not in SERVICE_BY_ID:
            raise HTTPException(status_code=404, detail='Unknown service')
        result = manual_ports.check_configured(id)
        if result is None:
            raise HTTPException(status_code=404, detail='No port configured for this service')
        return result
    raise HTTPException(status_code=400, detail='Invalid port kind')


@app.delete('/api/ports/service/{service_id}')
def remove_service_port(service_id: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    try:
        service_ports.set_port(service_id, None)
    except KeyError as error:
        raise HTTPException(status_code=404, detail='Unknown service') from error
    return {'ok': True}

@app.get('/api/ports/manual')
def get_manual_ports(_token: str = Depends(_authenticated)):
    return _safe_call(manual_ports.list_checked)

@app.post('/api/ports/manual/check')
def check_manual_port(body: ManualPortBody, request: Request, exclude_id: str = '', _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return _safe_call(manual_ports.check, body.model_dump(), exclude_id or None)

def _save_manual_port(body: ManualPortBody, record_id: str | None = None) -> dict:
    try:
        return manual_ports.save(body.model_dump(), record_id, body.confirm_duplicate)
    except manual_ports.DuplicatePortError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

@app.post('/api/ports/manual')
def add_manual_port(body: ManualPortBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return _save_manual_port(body)

@app.put('/api/ports/manual/{record_id}')
def update_manual_port(record_id: str, body: ManualPortBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return _save_manual_port(body, record_id)

@app.delete('/api/ports/manual/{record_id}')
def remove_manual_port(record_id: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    _safe_call(manual_ports.delete, record_id)
    return {'ok': True}

@app.post("/api/services/{service_id}/actions/{action}")
def action(service_id: str, action: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    if service_id not in SERVICE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown service")
    return _safe_call(systemd.control_service, service_id, action)

@app.get("/api/services/{service_id}/status")
def status(service_id: str, _token: str = Depends(_authenticated)):
    try:
        return {"status": _safe_call(systemd.get_status, service_id)}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

@app.get("/api/services/{service_id}/logs")
def recent_logs(service_id: str, lines: int = 200, query: str = "", _token: str = Depends(_authenticated)):
    if service_id not in SERVICE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown service")
    return _safe_call(systemd.get_recent_log_snapshot, service_id, lines, query)

@app.get("/api/services/{service_id}/logs/stream")
def log_stream(service_id: str, request: Request, lines: int = 0, cursor: str = '', identity: str = '',
               _token: str = Depends(_authenticated)):
    if service_id not in SERVICE_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown service")
    cursor = _safe_call(systemd.validate_journal_cursor, request.headers.get('last-event-id') or cursor)
    if len(identity) > 64 or any(c not in '0123456789abcdef' for c in identity):
        raise HTTPException(status_code=400, detail='Invalid service identity')
    async def events():
        iterator = systemd.stream_logs(service_id, lines, session_valid=lambda: security.token_is_valid(_token),
                                       disconnected=request.is_disconnected, structured=True, cursor=cursor, identity=identity)
        try:
            async for event in iterator:
                if await request.is_disconnected():
                    break
                yield systemd.encode_log_event(event)
        finally:
            await iterator.aclose()
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get('/api/ssh-key')
def get_ssh_key(_token: str = Depends(_authenticated)):
    return _safe_call(ssh_hosts.public_key)

@app.post('/api/ssh-key')
def create_ssh_key(request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return _safe_call(ssh_hosts.ensure_key)

@app.get('/api/hosts')
def get_hosts(_token: str = Depends(_authenticated)):
    rows = _safe_call(registry.hosts)
    registered = registry.registered_services()
    return {'hosts': [{**ssh_hosts.safe_host(row), 'service_count': sum(s.get('host_id') == row['id'] for s in registered)} for row in rows],
            'local': {'id': 'local', 'name': 'This host', 'connection': 'Local'}}

@app.post('/api/hosts')
def add_host(body: HostBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return {'host': _safe_call(ssh_hosts.save_host, body.model_dump())}

@app.put('/api/hosts/{host_id}')
def edit_host(host_id: str, body: HostBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return {'host': _safe_call(ssh_hosts.save_host, body.model_dump(), host_id)}

@app.delete('/api/hosts/{host_id}')
def remove_host(host_id: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    _safe_call(ssh_hosts.delete_host, host_id)
    return {'ok': True}

@app.post('/api/hosts/{host_id}/scan')
def scan_host(host_id: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return _safe_call(ssh_hosts.scan_host, host_id)

@app.post('/api/hosts/{host_id}/trust')
def trust_host(host_id: str, body: TrustBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return {'host': _safe_call(ssh_hosts.trust_host, host_id, body.fingerprint)}

@app.post('/api/hosts/{host_id}/check')
def check_host(host_id: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    return {'host': _safe_call(ssh_hosts.check_host, host_id)}

@app.post('/api/services')
def register_service(body: AddServiceBody, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    candidate = _safe_call(registry.normalize_service_fields, body.model_dump())
    with storage.LOCK:
        host_snapshot = _safe_call(_probe_host_snapshot, candidate)
    if candidate['service_type'] != 'external' and candidate['unit']:
        # Slow systemctl/SSH work must never hold the JSON storage lock.
        _safe_call(systemd.inspect_unit, {**candidate, 'id': candidate['unit']})
    with storage.transaction():
        _probe_is_current(candidate, host_snapshot)
        # add_service rechecks host trust, duplicates and capacity in this transaction.
        entry = _safe_call(registry.add_service, candidate)
        if body.favorite:
            service_favorites.set_favorite(entry['id'], True)
    return {'service': entry, 'ok': True}

@app.delete('/api/services/{service_id}')
def unregister_service(service_id: str, request: Request, _token: str = Depends(_authenticated)):
    security.require_same_origin(request)
    _safe_call(registry.delete_service, service_id)
    return {'ok': True}


@app.on_event("startup")
async def require_password():
    validate_password(os.environ.get("DASHBOARD_PASSWORD", ""))
    with storage.LOCK:
        pass  # Recover interrupted JSON transaction before serving requests.
