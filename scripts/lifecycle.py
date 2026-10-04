#!/usr/bin/env python3
"""Interactive, non-root installation lifecycle. No shell eval or sudoers grants."""
import argparse
import getpass
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import shlex
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

UNIT = 'host-service-dashboard.service'
APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))
from app.password_policy import validate_password
from app import storage
HOME = Path.home().resolve()
CONFIG_BASE = Path(os.environ.get('XDG_CONFIG_HOME', HOME / '.config'))
CONFIG = CONFIG_BASE / 'host-service-dashboard'
ENV = CONFIG / 'dashboard.env'
RECEIPT = CONFIG / 'install.json'
UNITS = {'user': HOME / '.config/systemd/user' / UNIT,
         'system': Path('/etc/systemd/system') / UNIT}
ACCOUNT = pwd.getpwuid(os.getuid()).pw_name
UID = os.getuid()
MARKER = f'# Managed by Host Service Dashboard; owner={ACCOUNT}; project={APP}'
SUDO_READY = False


def step(message):
    print(f'\n==> {message}', flush=True)


def fail(message):
    raise RuntimeError(message)


def run(args, *, capture=False, check=True):
    return subprocess.run([str(x) for x in args], check=check, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def sudo(*args):
    global SUDO_READY
    if not SUDO_READY:
        if not shutil.which('sudo'):
            fail('sudo is required for this operation; ask an administrator to configure it first.')
        step('Request administrator authentication for systemd / boot setup only')
        run(['sudo', '-v'])
        SUDO_READY = True
    return run(['sudo', '--', *args])


def ctl(mode, *args, capture=False, check=True):
    cmd = ['systemctl', *(['--user'] if mode == 'user' else []), *args]
    if mode == 'system' and not capture:
        return sudo(*cmd)
    return run(cmd, capture=capture, check=check)


def safe_path(path):
    if not path.is_absolute() or '..' in path.parts or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        fail(f'Expected a safe absolute path: {path}')
    for part in (path, *path.parents):
        if part.is_symlink():
            fail(f'Symlink not supported for installer-managed paths: {part}')


def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.dashboard-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def python_packages_help(reason, repair=None):
    message = (reason + '\nOn Ubuntu, install the required packages, then rerun this script:\n'
               '  sudo apt update\n'
               '  sudo apt install python3 python3-pip python3-venv\n'
               'No system packages were installed automatically.')
    if repair:
        message += ('\nFor an existing virtual environment without pip, also run:\n  '
                    + shlex.quote(str(repair)) + ' -m ensurepip --upgrade\n'
                    'For a uv-created environment, you can instead use:\n  uv pip install --python '
                    + shlex.quote(str(repair)) + ' pip')
    fail(message)


def environment():
    if not ENV.exists():
        return {}
    result = {}
    for line in ENV.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith(('#', ';')):
            continue
        name, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name):
            fail('Unsupported environment-file syntax; simplify dashboard.env to one KEY=value per line first.')
        # The installer writes single-line, double-quoted systemd values.
        if value.startswith('"'):
            if not value.endswith('"'):
                fail('Multiline environment values are not supported by the installer.')
            raw = value[1:-1]
            value = re.sub(r'\\([\\"$`])', r'\1', raw)
        elif value.startswith("'"):
            if not value.endswith("'"):
                fail('Multiline environment values are not supported by the installer.')
            value = value[1:-1]
        else:
            value = value.strip()
            if '\\' in value:
                fail('Quote backslash-containing environment values before using the installer.')
        result[name] = value
    return result


