"""Tests for bin/rakabot-open, which decides what "open Rakazo" means here.

Every external command (hyprctl, gtk-launch, xdg-open, omarchy-launch-webapp) is a
shim on PATH that records its arguments, so the cascade is asserted end to end
without touching a real session.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

OPENER = Path(__file__).resolve().parents[1] / 'bin/rakabot-open'
URL = 'https://rakazo.tail9e18cf.ts.net'
CHROME_CLASS = 'chrome-rakazo.tail9e18cf.ts.net__-Default'

SHIM = """#!/bin/bash
printf '%s' "$(basename "$0")" >> "$RAKABOT_TEST_LOG"
for argument in "$@"; do printf ' %s' "$argument" >> "$RAKABOT_TEST_LOG"; done
printf '\\n' >> "$RAKABOT_TEST_LOG"
{extra}
exit 0
"""


class OpenerHarness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.log = self.home / 'calls.log'
        self.clients = self.home / 'clients.json'
        self.applications = self.home / '.local/share/applications'
        self.applications.mkdir(parents=True)
        self.write_shim('hyprctl', extra='cat "$RAKABOT_TEST_CLIENTS"')
        for name in ('gtk-launch', 'xdg-open', 'omarchy-launch-webapp', 'omarchy-launch-browser'):
            self.write_shim(name)
        self.set_clients([])

    def write_shim(self, name, extra=''):
        path = self.bin / name
        path.write_text(SHIM.format(extra=extra))
        path.chmod(0o755)

    def set_clients(self, clients):
        self.clients.write_text(json.dumps(clients))

    def window(self, **overrides):
        window = {'address': '0xabc', 'class': CHROME_CLASS, 'initialClass': CHROME_CLASS,
                  'title': 'Rakazo'}
        window.update(overrides)
        return window

    def web_app(self, name='webapp-rakazo.desktop', url=URL):
        (self.applications / name).write_text(textwrap.dedent("""\
            [Desktop Entry]
            Type=Application
            Name=Rakazo
            Exec=google-chrome --app=%s
            Icon=web-browser
            """ % url))

    def run_opener(self, *arguments):
        environment = dict(os.environ)
        environment.update({
            'PATH': '%s:%s' % (self.bin, os.environ.get('PATH', '')),
            'HOME': str(self.home),
            'RAKABOT_APPLICATIONS': str(self.applications),
            'RAKABOT_TEST_LOG': str(self.log),
            'RAKABOT_TEST_CLIENTS': str(self.clients),
        })
        result = subprocess.run([sys.executable, '-B', str(OPENER), *arguments],
                                capture_output=True, text=True, timeout=30, env=environment, check=False)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, calls

    def called(self, calls, name):
        return [line for line in calls if line.split()[0] == name]

    def dispatched(self, calls):
        return [line for line in calls if line.startswith('hyprctl dispatch')]


class WindowTest(OpenerHarness):
    def test_an_open_web_app_window_is_focused_not_relaunched(self):
        self.set_clients([self.window()])
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('focused the open Rakazo window', result.stdout)
        self.assertEqual(len(self.dispatched(calls)), 1)
        self.assertIn('address:0xabc', self.dispatched(calls)[0])
        self.assertEqual(self.called(calls, 'xdg-open'), [])
        self.assertEqual(self.called(calls, 'gtk-launch'), [])

    def test_the_desktop_app_window_is_focused_too(self):
        self.set_clients([self.window(**{'class': 'rakazo', 'initialClass': 'rakazo'})])
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('focused', result.stdout)

    def test_a_window_titled_after_the_server_is_focused(self):
        self.set_clients([self.window(**{'class': 'google-chrome', 'initialClass': 'google-chrome',
                                        'title': 'Rakazo - Google Chrome'})])
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('focused', result.stdout)

    def test_a_lookalike_window_is_not_mistaken_for_ours(self):
        self.set_clients([self.window(**{'class': 'notrakazo.example', 'initialClass': 'notrakazo.example',
                                         'title': 'something else'})])
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dispatched(calls), [], 'word boundaries must hold')

    def test_an_unrelated_window_leaves_the_fallbacks_in_place(self):
        self.set_clients([self.window(**{'class': 'firefox', 'initialClass': 'firefox', 'title': 'Docs'})])
        self.web_app()
        result, calls = self.run_opener(URL)
        self.assertIn('launched the Rakazo web app', result.stdout)
        self.assertEqual(self.called(calls, 'gtk-launch')[0].split()[1], 'webapp-rakazo')

    def test_hyprland_that_does_not_answer_degrades_quietly(self):
        self.clients.write_text('not json at all')
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('opened', result.stdout)
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)


class WebAppTest(OpenerHarness):
    def test_an_installed_web_app_is_launched_when_no_window_is_open(self):
        self.web_app()
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('launched the Rakazo web app', result.stdout)
        self.assertEqual(self.called(calls, 'gtk-launch'), ['gtk-launch webapp-rakazo'])
        self.assertEqual(self.called(calls, 'xdg-open'), [])

    def test_a_web_app_for_another_address_is_ignored(self):
        self.web_app(name='webapp-openwebui.desktop', url='https://openwebui.tail9e18cf.ts.net')
        result, calls = self.run_opener(URL)
        self.assertIn('opened', result.stdout)
        self.assertEqual(self.called(calls, 'gtk-launch'), [])
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)

    def test_a_web_app_behind_a_path_is_still_ours(self):
        self.web_app(url='https://rakazo.tail9e18cf.ts.net/inbox/1')
        result, calls = self.run_opener(URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), ['gtk-launch webapp-rakazo'])

    def test_web_app_entries_that_are_not_app_mode_are_ignored(self):
        (self.applications / 'webapp-rakazo.desktop').write_text(
            '[Desktop Entry]\nType=Application\nName=Rakazo\nExec=firefox https://rakazo.tail9e18cf.ts.net\n')
        result, calls = self.run_opener(URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), [])
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)


class WebAppFormTest(OpenerHarness):
    """The three shapes a Rakazo launcher can take on an Omarchy machine."""

    def entry(self, name, body):
        (self.applications / name).write_text(textwrap.dedent(body))

    def test_an_omarchy_web_app_entry_is_used(self):
        self.entry('Rakazo.desktop', """\
            [Desktop Entry]
            Version=1.0
            Name=Rakazo
            Exec=omarchy-launch-webapp https://rakazo.tail9e18cf.ts.net
            Type=Application
            Icon=rakazo
            """)
        result, calls = self.run_opener(URL)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('launched the Rakazo web app', result.stdout)
        self.assertEqual(self.called(calls, 'gtk-launch'), ['gtk-launch Rakazo'])

    def test_another_site_s_omarchy_web_app_is_ignored(self):
        self.entry('Gmail.desktop', """\
            [Desktop Entry]
            Name=Gmail
            Exec=omarchy-launch-webapp https://mail.google.com/mail/u/0/
            Type=Application
            """)
        result, calls = self.run_opener(URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), [])
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)

    def test_a_browser_shortcut_is_matched_by_its_window_class(self):
        self.entry('Rakazo app.desktop', """\
            [Desktop Entry]
            Name=Something else
            Exec=google-chrome --profile-directory=Default --app-id=khgjhlppnfndncpjdcgpjbgmjpfbpcnf
            StartupWMClass=chrome-rakazo.tail9e18cf.ts.net__-Default
            Type=Application
            """)
        result, calls = self.run_opener(URL)
        self.assertIn('launched the Rakazo web app', result.stdout)
        self.assertEqual(self.called(calls, 'gtk-launch'), ['gtk-launch Rakazo app'])

    def test_a_tui_launcher_with_an_app_id_is_ignored(self):
        self.entry('Docker.desktop', """\
            [Desktop Entry]
            Name=Docker
            Exec=xdg-terminal-exec --app-id=TUI.tile -e omarchy-launch-docker-tui
            Type=Application
            """)
        result, calls = self.run_opener(URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), [])
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)

    def test_an_entry_named_after_rakazo_is_not_enough(self):
        # A launcher that mentions Rakazo is not necessarily one that opens it.
        self.entry('webapp-rakazo.desktop', """\
            [Desktop Entry]
            Name=Rakazo Tail9e18cf Ts Net
            Exec=google-chrome --profile-directory=Default --app-id=zzzz
            Type=Application
            """)
        result, calls = self.run_opener(URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), [])
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)

    def test_the_address_beats_a_window_class_match(self):
        self.entry('Rakazo pwa.desktop', """\
            [Desktop Entry]
            Name=Rakazo
            Exec=google-chrome --profile-directory=Default --app-id=zzzz
            StartupWMClass=chrome-rakazo.tail9e18cf.ts.net__-Default
            Type=Application
            """)
        self.entry('Rakazo.desktop', """\
            [Desktop Entry]
            Name=Rakazo
            Exec=omarchy-launch-webapp https://rakazo.tail9e18cf.ts.net
            Type=Application
            """)
        result, calls = self.run_opener(URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), ['gtk-launch Rakazo'])


class PreferenceTest(OpenerHarness):
    def test_prefer_browser_ignores_an_open_window(self):
        self.set_clients([self.window()])
        self.web_app()
        result, calls = self.run_opener('--prefer', 'browser', URL)
        self.assertIn('in the browser', result.stdout)
        self.assertEqual(self.dispatched(calls), [])
        self.assertEqual(self.called(calls, 'gtk-launch'), [])
        self.assertEqual(len(self.called(calls, 'xdg-open')), 1)

    def test_prefer_web_app_opens_a_window_even_without_a_launcher(self):
        result, calls = self.run_opener('--prefer', 'web-app', URL)
        self.assertIn('as a web app window', result.stdout)
        self.assertEqual(self.called(calls, 'omarchy-launch-webapp'), [
            'omarchy-launch-webapp %s' % URL])
        self.assertEqual(self.called(calls, 'xdg-open'), [])

    def test_prefer_web_app_still_uses_the_launcher_when_there_is_one(self):
        self.web_app()
        result, calls = self.run_opener('--prefer', 'web-app', URL)
        self.assertEqual(self.called(calls, 'gtk-launch'), ['gtk-launch webapp-rakazo'])
        self.assertEqual(self.called(calls, 'omarchy-launch-webapp'), [])


class ArgumentTest(OpenerHarness):
    def test_an_address_is_required(self):
        result, _ = self.run_opener()
        self.assertEqual(result.returncode, 1)
        self.assertIn('usage', result.stderr)

    def test_an_unknown_preference_is_refused(self):
        result, _ = self.run_opener('--prefer', 'sometimes', URL)
        self.assertEqual(result.returncode, 1)
        self.assertIn('--prefer takes', result.stderr)

    def test_an_argument_that_is_not_an_address_is_refused(self):
        result, _ = self.run_opener('rakazo')
        self.assertEqual(result.returncode, 1)
        self.assertIn('not an address', result.stderr)

    def test_an_extra_pattern_can_be_added(self):
        self.set_clients([self.window(**{'class': 'some-browser', 'initialClass': 'some-browser',
                                         'title': 'untitled'})])
        result, calls = self.run_opener('--pattern', 'untitled', URL)
        self.assertIn('focused', result.stdout)


if __name__ == '__main__':
    unittest.main()
