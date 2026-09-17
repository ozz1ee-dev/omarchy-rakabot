"""Tests for the watcher's notifications.

The plugin sends its own notifications, because the ones the Rakazo page raises
through Chrome arrive named and drawn as Chrome and cannot be restyled from
outside. What is tested here: only transitions are announced, never the world as
it already stood; the same event is announced once even though the bar runs two
watchers; muted bots stay silent; and the notification carries our mark plus a
click action that lands on the bot that wrote.
"""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

WATCHER = Path(__file__).resolve().parents[1] / 'bin/rakabot-watch'


def load_watcher():
    loader = importlib.machinery.SourceFileLoader('rakabot_watch_notify', str(WATCHER))
    spec = importlib.util.spec_from_loader('rakabot_watch_notify', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def bot(identifier='b1', name='Chief', unread=0, activity=100.0, awaiting=False,
        reason='', preview='hello there', muted=False):
    return {'id': identifier, 'name': name, 'unread': unread, 'last_activity_ts': activity,
            'awaiting': awaiting, 'awaiting_reason': reason, 'last_text': preview,
            'muted': muted}


def state(bots, url='https://rakazo.test'):
    return {'app': {'url': url}, 'bots': bots}


class NotifyHarness(unittest.TestCase):
    """A watcher whose paths, sender and PATH all point inside a temp directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        self.calls = self.dir / 'calls.log'
        self.module = load_watcher()
        self.module.NOTIFY_STATE = str(self.dir / 'notify.json')
        self.module.NOTIFY_LOCK = str(self.dir / 'notify.lock')
        self.module.MARK = str(self.dir / 'mark.png')
        self.module.OPENER = str(self.dir / 'rakabot-open')
        (self.dir / 'mark.png').write_bytes(b'png')
        (self.dir / 'rakabot-open').write_text('#!/bin/sh\n')
        os.chmod(self.module.OPENER, 0o755)
        self.write_sender('omarchy-notification-send')
        self.previous_path = os.environ.get('PATH', '')
        # Nothing outside the shims: a fall-through would post into the live session.
        os.environ['PATH'] = str(self.bin)

    def tearDown(self):
        os.environ['PATH'] = self.previous_path
        self.tmp.cleanup()

    def write_sender(self, name, body=None):
        path = self.bin / name
        path.write_text(body if body else """#!/bin/bash
# Tab separated: an argument may contain spaces, and the test must still see it
# as one argument. bash builtins only, so PATH can hold nothing but these shims.
printf '%s' "${0##*/}" >> "$NOTIFY_TEST_LOG"
for argument in "$@"; do printf '\\t%s' "$argument" >> "$NOTIFY_TEST_LOG"; done
printf '\\n' >> "$NOTIFY_TEST_LOG"
exit 0
""")
        os.chmod(path, 0o755)
        os.environ['NOTIFY_TEST_LOG'] = str(self.calls)
        return path

    def posted(self):
        if not self.calls.exists():
            return []
        return [line for line in self.calls.read_text().splitlines() if line.strip()]

    def remember(self, snapshot):
        """Put a snapshot on file as if an earlier pass had seen it."""
        with open(self.module.NOTIFY_STATE, 'w', encoding='utf-8') as handle:
            json.dump(self.module.seen_state(snapshot), handle)

    def events(self, snapshot):
        return self.module.notification_events(self.module.read_notify_state(), snapshot)


class EventTest(NotifyHarness):
    def test_the_first_pass_records_the_world_instead_of_announcing_it(self):
        self.assertIsNone(self.module.read_notify_state())
        snapshot = state([bot(unread=3, activity=100.0)])
        self.assertEqual(self.module.notification_events(None, snapshot), [])
        self.assertEqual(self.module.notify_pass(snapshot, True), [])
        self.assertEqual(self.posted(), [])
        self.assertEqual(self.module.read_notify_state()['seen']['b1']['unread'], 3)

    def test_a_bot_that_wrote_is_announced_once(self):
        self.remember(state([bot(unread=0, activity=100.0)]))
        snapshot = state([bot(unread=1, activity=106.0, preview='<b>Deploy</b> is done')])
        events = self.events(snapshot)
        self.assertEqual([(e['kind'], e['name'], e['text'], e['index']) for e in events],
                         [('message', 'Chief', 'bDeploy/b is done', 1)])
        self.module.notify_pass(snapshot, True)
        self.assertEqual(len(self.posted()), 1)
        # Same snapshot again: already announced, so nothing.
        self.assertEqual(self.events(snapshot), [])

    def test_a_bot_that_starts_waiting_is_announced_with_its_reason(self):
        self.remember(state([bot(unread=1, activity=100.0)]))
        snapshot = state([bot(unread=1, activity=100.0, awaiting=True,
                              reason='Waiting for your approval')])
        events = self.events(snapshot)
        self.assertEqual([(e['kind'], e['text']) for e in events],
                         [('awaiting', 'Waiting for your approval')])

    def test_a_muted_bot_is_never_announced(self):
        self.remember(state([bot(unread=0, activity=100.0)]))
        snapshot = state([bot(unread=4, activity=200.0, muted=True, awaiting=True)])
        self.assertEqual(self.events(snapshot), [])

    def test_a_bot_the_roster_only_just_met_is_not_announced(self):
        self.remember(state([bot('b1')]))
        snapshot = state([bot('b1'), bot('b2', name='New', unread=1, activity=500.0)])
        self.assertEqual(self.events(snapshot), [])

    def test_the_newest_events_win_when_many_arrive_at_once(self):
        self.remember(state([bot('b%d' % i, name='Bot %d' % i, activity=1.0) for i in range(1, 6)]))
        snapshot = state([bot('b%d' % i, name='Bot %d' % i, unread=1, activity=10.0 * i)
                          for i in range(1, 6)])
        events = self.events(snapshot)
        self.assertEqual([e['id'] for e in events], ['b5', 'b4', 'b3'])
        self.assertEqual([e['index'] for e in events], [5, 4, 3])

    def test_the_lock_keeps_a_second_watcher_quiet(self):
        import fcntl
        os.makedirs(os.path.dirname(self.module.NOTIFY_STATE), exist_ok=True)
        held = open(self.module.NOTIFY_LOCK, 'w')
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.module.notify_pass(state([bot()]), True), [])
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()


class PostingTest(NotifyHarness):
    def test_the_notification_carries_our_mark_and_a_click_that_opens_that_bot(self):
        event = {'id': 'b4', 'name': 'Web', 'index': 4, 'activity': 9.0, 'unread': 1,
                 'kind': 'message', 'text': 'new links'}
        self.assertTrue(self.module.post_notification(event, 'https://rakazo.test'))
        lines = self.posted()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].split('\t'), [
            'omarchy-notification-send', '--app-name', 'Rakabot', '-u', 'normal',
            '-i', self.module.MARK, 'Web', 'new links',
            '--exec', self.module.OPENER, '--select-index', '4', '--select', 'Web',
            'https://rakazo.test'])

    def test_a_waiting_bot_says_so_in_the_headline(self):
        event = {'id': 'b1', 'name': 'Chief', 'index': 1, 'activity': 9.0, 'unread': 0,
                 'kind': 'awaiting', 'text': 'Waiting for you.'}
        self.module.post_notification(event, 'https://rakazo.test')
        self.assertIn('Chief wants you', self.posted()[0])

    def test_plain_notify_send_is_used_when_omarchy_has_none(self):
        (self.bin / 'omarchy-notification-send').unlink()
        self.write_sender('notify-send')
        event = {'id': 'b1', 'name': 'Chief', 'index': 1, 'activity': 9.0, 'unread': 1,
                 'kind': 'message', 'text': 'hi'}
        self.assertTrue(self.module.post_notification(event, 'https://rakazo.test'))
        self.assertEqual(self.posted()[0].split('\t'), [
            'notify-send', '-a', 'Rakabot', '-i', self.module.MARK, 'Chief', 'hi'])

    def test_no_sender_at_all_is_not_a_crash(self):
        (self.bin / 'omarchy-notification-send').unlink()
        event = {'id': 'b1', 'name': 'Chief', 'index': 1, 'activity': 9.0, 'unread': 1,
                 'kind': 'message', 'text': 'hi'}
        self.assertFalse(self.module.post_notification(event, 'https://rakazo.test'))
        self.assertEqual(self.posted(), [])

    def test_off_still_records_so_turning_it_back_on_does_not_replay(self):
        snapshot = state([bot(unread=0, activity=100.0)])
        self.module.notify_pass(snapshot, True)
        newer = state([bot(unread=2, activity=150.0)])
        self.assertEqual(self.module.notify_pass(newer, False), [])
        self.assertEqual(self.posted(), [])
        self.assertEqual(self.module.read_notify_state()['seen']['b1']['unread'], 2)
        self.assertEqual(self.events(newer), [])

    def test_the_first_line_of_a_message_is_what_gets_shown(self):
        long_preview = 'a' * 400
        self.assertEqual(len(self.module.first_line(long_preview, 140)), 140)
        self.assertEqual(self.module.first_line('one\ntwo   three', 40), 'one two three')


if __name__ == '__main__':
    unittest.main()