def env_quote(value):
    if any(c in value for c in '\n\r\x00'):
        fail('Environment values must be single-line text.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + '"'


def unit_quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def installed_units():
    found = {}
    for mode, path in UNITS.items():
        safe_path(path)
        if not path.exists():
            continue
        text = path.read_text()
        legacy = mode == 'user' and APP == HOME / 'host-service-dashboard' and 'WorkingDirectory=%h/host-service-dashboard\n' in text
        if MARKER not in text and not legacy:
            fail(f'Refusing to overwrite or remove a unit not owned by this installation: {path}')
        found[mode] = text
    if RECEIPT.exists():
        receipt = json.loads(RECEIPT.read_text())
        if not isinstance(receipt, dict): fail('Invalid install.json; restore the installation record first.')
        if receipt.get('project') != str(APP) or receipt.get('user') != ACCOUNT:
            fail('This account already has a Dashboard installation in another project directory.')
    return found


DATA_FILES = ('bookmarks.json', 'sessions.json', 'hosts.json', 'registered-services.json',
              'service-metadata.json', 'service-names.json', 'service-open-urls.json',
              'service-ports.json', 'service-favorites.json', 'manual-ports.json', 'local-catalog.json')
OWNER_FILE = '.dashboard-owner.json'


def receipt_data():
    if not RECEIPT.exists(): return {}
    safe_file(RECEIPT)
    value = json.loads(RECEIPT.read_text())
    if not isinstance(value, dict) or value.get('project') != str(APP) or value.get('user') != ACCOUNT:
        fail('Installation receipt does not belong to this account and project.')
    if not isinstance(value.get('data'), str) or not value['data']:
        fail('Installation receipt has no data location; restore it before continuing.')
    return value


def data_path(settings):
    receipt = receipt_data()
    recorded = settings.get('DASHBOARD_DATA_DIR')
    if ENV.exists() and not recorded:
        fail('dashboard.env has no DASHBOARD_DATA_DIR; explicitly restore its original location before continuing.')
    if recorded and receipt and recorded != receipt['data']:
        fail('dashboard.env and install.json disagree about DATA_DIR; reconcile the original location first.')
    path = Path(recorded or receipt.get('data', str(APP / 'data')))
    safe_path(path)
    # Only the dedicated data subtree is valid inside the source checkout.
    if path == APP or (APP in path.parents and not (path == APP / 'data' or APP / 'data' in path.parents)):
        fail('DATA_DIR cannot contain project source, Git, configuration or virtual environment files.')
    protected = (HOME, CONFIG_BASE, CONFIG, APP / '.venv', APP / '.git', Path('/etc'), Path('/usr'),
                 Path('/bin'), Path('/sbin'), Path('/lib'), Path('/lib64'), Path('/boot'), Path('/dev'),
                 Path('/proc'), Path('/sys'), Path('/run'), Path('/root'))
    if path in (Path('/var'), Path('/tmp'), Path('/opt'), Path('/srv'), Path('/mnt'), Path('/media')):
        fail('DATA_DIR must be a dedicated subdirectory, not a shared system root.')
    if path in APP.parents or any(path == root or path in root.parents for root in protected):
        fail('DATA_DIR cannot be a home, configuration or system directory.')
    if any(root in path.parents for root in protected[1:]):
        fail('DATA_DIR cannot be inside configuration or protected system directories.')
    return path


def safe_file(path):
    safe_path(path)
    if path.exists() and (not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_uid != UID):
        fail(f'Expected an ordinary user-owned file, not a directory/device: {path}')


def owner_value(data):
    return {'version': 1, 'project': str(APP), 'user': ACCOUNT, 'uid': UID, 'data': str(data)}


def require_owner(data, *, create=False):
    safe_path(data)
    if data.exists() and (not data.is_dir() or data.stat().st_uid != UID):
        fail('DATA_DIR must be a directory owned by the current user.')
    marker = data / OWNER_FILE
    safe_file(marker)
    if marker.exists():
        if json.loads(marker.read_text()) != owner_value(data):
            fail('DATA_DIR ownership marker does not match this installation; migrate explicitly.')
        return
    if create and (not data.exists() or not any(data.iterdir())):
        data.mkdir(parents=True, mode=0o700, exist_ok=True)
        atomic(marker, json.dumps(owner_value(data)) + '\n')
        marker.chmod(0o600)
        return
    fail('DATA_DIR has no ownership marker. Review it, then run python3 scripts/lifecycle.py adopt-data for this legacy installation.')


def preflight_data(data):
    """Validate types before recovery; never follow a JSON or SSH symlink."""
    safe_path(data)
    for name in (*DATA_FILES, storage.JOURNAL, '.json.lock', OWNER_FILE): safe_file(data / name)
    ssh = data / 'ssh'
    safe_path(ssh)
    if ssh.exists() and not ssh.is_dir(): fail('Dashboard ssh path must be a directory.')
    if data.exists():
        for path in data.iterdir():
            if path.name.endswith('.json'): safe_file(path)
    storage.DATA_DIR = data
    with storage.LOCK:
        for name in DATA_FILES:
            if (data / name).exists(): storage.read(name, None)
        ports = storage.read('service-ports.json', {})
        if not isinstance(ports, dict): fail('service-ports.json must contain an object.')


def revoke_sessions(data):
    preflight_data(data)  # Acquiring the common lock finishes recovery FIRST.
    with storage.transaction(): storage.write('sessions.json', {})
    print('All sessions revoked after successful storage recovery.')


def require_offline():
    for scope in UNITS:
        result = ctl(scope, 'show', UNIT, '-p', 'ActiveState', '--value', capture=True, check=False)
        if result.returncode or result.stdout.strip() not in ('inactive', 'failed'):
            fail(f'Cannot confirm {scope} Dashboard is stopped. Stop it and verify the user manager before this offline operation.')


def adopt_data():
    installed_units()  # Verify any existing units and receipt first.
    settings = environment()
    if not ENV.exists() and not RECEIPT.exists():
        fail('Legacy adoption requires an existing environment or installation receipt with an explicit DATA_DIR.')
    data = data_path(settings)
    if (data / OWNER_FILE).exists():
        require_owner(data)
        print('Ownership already recorded.'); return
    require_offline()
    preflight_data(data)
    print(f'Legacy DATA_DIR: {data}\nOnly known Dashboard files will be removable; unknown files and SSH content remain protected.')
    if input('Confirm this data belongs to this installation by typing ADOPT: ') != 'ADOPT': fail('Cancelled.')
    atomic(data / OWNER_FILE, json.dumps(owner_value(data)) + '\n')
    (data / OWNER_FILE).chmod(0o600)
    print('Ownership recorded. Run setup/reset/uninstall again.')


def check_unit_paths(mode):
    # The shell XDG_CONFIG_HOME is not necessarily the already running manager's value.
    result = ctl('user', 'show', '-p', 'UnitPath', '--value', capture=True, check=False)
    try: paths = shlex.split(result.stdout)
    except ValueError: paths = []
    if result.returncode or str(UNITS['user'].parent) not in paths:
        fail('Cannot confirm ~/.config/systemd/user is in the running user manager UnitPath. '
             'Reconcile the manager XDG_CONFIG_HOME / UnitPath before installation; no unit will be written there.')


def prompt(label, default):
    value = input(f'{label} [{default}]: ').strip()
    return value or str(default)


def get_settings(old, installed, reset):
    step('Configure installation (password input is hidden)')
    while True:
        password = getpass.getpass('Dashboard password' + (' (Enter keeps current)' if old.get('DASHBOARD_PASSWORD') and not reset else '') + ': ')
        if not password and old.get('DASHBOARD_PASSWORD') and not reset:
            password = old['DASHBOARD_PASSWORD']
            try:
                validate_password(password)
                break
            except ValueError as error:
                print(error); continue
        try:
            validate_password(password)
        except ValueError as error:
            print(error); continue
        if password == getpass.getpass('Confirm password: '):
            break
        print('Passwords did not match. Please try again.')
    while True:
        host = prompt('Listen IP address', old.get('DASHBOARD_BIND', '0.0.0.0'))
        try:
            address = ipaddress.ip_address(host)
            if address.is_multicast or '%' in host:
                raise ValueError()
            host = str(address); break
        except ValueError:
            print('Enter an IPv4 or IPv6 address, e.g. 0.0.0.0, 192.168.1.10 or :: (not a CIDR subnet).')
    while True:
        port = prompt('TCP port (1024-65535)', old.get('DASHBOARD_PORT', '8765'))
        if port.isdecimal() and 1024 <= int(port) <= 65535:
            port = str(int(port)); break
        print('Choose an unprivileged port between 1024 and 65535.')
    default_mode = next(iter(installed), 'user')
    while True:
        mode = prompt('systemd location: user (~/.config) or system (/etc)', default_mode).lower()
        if mode in UNITS: break
        print('Enter user or system.')
    values = {**old, 'DASHBOARD_PASSWORD': password, 'DASHBOARD_BIND': host,
              'DASHBOARD_PORT': port, 'DASHBOARD_INSTALL_MODE': mode,
              'DASHBOARD_DATA_DIR': str(data_path(old))}
    values.setdefault('DASHBOARD_COOKIE_SECURE', '0')
    print(f'\nRun as: {ACCOUNT} (not root)\nUnit: {UNITS[mode]}\nListen: {host}:{port}\nData: {values["DASHBOARD_DATA_DIR"]}')
    print('No sudoers, firewall rules or account group memberships will be created.')
    if input('Install and start with these settings? [y/N]: ').lower() != 'y':
        fail('Cancelled; installation settings were not changed.')
    return values, mode


def ensure_user_manager():
    step('Ensure user manager starts at boot, even before login')
    result = run(['loginctl', 'show-user', ACCOUNT, '-p', 'Linger', '--value'], capture=True, check=False)
    if result.stdout.strip() != 'yes':
        sudo('loginctl', 'enable-linger', ACCOUNT)
    else:
        print('Linger is already enabled.')
    # System-mode Dashboard also needs this bus to query local user services.
    os.environ['XDG_RUNTIME_DIR'] = f'/run/user/{UID}'
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{UID}/bus'
    for _ in range(20):
        if Path(f'/run/user/{UID}/bus').exists():
            return
        time.sleep(.5)
    fail('User bus did not become available. Check user@UID.service, then rerun setup.')


def make_unit(mode, data):
    identity = ''
    manager = ''
    if mode == 'system':
        manager = f'Requires=user@{UID}.service\nAfter=user@{UID}.service'
        identity = '\n'.join([f'User={ACCOUNT}', f'Group={pwd.getpwuid(UID).pw_gid}',
                              'SupplementaryGroups=systemd-journal',
                              f'Environment={unit_quote("HOME=" + str(HOME))}',
                              f'Environment="XDG_RUNTIME_DIR=/run/user/{UID}"',
                              f'Environment="DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{UID}/bus"'])
    tokens = {'MARKER': MARKER, 'USER_MANAGER': manager, 'IDENTITY': identity,
              'APP': unit_quote(APP), 'ENV': unit_quote(ENV), 'DATA': unit_quote(data),
              'PYTHON': unit_quote(str(APP / '.venv/bin/python').replace('$', '$$')),
              'TARGET': 'multi-user.target' if mode == 'system' else 'default.target'}
    template = (APP / 'systemd' / UNIT).read_text()
    return re.sub(r'@(MARKER|USER_MANAGER|IDENTITY|APP|ENV|DATA|PYTHON|TARGET)@',
                  lambda match: tokens[match[1]], template)


def put_unit(mode, text):
    path = UNITS[mode]
    if mode == 'user':
        atomic(path, text); path.chmod(0o644)
    else:
        with tempfile.TemporaryDirectory(prefix='dashboard-unit-') as directory:
            temporary = Path(directory) / UNIT
            temporary.write_text(text)
            sudo('install', '-o', 'root', '-g', 'root', '-m', '0644', str(temporary), str(path))


def remove_unit(mode):
    if mode == 'user':
        UNITS[mode].unlink(missing_ok=True)
    else:
        sudo('rm', '-f', '--', str(UNITS[mode]))


def port_available(host, port):
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, int(port)))
        except OSError as error:
            fail(f'Cannot bind {host}:{port}: {error}. Choose an available local IP and port.')


