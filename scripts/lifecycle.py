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
    if not path.is_absolute() or any(c in str(path) for c in '\n\r\x00'):
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


def data_path(settings):
    path = Path(settings.get('DASHBOARD_DATA_DIR', str(APP / 'data')))
    safe_path(path)
    protected = (APP, HOME, CONFIG, APP / '.venv', APP / '.git', APP / 'scripts')
    if any(path == root or path in root.parents or root in path.parents for root in protected[2:]) or path == APP or path in APP.parents or path == HOME or path in HOME.parents:
        fail('DASHBOARD_DATA_DIR must be a dedicated data directory, not a project/home/system root, config, venv or source directory.')
    return path


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
              'APP': str(APP).replace('%', '%%'), 'ENV': str(ENV).replace('%', '%%'), 'DATA': unit_quote(data),
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
    ensure_user_manager()
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
        step('Installation incomplete; restoring previous unit and settings')
        for scope in touched:
            try:
                ctl(scope, 'disable', '--now', UNIT)
                if scope not in installed: remove_unit(scope)
            except Exception:
                print(f'Could not stop/remove new {scope} unit; inspect it manually.', file=sys.stderr)
        with storage.LOCK:
            for path, content in snapshots.items():
                if content is None: path.unlink(missing_ok=True)
                else: atomic(path, content.decode())
        for scope, text in installed.items():
            put_unit(scope, text)
        for scope in set(installed) | touched:
            ctl(scope, 'daemon-reload')
        for scope, status in previous.items():
            ctl(scope, 'enable' if status['enabled'] else 'disable', UNIT)
            if status['active']: ctl(scope, 'start', UNIT)
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


def uninstall():
    installed = installed_units()
    settings = environment()
    if not ENV.exists() and RECEIPT.exists():
        settings['DASHBOARD_DATA_DIR'] = json.loads(RECEIPT.read_text())['data']
    os.environ['XDG_RUNTIME_DIR'] = f'/run/user/{UID}'
    os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{UID}/bus'
    for scope in UNITS:
        loaded = ctl(scope, 'show', UNIT, '-p', 'FragmentPath', '--value', capture=True, check=False).stdout.strip()
        if loaded and scope not in installed:
            fail(f'A Dashboard unit is still loaded without an owned unit file: {loaded}. Stop and reconcile it before uninstalling.')
    data = data_path(settings)
    # A custom directory may hold unrelated files: remove only known application data there.
    known = ['bookmarks.json', 'sessions.json', 'hosts.json', 'registered-services.json',
             'service-metadata.json', 'service-names.json', 'service-open-urls.json',
             'service-ports.json', 'service-favorites.json', 'manual-ports.json', 'local-catalog.json', '.json-transaction.json', 'ssh']
    targets = [APP / '.venv', ENV, RECEIPT, CONFIG / 'host-service-dashboard.sudoers']
    targets += [data] if data == APP / 'data' else [data / name for name in known]
    for path in targets: safe_path(path)
    step('Uninstall plan: the following Dashboard files will be deleted')
    for path in [*(UNITS[scope] for scope in installed), *targets]: print(f'  {path}')
    print('Source code, other services, existing /etc/sudoers.d rules, account groups and linger are retained.')
    print('Dashboard SSH keys will be deleted. Remove their public keys from remote authorized_keys separately.')
    if input('Type REMOVE to confirm permanent deletion: ') != 'REMOVE':
        fail('Cancelled; nothing removed.')
    for scope in installed:
        step(f'Stop, disable and remove {scope} Dashboard service')
        if scope == 'user':
            os.environ['XDG_RUNTIME_DIR'] = f'/run/user/{UID}'
            os.environ['DBUS_SESSION_BUS_ADDRESS'] = f'unix:path=/run/user/{UID}/bus'
        ctl(scope, 'disable', '--now', UNIT)
        remove_unit(scope); ctl(scope, 'daemon-reload')
        ctl(scope, 'reset-failed', UNIT, capture=True, check=False) if scope == 'user' else None
    for path in targets:
        if not path.exists(): continue
        step(f'Delete {path}')
        if path.is_dir(): shutil.rmtree(path)
        else: path.unlink()
    if CONFIG.exists() and not any(CONFIG.iterdir()): CONFIG.rmdir()
    step('Uninstall complete; source code retained. Run bash scripts/setup.sh to install again.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'reset', 'uninstall'])
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
        else: install(reset=action == 'reset', backend=args.backend)
    finally:
        os.close(descriptor)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, KeyboardInterrupt, EOFError) as error:
        print(f'\nERROR: {error or "Cancelled"}', file=sys.stderr)
        sys.exit(1)
