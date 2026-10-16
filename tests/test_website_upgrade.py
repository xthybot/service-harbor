"""Actual local Git update preserves fictional installation data; no network."""
import subprocess
import tempfile
import unittest
from pathlib import Path


class WebsiteUpgrade(unittest.TestCase):
    def test_git_pull_preserves_existing_private_files(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='harbor-upgrade-') as temporary:
            copy = Path(temporary) / 'installation'
            def git(*args):
                return subprocess.run(['git', '-C', str(copy), *args], check=True, capture_output=True, text=True)
            subprocess.run(['git', 'clone', '--quiet', '--no-local', str(source), str(copy)], check=True, capture_output=True)
            git('switch', '-C', 'main', '248dd03')  # Published version before website_check.
            saved = {'data/registered-services.json': '[{"id":"svc-old","open_url":"https://example.invalid"}]',
                     'data/hosts.json': '[{"id":"fictional-host"}]',
                     'data/sessions.json': '{"fictional-session":123}',
                     'data/ssh/dashboard_ed25519': 'FICTIONAL PRIVATE KEY ONLY',
                     'data/ssh/fictional.known_hosts': 'FICTIONAL HOST KEY ONLY',
                     '.venv/pyvenv.cfg': 'fictional environment',
                     '.env': 'DASHBOARD_PASSWORD=fictional-example',
                     'local-notes.txt': 'untracked local notes'}
            for name, value in saved.items():
                path = copy / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
            settings = Path(temporary) / 'home/.config/dashboard/dashboard.env'
            settings.parent.mkdir(parents=True); settings.write_text('fictional external install settings')
            self.assertFalse((copy / 'app/website_checks.py').exists())
            git('pull', '--ff-only', 'origin', 'main')
            self.assertTrue((copy / 'app/website_checks.py').exists())
            for name, value in saved.items():
                self.assertEqual((copy / name).read_text(), value, name)
            self.assertEqual(settings.read_text(), 'fictional external install settings')
            self.assertEqual(git('rev-parse', 'HEAD').stdout.strip(), git('rev-parse', 'origin/main').stdout.strip())
