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