def verify(mode, host, port):
    step('Confirm enabled unit, non-root process and HTTP readiness')
    target = '127.0.0.1' if host == '0.0.0.0' else '::1' if host == '::' else host
    url = f'http://{"[" + target + "]" if ":" in target else target}:{port}/api/session'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    consecutive = 0
    previous_pid = None
    for attempt in range(30):
        if attempt % 5 == 0: print(f'Waiting for HTTP readiness ({attempt + 1}/30)…', flush=True)
        result = ctl(mode, 'show', UNIT, '-p', 'MainPID', '--value', capture=True, check=False)
        try:
            pid = int(result.stdout.strip())
            status = Path(f'/proc/{pid}/status').read_text()
            process_uid = int(re.search(r'^Uid:\s+(\d+)', status, re.M)[1])
            with opener.open(url, timeout=2) as response:
                payload = json.load(response)
            if pid > 0 and process_uid == UID and payload.get('password_configured'):
                consecutive = consecutive + 1 if pid == previous_pid else 1
                previous_pid = pid
                if consecutive >= 3:
                    ctl(mode, 'is-enabled', UNIT, capture=True)
                    ctl(mode, 'is-active', UNIT, capture=True)
                    print('Service is active, enabled and responding to HTTP as the selected user.')
                    return
            else:
                consecutive = 0
        except (OSError, ValueError, TypeError, KeyError):
            consecutive = 0
        time.sleep(1)
    fail('Dashboard did not become ready. Inspect its journal; previous installation will be restored.')


