"""Tests for bin/rakabot-setup, against the same fake server the watcher uses.

The interactive path is driven in-process with a stubbed terminal, so no test
needs a tty (and none can hang waiting for one).
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_watch import FakeRakazo

SETUP = Path(__file__).resolve().parents[1] / 'bin/rakabot-setup'


def _load():
    loader = importlib.machinery.SourceFileLoader('rakabot_setup', str(SETUP))
    spec = importlib.util.spec_from_loader('rakabot_setup', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def protected_token_file(home, token='tok-123', name='given-token'):
    """A token file as the setup demands one: ours, and nobody else's to read."""
    path = home / name
    path.write_text(token + '\n')
    path.chmod(0o600)
    return path


def run_setup(*arguments, home):
    environment = dict(os.environ)
    environment['HOME'] = str(home)
    environment.pop('RAKABOT_TOKEN', None)
    environment.pop('RAKABOT_CONFIG', None)
    return subprocess.run([sys.executable, '-B', str(SETUP), *arguments], capture_output=True, text=True,
                          timeout=30, env=environment, check=False)


def run_setup_in_process(arguments, home, password=None, emailed=None):
    """main() with a stubbed terminal. `password=None` means no tty at all."""
    module = _load()
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('RAKABOT_TOKEN', 'RAKABOT_CONFIG')}
    environment['HOME'] = str(home)
    output = io.StringIO()

    def read_password(_prompt):
        if password is None:
            raise EOFError('no tty')
        return password

    with mock.patch.dict(os.environ, environment, clear=True):
        with mock.patch.object(sys, 'argv', [str(SETUP), *arguments]):
            with mock.patch.object(module, 'getpass') as guard:
                guard.getpass.side_effect = read_password
                with mock.patch.object(module, 'input', lambda prompt='': emailed or ''):
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                        code = module.main()
    return code, output.getvalue()


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.server = FakeRakazo()
        self.addCleanup(self.server.stop)
        self.config = self.home / '.config/rakabot/config.json'
        self.token = self.home / '.config/rakabot/token'

    def test_a_token_file_is_stored_private_and_used(self):
        result = run_setup('--url', self.server.url, '--token-file', str(protected_token_file(self.home)), home=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('answered: 0 bots', result.stdout)
        self.assertEqual(json.loads(self.config.read_text())['url'], self.server.url)
        self.assertEqual(self.token.read_text().strip(), 'tok-123')
        self.assertEqual(self.token.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.config.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.server.requests[-1]['authorization'], 'Bearer tok-123')

    def test_the_written_config_is_what_the_watcher_reads(self):
        run_setup('--url', self.server.url, '--token-file', str(protected_token_file(self.home)), home=self.home)
        watcher = importlib.machinery.SourceFileLoader('w', str(SETUP.parent / 'rakabot-watch'))
        spec = importlib.util.spec_from_loader('w', watcher)
        module = importlib.util.module_from_spec(spec)
        watcher.exec_module(module)
        with mock.patch.dict(os.environ, {'HOME': str(self.home)}, clear=True):
            loaded = module.load_config()
        self.assertEqual(loaded['url'], self.server.url)
        self.assertEqual(loaded['token'], 'tok-123')

    def test_signing_in_uses_the_password_and_never_keeps_it(self):
        code, output = run_setup_in_process(
            ['--url', self.server.url, '--email', 'oskar@example.com'], self.home,
            password=self.server.password)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.server.sign_ins[-1]['email'], 'oskar@example.com')
        self.assertEqual(self.token.read_text().strip(), 'session-token-abc')
        for path in (self.token, self.config):
            self.assertNotIn(self.server.password, path.read_text(), 'the password reached %s' % path)
        self.assertNotIn(self.server.password, output)
        self.assertIn('signed in as oskar@example.com', output)

    def test_the_email_is_asked_for_when_it_is_not_given(self):
        code, output = run_setup_in_process(['--url', self.server.url], self.home,
                                            password=self.server.password,
                                            emailed='oskar@example.com')
        self.assertEqual(code, 0, output)
        self.assertEqual(self.server.sign_ins[-1]['email'], 'oskar@example.com')

    def test_with_no_terminal_the_setup_stops_instead_of_reading_a_pipeline(self):
        code, output = run_setup_in_process(['--url', self.server.url, '--email', 'oskar@example.com'],
                                            self.home, password=None)
        self.assertEqual(code, 1)
        self.assertIn('cancelled', output)
        self.assertFalse(self.token.exists())
        self.assertEqual(self.server.sign_ins, [])

    def test_an_empty_password_is_refused(self):
        code, output = run_setup_in_process(['--url', self.server.url, '--email', 'oskar@example.com'],
                                            self.home, password='')
        self.assertEqual(code, 1)
        self.assertIn('no password given', output)
        self.assertFalse(self.token.exists())

    def test_a_wrong_password_is_reported(self):
        code, output = run_setup_in_process(['--url', self.server.url, '--email', 'oskar@example.com'],
                                            self.home, password='wrong password')
        self.assertEqual(code, 1)
        self.assertIn('sign-in failed: HTTP 401', output)
        self.assertFalse(self.token.exists())

    def test_a_rejected_token_is_caught_before_the_bar_sees_it(self):
        self.server.mode = 'unauthorized'
        result = run_setup('--url', self.server.url, '--token-file', str(protected_token_file(self.home, 'stale')), home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('401', result.stderr)

    def test_check_only_writes_nothing(self):
        result = run_setup('--url', self.server.url, '--token-file', str(protected_token_file(self.home)), '--check', home=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config.exists())
        self.assertFalse(self.token.exists())

    def test_the_url_has_to_be_a_url(self):
        result = run_setup('--url', 'rakazo.example', '--token-file', str(protected_token_file(self.home)), home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must start with http', result.stderr)

    def test_an_unknown_argument_is_refused(self):
        result = run_setup('--url', self.server.url, '--nope', home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unknown argument', result.stderr)

    def test_a_server_that_answers_without_a_token_is_reported(self):
        self.server.auth_token = ''
        module = _load()
        token, error = module.sign_in(self.server.url, 'oskar@example.com', self.server.password)
        self.assertEqual(token, '')
        self.assertIn('no session token', error)

    def test_a_cookie_only_sign_in_still_yields_a_token(self):
        module = _load()
        response = mock.MagicMock()
        response.headers = {'set-auth-token': None, 'set-cookie':
                            'better-auth.session_token=signed%2Btoken; Path=/; HttpOnly'}
        self.assertEqual(module.read_token(response, '{}'), 'signed+token')

    def test_a_token_in_the_reply_body_is_used_when_there_is_no_header(self):
        module = _load()
        response = mock.MagicMock()
        response.headers = {}
        self.assertEqual(module.read_token(response, '{"token": "from-body"}'), 'from-body')

    def test_the_url_has_to_be_https_unless_it_is_loopback(self):
        module = _load()
        self.assertEqual(module.url_problem('https://rakazo.example'), '')
        self.assertEqual(module.url_problem('http://127.0.0.1:8080'), '')
        self.assertEqual(module.url_problem('http://localhost:9000'), '')
        self.assertEqual(module.url_problem('http://[::1]:1'), '')
        for url in ('http://rakazo.example', 'http://192.168.1.10:8080', 'ftp://rakazo.example'):
            self.assertNotEqual(module.url_problem(url), '', url)

    def test_a_plain_http_server_is_refused_before_anything_is_sent(self):
        result = run_setup('--url', 'http://rakazo.example', home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing plain http', result.stderr)
        self.assertFalse(self.token.exists())
        self.assertEqual(self.server.sign_ins, [])

    def test_a_loopback_http_server_still_works(self):
        # The test server is http://127.0.0.1:PORT and must keep working: the whole
        # suite runs against it, and a server on this machine never hits a network.
        result = run_setup('--url', self.server.url, '--token-file',
                           str(protected_token_file(self.home)), home=self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.token.exists())

    def test_the_token_cannot_come_from_an_argument(self):
        # A secret in argv is readable from /proc/<pid>/cmdline, which is world
        # readable, so the flag is refused outright with a way forward.
        result = run_setup('--url', self.server.url, '--token', 'tok-123', home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--token is gone on purpose', result.stderr)
        self.assertIn('--token-file', result.stderr)

    def test_a_token_file_readable_by_others_is_refused(self):
        loose = protected_token_file(self.home, 'tok-123', 'loose')
        loose.chmod(0o644)
        result = run_setup('--url', self.server.url, '--token-file', str(loose), home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('readable by other users', result.stderr)
        self.assertIn('chmod 600', result.stderr)
        self.assertFalse(self.token.exists())

    def test_a_missing_token_file_is_reported(self):
        result = run_setup('--url', self.server.url, '--token-file', str(self.home / 'nope'), home=self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('cannot read', result.stderr)

    def test_the_token_can_come_from_stdin(self):
        module = _load()
        with mock.patch.object(sys, 'stdin', io.StringIO('piped-token\n')):
            with mock.patch.object(sys.stdin, 'isatty', lambda: False, create=True):
                token, error = module.read_token_stdin()
        self.assertEqual((token, error), ('piped-token', ''))

    def test_stdin_refuses_a_terminal(self):
        module = _load()
        with mock.patch.object(sys, 'stdin', io.StringIO('piped-token\n')):
            with mock.patch.object(sys.stdin, 'isatty', lambda: True, create=True):
                token, error = module.read_token_stdin()
        self.assertEqual(token, '')
        self.assertIn('needs the token piped in', error)

    def test_an_empty_stdin_is_reported(self):
        module = _load()
        with mock.patch.object(sys, 'stdin', io.StringIO('\n')):
            with mock.patch.object(sys.stdin, 'isatty', lambda: False, create=True):
                token, error = module.read_token_stdin()
        self.assertEqual(token, '')
        self.assertIn('no token arrived', error)

    def test_a_redirect_is_refused_instead_of_carrying_the_token(self):
        # urllib would follow a 3xx to another host and resend Authorization there.
        module = _load()
        opener = module.http_opener()
        self.assertTrue(any(isinstance(h, module.NoRedirect) for h in opener.handlers),
                        'the opener must refuse redirects')


if __name__ == '__main__':
    unittest.main()
