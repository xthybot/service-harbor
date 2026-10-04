"""One reentrant thread/process lock and recoverable transactions for private JSON."""
import base64
import copy
from contextlib import contextmanager
import fcntl
from functools import wraps
import json
import os
from pathlib import Path
import tempfile
import threading

DATA_DIR = Path(os.environ.get('DASHBOARD_DATA_DIR', Path(__file__).resolve().parent.parent / 'data'))
JOURNAL = '.json-transaction.json'
_local = threading.local()


def _path(name):
    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.json') or name == JOURNAL:
        raise ValueError('Invalid JSON record name')
    return DATA_DIR / name


def _sync_directory():
    fd = os.open(DATA_DIR, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _replace_bytes(path, content):
    fd, temporary = tempfile.mkstemp(prefix='.json-write-', dir=DATA_DIR)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory()
    finally:
        Path(temporary).unlink(missing_ok=True)


def _recover():
    journal = DATA_DIR / JOURNAL
    if not journal.exists(): return
    before = json.loads(journal.read_text())
    if not isinstance(before, dict): raise ValueError('Invalid JSON recovery journal')
    for name, encoded in before.items():
        path = _path(name)
        if encoded is None: path.unlink(missing_ok=True)
        else: _replace_bytes(path, base64.b64decode(encoded, validate=True))
    _sync_directory()
    journal.unlink()
    _sync_directory()


class DataLock:
    def __init__(self): self.thread_lock = threading.RLock()

    def __enter__(self):
        self.thread_lock.acquire()
        depth = getattr(_local, 'depth', 0)
        try:
            if depth == 0:
                DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(DATA_DIR / '.json.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                _local.fd = fd
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    _recover()
                except BaseException:
                    os.close(fd)
                    raise
            _local.depth = depth + 1
            return self
        except BaseException:
            self.thread_lock.release()
            raise

    def __exit__(self, *args):
        _local.depth -= 1
        if _local.depth == 0:
            os.close(_local.fd)
        self.thread_lock.release()


LOCK = DataLock()


def locked(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        with LOCK: return function(*args, **kwargs)
    return wrapper


@locked
def read(name, default):
    path = _path(name)
    pending = getattr(_local, 'pending', None)
    if pending is not None and name in pending: return copy.deepcopy(pending[name])
    try: return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError: return copy.deepcopy(default)


@locked
def write(name, value):
    path = _path(name)
    pending = getattr(_local, 'pending', None)
    if pending is not None:
        _local.pending[name] = copy.deepcopy(value)
    else:
        _replace_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


@contextmanager
def transaction():
    with LOCK:
        if getattr(_local, 'pending', None) is not None:
            raise RuntimeError('Nested JSON transactions are not supported')
        _local.pending = {}
        try:
            yield
            pending = _local.pending
            encoded = {name: (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode() for name, value in pending.items()}
            if not encoded: return
            before = {name: base64.b64encode(_path(name).read_bytes()).decode() if _path(name).exists() else None for name in encoded}
            _replace_bytes(DATA_DIR / JOURNAL, json.dumps(before).encode())
            try:
                for name, content in encoded.items(): _replace_bytes(_path(name), content)
            except BaseException:
                _recover()  # If rollback fails, journal stays and every subsequent access retries.
                raise
            (DATA_DIR / JOURNAL).unlink()
            _sync_directory()
        finally:
            del _local.pending