def install(reset=False, backend=None):
    for path in (APP, CONFIG_BASE, CONFIG, ENV, RECEIPT, APP / '.venv'): safe_path(path)
    installed = installed_units()
    old = environment()
    if backend is None:
        receipt = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {}
        backend = receipt.get('backend', 'venv')
    if backend not in ('venv', 'uv'): fail('Unknown installation backend in install.json.')
    step(f'Python environment backend: {backend}')
    if RECEIPT.exists() and not ENV.exists():
        fail('The installation environment file is missing. Restore dashboard.env before setup/reset to preserve the data location.')
    values, mode = get_settings(old, installed, reset)
    data = data_path(values)
    storage.DATA_DIR = data
    step('Check prerequisites; no apt packages are installed automatically')
    for executable in ('systemctl', 'systemd-analyze', 'loginctl', 'journalctl', 'hostname', 'ssh', 'ssh-keygen', 'ssh-keyscan'):
        if not shutil.which(executable):
            fail(f'Missing {executable}. Install the corresponding system package first (SSH tools: openssh-client).')
    for path in (data / 'sessions.json', data / 'service-ports.json'):
        safe_path(path)
    uv = shutil.which('uv') if backend == 'uv' else None
    if backend == 'uv' and not uv:
        fail('uv is not installed or is not on PATH. Choose either option:\n'
             '  1. Use the standard Python venv/pip installer:\n'
             '     bash scripts/setup.sh\n'
             '  2. Install uv as your ordinary user (without sudo):\n'
             '     curl -LsSf https://astral.sh/uv/install.sh | sh\n'
             '     Open a new terminal, then run:\n'
             '     uv --version\n'
             '     bash scripts/setup-uv.sh\n'
             'No packages were installed automatically.')
    if backend == 'venv':
        import importlib.util
        if not importlib.util.find_spec('venv') or not importlib.util.find_spec('ensurepip'):
            python_packages_help('Python venv/ensurepip is missing for the python3 running this script.')
        existing_python = APP / '.venv/bin/python'
        if existing_python.exists() and run([existing_python, '-m', 'pip', '--version'], capture=True, check=False).returncode:
            python_packages_help('The existing .venv does not have usable pip.', existing_python)
    require_owner(data, create=True)
    preflight_data(data)
    ensure_user_manager()
    check_unit_paths(mode)
    if mode == 'system':
        import grp
        try: grp.getgrnam('systemd-journal')
        except KeyError: fail('The systemd-journal group is missing; restore the Ubuntu systemd journal setup first.')
    # Detect units loaded from another location before changing anything.
    for scope in UNITS:
        loaded = ctl(scope, 'show', UNIT, '-p', 'FragmentPath', '--value', capture=True, check=False).stdout.strip()
        if loaded and loaded != str(UNITS[scope]):
            fail(f'A same-name unit is loaded from another location: {loaded}')
    step('Prepare private directories and Python virtual environment as the current user')
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700); CONFIG.chmod(0o700)
    data.mkdir(parents=True, exist_ok=True, mode=0o700); data.chmod(0o700)
    venv = APP / '.venv'
    if not (venv / 'bin/python').exists():
        if venv.exists() and any(venv.iterdir()):
            fail('Existing .venv has no usable Python. Back it up and repair it before continuing; it will not be overwritten.')
        if backend == 'uv':
            step('Create .venv using uv (no pip seeding or Python download)')
            run([uv, 'venv', '--no-python-downloads', '--python', sys.executable, str(venv)])
        else:
            try:
                run([sys.executable, '-m', 'venv', str(venv)])
            except subprocess.CalledProcessError:
                python_packages_help('Virtual environment creation failed. Check the error above and Python package availability.')
    else:
        print('Reusing existing .venv; it will not be recreated.')
    step(f'Install application dependencies using {"uv pip" if backend == "uv" else "pip"}')
    if backend == 'uv':
        run([uv, 'pip', 'install', '--no-python-downloads', '--python', venv / 'bin/python', '-r', APP / 'requirements.txt'])
    else:
        if run([venv / 'bin/python', '-m', 'pip', '--version'], capture=True, check=False).returncode:
            python_packages_help('The virtual environment does not have usable pip.', venv / 'bin/python')
        run([venv / 'bin/python', '-m', 'pip', 'install', '-r', APP / 'requirements.txt'])
    step('Validate generated systemd unit before stopping the existing service')
    with tempfile.TemporaryDirectory(prefix='dashboard-unit-check-') as temporary:
        candidate = Path(temporary) / UNIT
        candidate.write_text(make_unit(mode, data))
        run(['systemd-analyze', *(['--user'] if mode == 'user' else []), 'verify', str(candidate)])
    snapshots = {path: path.read_bytes() if path.exists() else None for path in (ENV, RECEIPT)}
    previous = {scope: {'active': ctl(scope, 'is-active', UNIT, capture=True, check=False).returncode == 0,
                        'enabled': ctl(scope, 'is-enabled', UNIT, capture=True, check=False).returncode == 0} for scope in installed}
    preflight_data(data)  # Recovery and format checks before stopping any unit.
    touched = set()
    try:
        step('Stop existing Dashboard units before rebuilding (other services are untouched)')
        for scope in installed:
            ctl(scope, 'stop', UNIT)
        with storage.LOCK:
            for path in (data / 'sessions.json', data / 'service-ports.json'):
                snapshots[path] = path.read_bytes() if path.exists() else None
        port_available(values['DASHBOARD_BIND'], values['DASHBOARD_PORT'])
        step('Write private settings and rebuild systemd unit')
        atomic(ENV, ''.join(f'{name}={env_quote(value)}\n' for name, value in values.items()))
        with storage.transaction():
            ports = storage.read('service-ports.json', {})
            if not isinstance(ports, dict): fail('Invalid service-ports.json; restore valid JSON before installation.')
            if UNIT in ports:
                ports[UNIT] = int(values['DASHBOARD_PORT'])
                storage.write('service-ports.json', ports)
            if reset or old.get('DASHBOARD_PASSWORD') != values['DASHBOARD_PASSWORD']:
                storage.write('sessions.json', {})
                print('Old login sessions revoked; service/host settings and SSH keys retained.')
        touched.add(mode)
        put_unit(mode, make_unit(mode, data))
        ctl(mode, 'daemon-reload')
        step(f'Enable and start {mode} service')
        ctl(mode, 'enable', UNIT)
        ctl(mode, 'restart', UNIT)
        verify(mode, values['DASHBOARD_BIND'], values['DASHBOARD_PORT'])
        for scope in installed:
            if scope != mode:
                step(f'Remove previous {scope} unit after successful migration')
                ctl(scope, 'disable', UNIT); remove_unit(scope); ctl(scope, 'daemon-reload')
        atomic(RECEIPT, json.dumps({'version': 1, 'project': str(APP), 'user': ACCOUNT,
                                   'mode': mode, 'data': str(data), 'backend': backend}, indent=2) + '\n')
    except (Exception, KeyboardInterrupt):
        rollback_install(installed, previous, touched, snapshots, data)
        raise
    step('Installation complete')
    host, port = values['DASHBOARD_BIND'], values['DASHBOARD_PORT']
    if host in ('0.0.0.0', '::'):
        addresses = run(['hostname', '-I'], capture=True, check=False).stdout.split()
        for address in addresses:
            if (':' in address) == (host == '::'):
                print(f'Open: http://{"[" + address + "]" if ":" in address else address}:{port}/')
        print(f'Listening on {host}:{port}; use a reachable LAN address above.')
    else:
        print(f'Open: http://{"[" + host + "]" if ":" in host else host}:{port}/')
    print(f'Password saved privately in {ENV}; not printed.')
    print('Firewall rules and existing sudoers were not changed. System unit controls require separate explicit authorization.')


