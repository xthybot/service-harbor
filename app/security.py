"""Password sessions for the LAN dashboard, persisted across app restarts."""
import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from . import storage
from .password_policy import validate_password

SESSION_COOKIE = "host_dashboard_session"
SESSION_TTL = 7 * 24 * 60 * 60
DATA_DIR = Path(os.environ.get("DASHBOARD_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
SESSIONS_FILE = DATA_DIR / "sessions.json"
_failed_logins: dict[str, deque[float]] = defaultdict(deque)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _load_sessions() -> dict[str, float]:
    value = storage.read('sessions.json', {})
    if not isinstance(value, dict): raise ValueError('Invalid sessions file')
    now = time.time()
    return {key: expiry for key, expiry in value.items() if isinstance(key, str) and type(expiry) in (int, float) and expiry > now}


def _save_sessions(sessions):
    storage.write('sessions.json', sessions)


@storage.locked
def token_is_valid(token):
    return bool(token and _load_sessions().get(_token_hash(token), 0) > time.time())


def password_is_configured() -> bool:
    return bool(os.environ.get("DASHBOARD_PASSWORD"))

@storage.locked
def login(password: str, client_id: str) -> str | None:
    validate_password(password)
    now = time.time()
    attempts = _failed_logins[client_id]
    while attempts and now - attempts[0] > 60:
        attempts.popleft()
    if len(attempts) >= 8:
        return None
    expected = os.environ.get("DASHBOARD_PASSWORD", "")
    if expected and secrets.compare_digest(password.encode(), expected.encode()):
        _failed_logins.pop(client_id, None)
        token = secrets.token_urlsafe(32)
        sessions = _load_sessions()
        sessions[_token_hash(token)] = now + SESSION_TTL
        _save_sessions(sessions)
        return token
    attempts.append(now)
    return None

@storage.locked
def logout(token: str | None) -> None:
    if token:
        sessions = _load_sessions()
        sessions.pop(_token_hash(token), None)
        _save_sessions(sessions)

def require_session(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not token_is_valid(token):
        raise HTTPException(status_code=401, detail="Login required")
    return token

def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="Same-origin request required")
    parsed = urlsplit(origin)
    if parsed.scheme != request.url.scheme or parsed.netloc.lower() != request.headers.get("host", "").lower():
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