def rollback_install(installed, previous, touched, snapshots, data):
    step('Installation incomplete; independent rollback steps (not a power-loss recovery mechanism)')
    results = []
    def attempt(label, action):
        try:
            action(); results.append((label, True)); print(f'Rollback OK: {label}'); return True
        except (Exception, KeyboardInterrupt) as error:
            results.append((label, False)); print(f'Rollback FAILED: {label}: {type(error).__name__}', file=sys.stderr); return False
    safe_to_start = True
    for scope in touched:
        safe_to_start &= attempt(f'stop new {scope} unit', lambda s=scope: ctl(s, 'disable', '--now', UNIT))
        if scope not in installed:
            safe_to_start &= attempt(f'remove new {scope} unit', lambda s=scope: remove_unit(s))
    def restore_file(path, content):
        if content is None: path.unlink(missing_ok=True)
        else: atomic(path, content.decode())
    for path in (ENV, RECEIPT):
        if path in snapshots:
            safe_to_start &= attempt(f'restore {path.name}', lambda p=path: restore_file(p, snapshots[p]))
    def restore_data():
        preflight_data(data)
        with storage.transaction():
            for name in ('service-ports.json',):
                path = data / name
                if path in snapshots:
                    value = snapshots[path]
                    storage.write(name, json.loads(value) if value is not None else {})
            # Fail closed: never restore sessions revoked during an attempted reset.
            storage.write('sessions.json', {})
        preflight_data(data)
    safe_to_start &= attempt('recover data and revoke sessions', restore_data)
    for scope, text in installed.items():
        safe_to_start &= attempt(f'restore {scope} unit', lambda s=scope, t=text: put_unit(s, t))
    for scope in set(installed) | touched:
        safe_to_start &= attempt(f'reload {scope} manager', lambda s=scope: ctl(s, 'daemon-reload'))
    for scope, status in previous.items():
        safe_to_start &= attempt(f'restore {scope} enablement', lambda s=scope, t=status: ctl(s, 'enable' if t['enabled'] else 'disable', UNIT))
    if safe_to_start:
        for scope, status in previous.items():
            if status['active']: attempt(f'start previous {scope} service', lambda s=scope: ctl(s, 'start', UNIT))
    else:
        print('Previous services NOT restarted: recovery/settings/unit consistency was not established. Review rollback failures before starting.', file=sys.stderr)
    return results


def cleanup_data(data):
    require_owner(data)
    preflight_data(data)  # Never delete a recovery journal to bypass recovery.
    targets = [data / name for name in DATA_FILES]
    # Only exact Dashboard identity files and per-host pin files, never generic ssh/.
    ssh = data / 'ssh'
    saved_hosts = storage.read('hosts.json', [])
    if not isinstance(saved_hosts, list): fail('hosts.json must contain a list before cleaning SSH pins.')
    host_ids = {host.get('id') for host in saved_hosts if isinstance(host, dict)}
    if ssh.exists():
        targets.extend(path for path in ssh.iterdir() if path.name in ('dashboard_ed25519', 'dashboard_ed25519.pub')
                       or (re.fullmatch(r'[0-9a-f]{32}\.known_hosts', path.name) and path.stem in host_ids))
    targets.extend(path for path in data.iterdir() if re.fullmatch(r'\.json-write-[a-z0-9_]{8}', path.name))
    for path in targets: safe_file(path)
    for path in targets:
        if not path.exists():
            print(f'Already absent: {path.name}'); continue
        step(f'Delete Dashboard data file {path.name}')
        try: path.unlink()
        except OSError:
            print(f'Not cleared: {path}; ownership and installation records retained for retry.', file=sys.stderr); raise
    if ssh.exists():
        if any(ssh.iterdir()): print('Retained unknown SSH files; ssh directory was not removed.')
        else: ssh.rmdir()
    for name in ('.json.lock',):
        path = data / name; safe_file(path); path.unlink(missing_ok=True)
    remaining = [p.name for p in data.iterdir() if p.name != OWNER_FILE]
    if remaining: print('Retained unrecognized data entries: ' + ', '.join(sorted(remaining)))
    # Marker remains until *all* uninstall stages succeed, so retries stay authorized.


def uninstall():
    installed = installed_units()
    settings = environment()
    data = data_path(settings)
    final_retry = receipt_data().get('uninstall_stage') == 'data-cleared'
    if not final_retry:
        require_owner(data)
        preflight_data(data)
    os.environ['XDG_RUNTIME_DIR'] = f'/run/user/{UID}'
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{UID}/bus'
    for scope in UNITS:
        loaded = ctl(scope, 'show', UNIT, '-p', 'FragmentPath', '--value', capture=True, check=False).stdout.strip()
        if loaded and (scope not in installed or loaded != str(UNITS[scope])):
            fail(f'A Dashboard unit is loaded from an unowned location: {loaded}. Reconcile it first.')
    for path in (APP / '.venv', ENV, RECEIPT, CONFIG / 'host-service-dashboard.sudoers'): safe_path(path)
    for path in (ENV, RECEIPT, CONFIG / 'host-service-dashboard.sudoers'): safe_file(path)
    step(f'Uninstall: owned Dashboard records in {data}, private settings, owned units and .venv')
    print('Unknown files, source code, other services, sudoers and linger are retained.')
    print('Remove the Dashboard public key from remote authorized_keys separately.')
    if input('Type REMOVE to confirm permanent deletion: ') != 'REMOVE': fail('Cancelled; nothing removed.')
    # Durable original target before any deletion, including legacy deployments.
    receipt = receipt_data() or {'version': 1, 'project': str(APP), 'user': ACCOUNT, 'data': str(data)}
    receipt['uninstall_pending'] = True
    atomic(RECEIPT, json.dumps(receipt) + '\n')
    for scope in installed:
        step(f'Stop, disable and remove {scope} Dashboard service')
        ctl(scope, 'disable', '--now', UNIT)
        remove_unit(scope); ctl(scope, 'daemon-reload')
    if not final_retry: cleanup_data(data)
    venv = APP / '.venv'
    if venv.exists():
        step('Delete virtual environment')
        if not venv.is_dir(): fail('.venv is not a directory; retained for manual inspection.')
        shutil.rmtree(venv)  # Python rmtree does not follow internal directory symlinks.
    for path in (CONFIG / 'host-service-dashboard.sudoers', ENV):
        step(f'Delete {path.name}')
        path.unlink(missing_ok=True)
    # Persist final-stage progress before removing the last ownership marker.
    receipt['uninstall_stage'] = 'data-cleared'
    atomic(RECEIPT, json.dumps(receipt) + '\n')
    safe_file(data / OWNER_FILE)
    (data / OWNER_FILE).unlink(missing_ok=True)
    if data.exists() and not any(data.iterdir()): data.rmdir()
    RECEIPT.unlink(missing_ok=True)
    if CONFIG.exists() and not any(CONFIG.iterdir()): CONFIG.rmdir()
    step('Uninstall complete; unknown files (if listed) retained. Source code remains.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'reset', 'uninstall', 'adopt-data', 'revoke-sessions'])
    parser.add_argument('--backend', choices=['venv', 'uv'], help='Environment tool; defaults to the recorded backend, or venv')
    args = parser.parse_args()
    action = args.action
    if UID == 0:
        fail('Run this script as the intended ordinary user, without sudo. It requests sudo only for required system commands.')
    if not sys.stdin.isatty(): fail('Run interactively in a terminal.')
    os.umask(0o077)
    for path in (APP, CONFIG_BASE, CONFIG, ENV, RECEIPT, APP / 'data', APP / '.venv'):
        safe_path(path)
    # Lock the project directory itself; no lock file is left behind on removal.
    descriptor = os.open(APP, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try: fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: fail('Another lifecycle operation is running for this project.')
        if action == 'uninstall': uninstall()
        elif action == 'adopt-data': adopt_data()
        elif action == 'revoke-sessions':
            installed_units()
            require_offline()
            revoke_sessions(data_path(environment()))
        else: install(reset=action == 'reset', backend=args.backend)
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, KeyboardInterrupt, EOFError) as error:
        print(f'\nERROR: {error or "Cancelled"}', file=sys.stderr)
        sys.exit(1)
