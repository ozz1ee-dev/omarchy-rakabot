"""Tests for bin/rakabot-watch against a fake Rakazo server.

The watcher is the only part of this plugin that talks to anything, so it is the
part that has to earn its keep: the RPC calls it makes, the roster it maps out of
Rakazo's schema, the avatar encoding, and the cache it writes uploaded pictures
into. Nothing here reaches a real server.
"""
import base64
import http.server
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

WATCHER = Path(__file__).resolve().parents[1] / 'bin/rakabot-watch'
PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
PNG_URL = 'data:image/png;base64,' + base64.b64encode(PNG).decode()


def load_watcher():
    loader = importlib.machinery.SourceFileLoader('rakabot_watch', str(WATCHER))
    spec = importlib.util.spec_from_loader('rakabot_watch', loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeRakazo:
    """A stand-in for the oRPC endpoints the watcher is allowed to call."""

    def __init__(self, bots=(), sections=(), groups=(), health=None, token='good-token'):
        self.bots = list(bots)
        self.sections = list(sections)
        self.groups = list(groups)
        self.health = health if health is not None else {'ok': True, 'version': '0.27.3'}
        self.token = token
        self.password = 'correct horse battery staple'
        self.auth_token = 'session-token-abc'
        self.sign_ins = []
        self.mode = 'ok'          # ok | unauthorized | error | garbage
        self.requests = []
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return 'http://127.0.0.1:%d' % self.server.server_address[1]

    def handler(outer):
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get('content-length') or 0)
                body = self.rfile.read(length).decode('utf-8', 'replace')
                outer.requests.append({
                    'path': self.path,
                    'authorization': self.headers.get('authorization'),
                    'body': json.loads(body or '{}'),
                })
                if self.path == '/api/auth/sign-in/email':
                    outer.sign_ins.append(json.loads(body or '{}'))
                    if json.loads(body or '{}').get('password') == outer.password:
                        payload = json.dumps({'user': {'email': json.loads(body)['email']}}).encode()
                        self.send_response(200)
                        self.send_header('content-type', 'application/json')
                        self.send_header('set-auth-token', outer.auth_token)
                        self.send_header('content-length', str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                    else:
                        self.reply(401, {'message': 'Invalid email or password'})
                elif outer.mode == 'unauthorized':
                    self.reply(401, {'json': {'code': 'UNAUTHORIZED', 'status': 401, 'message': 'Unauthorized'}})
                elif outer.mode == 'error':
                    self.reply(500, {'json': {'code': 'INTERNAL', 'message': 'boom'}})
                elif outer.mode == 'garbage':
                    self.send_response(200)
                    self.send_header('content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'<html>not json</html>')
                elif self.path == '/rpc/health':
                    self.reply(200, {'json': outer.health})
                elif self.path == '/rpc/bots/list':
                    self.reply(200, {'json': outer.bots})
                elif self.path == '/rpc/botSections/list':
                    self.reply(200, {'json': outer.sections})
                elif self.path == '/rpc/groups/list':
                    self.reply(200, {'json': outer.groups})
                else:
                    self.reply(404, {'json': {'code': 'NOT_FOUND', 'message': 'no such procedure'}})

            def reply(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def bot(**overrides):
    record = {
        'id': 'bot-1', 'spaceId': 'space-1', 'name': 'Chief of Staff', 'title': 'Operations',
        'description': '', 'instructions': '', 'color': '#8B5CF6::shape_2', 'notifyOnFinish': True,
        'pinned': False, 'sectionId': None, 'archivedAt': None, 'unread': False, 'parentBotId': None,
        'memoryScope': None, 'threadId': 'thread-1', 'preview': 'Your Thursday is triple-booked.',
        'status': 'idle', 'computerMode': 'team', 'updatedAt': '2026-09-17T21:00:00.000Z',
        'createdAt': '2026-09-01T09:00:00.000Z', 'voiceId': None, 'autoSpeak': False,
        'modelProvider': 'opencode-go', 'modelId': 'deepseek-v4.1-flash', 'thinkingLevel': None,
        'teamChatAmbientEnabled': False, 'teamChatRules': '', 'webhookConfigured': False,
        'spawnKey': None,
    }
    record.update(overrides)
    return record


class WatcherHarness(unittest.TestCase):
    def setUp(self):
        self.module = load_watcher()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.module.CACHE = str(self.home / 'avatars')
        self.server = FakeRakazo()
        self.addCleanup(self.server.stop)

    def config(self, **overrides):
        token_file = self.home / 'token'
        token_file.write_text('file-token\n')
        token_file.chmod(0o600)
        config = {'url': self.server.url, 'tokenFile': str(token_file)}
        config.update(overrides)
        path = self.home / 'config.json'
        path.write_text(json.dumps(config))
        os.environ['RAKABOT_CONFIG'] = str(path)
        self.addCleanup(os.environ.pop, 'RAKABOT_CONFIG', None)
        return self.module.load_config()

    def snapshot(self, bots=(), sections=(), groups=(), **config_overrides):
        self.server.bots = list(bots)
        self.server.sections = list(sections)
        self.server.groups = list(groups)
        return self.module.snapshot(self.config(**config_overrides))


class ContractTest(WatcherHarness):
    def test_reads_only_the_three_documented_procedures(self):
        self.snapshot(bots=[bot()])
        paths = [request['path'] for request in self.server.requests]
        self.assertEqual(sorted(set(paths)), ['/rpc/botSections/list', '/rpc/bots/list', '/rpc/groups/list',
                                              '/rpc/health'])
        for request in self.server.requests:
            self.assertEqual(request['body'], {'json': {}}, 'a read call must not send arguments')

    def test_token_and_envelope(self):
        self.snapshot(bots=[bot()])
        for request in self.server.requests:
            self.assertEqual(request['authorization'], 'Bearer file-token')

    def test_environment_token_wins_over_the_token_file(self):
        os.environ['RAKABOT_TOKEN'] = 'env-token'
        self.addCleanup(os.environ.pop, 'RAKABOT_TOKEN', None)
        self.snapshot(bots=[bot()])
        self.assertEqual(self.server.requests[0]['authorization'], 'Bearer env-token')

    def test_health_is_reported_as_the_server_version_and_url(self):
        state = self.snapshot(bots=[bot()])
        self.assertTrue(state['app']['running'])
        self.assertEqual(state['app']['version'], '0.27.3')
        self.assertEqual(state['app']['url'], self.server.url)
        self.assertNotIn('error', state['app'])

    def test_snapshot_has_every_field_the_widget_reads(self):
        state = self.snapshot(bots=[bot()])
        self.assertEqual(sorted(state), ['app', 'bots', 'counts', 'generated_ts', 'sections'])
        for key in ('id', 'name', 'title', 'description', 'shape', 'color', 'avatar', 'hex', 'is_group',
                    'members', 'unread', 'awaiting', 'awaiting_reason', 'working', 'working_since_ts',
                    'muted', 'last_text', 'last_activity_ts', 'last_viewed_ts', 'focused', 'pinned'):
            self.assertIn(key, state['bots'][0], 'missing %s' % key)

    def test_every_field_the_qml_reads_is_produced_by_the_watcher(self):
        # The widget and the watcher are two files with no compiler between them,
        # so the contract is checked rather than assumed.
        widget = (WATCHER.parents[1] / 'Widget.qml').read_text()
        state = self.snapshot(bots=[bot()])
        produced = set(state['bots'][0])
        for field in sorted(set(__import__('re').findall(r'modelData\.bot\.([a-z_]+)', widget))
                            | set(__import__('re').findall(r'\bb\.([a-z_]+)\b', widget))):
            self.assertIn(field, produced, 'Widget.qml reads bot.%s, the watcher never sends it' % field)

    def test_archived_bots_are_left_out(self):
        state = self.snapshot(bots=[bot(), bot(id='bot-2', name='Old', archivedAt='2026-08-01T00:00:00.000Z')])
        self.assertEqual([item['id'] for item in state['bots']], ['bot-1'])


class StatusTest(WatcherHarness):
    def one(self, **overrides):
        return self.snapshot(bots=[bot(**overrides)])['bots'][0]

    def test_waiting_runs_ask_for_you_and_carry_the_last_message(self):
        item = self.one(status='waiting_input', preview='Shall I move the Vercel sync?')
        self.assertTrue(item['awaiting'])
        self.assertFalse(item['working'])
        self.assertEqual(item['awaiting_reason'], 'Shall I move the Vercel sync?')

    def test_takeover_counts_as_waiting_too(self):
        self.assertTrue(self.one(status='waiting_takeover')['awaiting'])

    def test_active_runs_are_working(self):
        for status in ('queued', 'leased', 'running'):
            item = self.one(status=status)
            self.assertTrue(item['working'], status)
            self.assertFalse(item['awaiting'], status)
            self.assertEqual(item['working_since_ts'], self.module.epoch('2026-09-17T21:00:00.000Z'))

    def test_finished_runs_are_neither(self):
        for status in ('completed', 'failed', 'cancelled'):
            item = self.one(status=status)
            self.assertFalse(item['working'], status)
            self.assertFalse(item['awaiting'], status)
            self.assertEqual(item['working_since_ts'], 0.0)

    def test_unread_is_a_boolean_in_rakazo(self):
        self.assertEqual(self.one(unread=True)['unread'], 1)
        self.assertEqual(self.one(unread=False)['unread'], 0)

    def test_notifications_off_reads_as_muted(self):
        self.assertTrue(self.one(notifyOnFinish=False)['muted'])
        self.assertFalse(self.one(notifyOnFinish=True)['muted'])

    def test_timestamps_are_seconds_since_the_epoch(self):
        self.assertEqual(self.one(updatedAt='2026-09-17T21:00:00.000Z')['last_activity_ts'], 1789678800.0)
        self.assertEqual(self.one(updatedAt=None)['last_activity_ts'], 0.0)
        self.assertEqual(self.one(updatedAt='not a date')['last_activity_ts'], 0.0)

    def test_control_characters_never_reach_the_widget(self):
        item = self.one(name='bad\u202ename', preview='line\nline\x07')
        self.assertEqual(item['name'], 'bad name')
        self.assertEqual(item['last_text'], 'line line ')


class SectionTest(WatcherHarness):
    def test_sections_follow_the_section_ids_and_keep_their_order(self):
        state = self.snapshot(
            bots=[bot(id='b1', sectionId='s1'), bot(id='b2', sectionId='s2'), bot(id='b3', sectionId='s1')],
            sections=[{'id': 's2', 'name': 'Personal', 'spaceId': 'space-1'},
                      {'id': 's1', 'name': 'ACME', 'spaceId': 'space-1'}])
        self.assertEqual(state['sections'], [
            {'id': 's2', 'name': 'Personal', 'bot_ids': ['b2']},
            {'id': 's1', 'name': 'ACME', 'bot_ids': ['b1', 'b3']},
        ])

    def test_unsectioned_bots_land_in_one_trailing_bucket(self):
        state = self.snapshot(bots=[bot(id='b1', sectionId='s1'), bot(id='b2'), bot(id='b3', sectionId='gone')],
                              sections=[{'id': 's1', 'name': 'ACME'}])
        self.assertEqual(state['sections'][-1], {'id': '__loose__', 'name': 'Unassigned', 'bot_ids': ['b2', 'b3']})

    def test_a_roster_with_no_sections_stays_flat(self):
        state = self.snapshot(bots=[bot(id='b1'), bot(id='b2')])
        self.assertEqual(state['sections'], [])


class AvatarTest(WatcherHarness):
    def one(self, colour):
        return self.snapshot(bots=[bot(color=colour)])['bots'][0]

    def test_shape_suffix_picks_the_app_s_own_shape(self):
        self.assertEqual(self.one('#EF4444::shape_0')['shape'], 'hex')
        self.assertEqual(self.one('#EF4444::shape_3')['shape'], 'tablet')
        self.assertEqual(self.one('#EF4444::shape_7')['shape'], 'cloud')
        self.assertEqual(self.one('#EF4444::shape_8')['shape'], 'hex', 'the index wraps like the app')
        self.assertEqual(self.one('#EF4444::shape_broken')['shape'], 'hex')

    def test_colour_name_comes_from_the_app_palette(self):
        self.assertEqual(self.one('#8B5CF6::shape_2')['color'], 'violet')
        self.assertEqual(self.one('#8B5CF6::shape_2')['hex'], '#8B5CF6')
        self.assertEqual(self.one('#ffffff::shape_0')['color'], 'white')
        self.assertEqual(self.one('#fff::shape_0')['color'], 'white', 'short hex is expanded')

    def test_a_bare_hex_still_gets_a_colour_and_a_shape(self):
        item = self.one('#F97316')
        self.assertEqual(item['hex'], '#F97316')
        self.assertIn(item['shape'], self.module.SHAPE_KEYS)

    def test_an_unknown_colour_degrades_to_a_persona_avatar(self):
        item = self.one('chartreuse')
        self.assertIsNone(item['hex'])
        self.assertEqual(item['color'], '')
        self.assertIn(item['shape'], self.module.SHAPE_KEYS)

    def test_persona_avatar_matches_the_app_byte_for_byte(self):
        # Expected values come from the app's own shippedHash/resolvePersonaShape,
        # run under node against packages/ui-web/src/bot-avatar.tsx. A drift here
        # means the bar draws a different avatar than Rakazo does.
        expected = [
            ('bot_cabc123', 'blob', 'red'),
            ('clx0a1b2c3d4e5f6', 'squircle', 'cyan'),
            ('77a1f0e2-0d5f-4a01-9b6c-111111111111', 'pebble', 'orange'),
            ('Chief of Staff', 'squircle', 'green'),
            ('a', 'pebble', 'yellow'),
            ('zzzzzzzzzzzzzzzzzzzzzzzzzzzz', 'squircle', 'violet'),
            ('8f14e45fceea167a5a36dedd4bea2543', 'hex', 'brown'),
        ]
        for identity, shape, colour in expected:
            self.assertEqual(self.module.persona_shape(identity), shape, identity)
            self.assertEqual(self.module.persona_color(identity), colour, identity)

    def test_an_uploaded_picture_is_cached_as_a_private_file(self):
        item = self.snapshot(bots=[bot(id='bot-9', color=PNG_URL)])['bots'][0]
        self.assertTrue(item['avatar'], 'the picture was not cached')
        picture = Path(item['avatar'])
        self.assertEqual(picture.read_bytes(), PNG)
        self.assertEqual(picture.stat().st_mode & 0o777, 0o600)
        self.assertEqual(picture.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(item['shape'], 'squircle', 'a picture is masked by a shape like the app does')

    def test_the_same_picture_twice_is_written_once(self):
        first = self.snapshot(bots=[bot(id='bot-9', color=PNG_URL)])['bots'][0]['avatar']
        second = self.snapshot(bots=[bot(id='bot-9', color=PNG_URL)])['bots'][0]['avatar']
        self.assertEqual(first, second)
        self.assertEqual(len(list(Path(self.module.CACHE).iterdir())), 1)
        self.assertFalse([name for name in os.listdir(self.module.CACHE) if name.startswith('.avatar-')],
                         'a temporary file was left behind')

    def test_an_oversized_picture_is_refused_and_falls_back_to_the_shape(self):
        huge = 'data:image/png;base64,' + base64.b64encode(b'x' * (2 * 1024 * 1024 + 1)).decode()
        item = self.snapshot(bots=[bot(color=huge)])['bots'][0]
        self.assertIsNone(item['avatar'])
        self.assertIn(item['shape'], self.module.SHAPE_KEYS)

    def test_a_picture_url_that_is_not_a_data_url_is_not_fetched(self):
        # `<img src="http://elsewhere/">` would leak the roster to a third party.
        item = self.snapshot(bots=[bot(color='http://example.invalid/tracker.png')])['bots'][0]
        self.assertIsNone(item['avatar'])

    def test_a_symlinked_cache_directory_is_refused(self):
        outside = self.home / 'outside'
        outside.mkdir()
        Path(self.module.CACHE).symlink_to(outside, target_is_directory=True)
        self.assertIsNone(self.module.store_avatar(PNG_URL))
        self.assertEqual(list(outside.iterdir()), [])

    def test_a_symlinked_cache_entry_is_not_served(self):
        target = self.home / 'private.png'
        target.write_bytes(b'private')
        Path(self.module.CACHE).mkdir()
        name = self.module.avatar_filename(PNG_URL)
        (Path(self.module.CACHE) / name).symlink_to(target)
        self.assertIsNone(self.module.store_avatar(PNG_URL))
        self.assertEqual(target.read_bytes(), b'private')

    def test_a_fifo_in_the_cache_does_not_hang_the_watcher(self):
        cache = Path(self.module.CACHE)
        cache.mkdir()
        os.mkfifo(cache / self.module.avatar_filename(PNG_URL))
        # Run in a child so a regression cannot hang the test process forever.
        # runpy hands back a copy of the globals on this interpreter, so the
        # function's own __globals__ is what has to carry the cache path.
        script = ('import runpy,sys;m=runpy.run_path(sys.argv[1]);'
                  'm["store_avatar"].__globals__["CACHE"]=sys.argv[2];'
                  'print(m["store_avatar"](sys.argv[3]))')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(WATCHER), str(cache), PNG_URL],
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(result.stdout.strip(), 'None')
        self.assertFalse([name for name in os.listdir(cache) if name.startswith('.avatar-')])

    def test_a_missing_cache_directory_is_created_private(self):
        cache = Path(self.module.CACHE)
        self.assertFalse(cache.exists())
        self.assertTrue(self.module.store_avatar(PNG_URL))
        self.assertEqual(cache.stat().st_mode & 0o777, 0o700)


class FailureTest(WatcherHarness):
    def test_a_rejected_token_is_said_plainly(self):
        self.server.mode = 'unauthorized'
        state = self.snapshot(bots=[bot()])
        self.assertFalse(state['app']['running'])
        self.assertIn('401', state['app']['error'])
        self.assertEqual(state['bots'], [])
        self.assertEqual(state['counts']['bots'], 0)

    def test_a_server_error_is_reported_without_crashing(self):
        self.server.mode = 'error'
        state = self.snapshot(bots=[bot()])
        self.assertFalse(state['app']['running'])
        self.assertIn('500', state['app']['error'])

    def test_a_reply_that_is_not_json_degrades(self):
        self.server.mode = 'garbage'
        state = self.snapshot(bots=[bot()])
        self.assertFalse(state['app']['running'])
        self.assertIn('JSON', state['app']['error'])

    def test_an_unreachable_server_is_not_an_exception(self):
        self.server.stop()
        state = self.module.snapshot(self.config())
        self.assertFalse(state['app']['running'])
        self.assertIn('cannot reach', state['app']['error'])

    def test_no_configuration_explains_itself(self):
        os.environ['RAKABOT_CONFIG'] = str(self.home / 'nothing.json')
        self.addCleanup(os.environ.pop, 'RAKABOT_CONFIG', None)
        state = self.module.snapshot(self.module.load_config())
        self.assertFalse(state['app']['running'])
        self.assertIn('no server configured', state['app']['error'])

    def test_a_missing_token_file_explains_itself(self):
        config = self.config()
        os.unlink(config['tokenFile'])
        state = self.module.snapshot(self.module.load_config())
        self.assertFalse(state['app']['running'])
        self.assertIn('no token configured', state['app']['error'])

    def test_a_malformed_bot_does_not_take_the_roster_down(self):
        state = self.snapshot(bots=['not a bot', bot(id='', name='nameless'),
                                    bot(id='bot-1', updatedAt=17, unread='yes')])
        self.assertEqual([item['id'] for item in state['bots']], ['bot-1'])
        self.assertEqual(state['bots'][0]['unread'], 0)
        self.assertEqual(state['bots'][0]['last_activity_ts'], 0.0)


class GroupTest(WatcherHarness):
    def group(self, **overrides):
        record = {'id': 'group-1', 'spaceId': 'space-1', 'name': 'Launch crew', 'pinned': False,
                  'sectionId': None, 'archivedAt': None, 'threadId': 'thread-g1',
                  'preview': 'We drafted the announcement.', 'unread': True,
                  'updatedAt': '2026-09-17T20:00:00.000Z', 'createdAt': '2026-09-02T09:00:00.000Z',
                  'members': [{'botId': 'bot-1', 'name': 'Chief of Staff', 'color': '#EF4444::shape_2'},
                              {'botId': 'bot-2', 'name': 'Release Notes', 'color': '#10B981::shape_1'}]}
        record.update(overrides)
        return record

    def test_a_group_is_drawn_as_a_cluster_of_its_members(self):
        state = self.snapshot(groups=[self.group()])
        item = state['bots'][0]
        self.assertTrue(item['is_group'])
        self.assertEqual(item['members'], 2)
        self.assertEqual(item['shape'], 'group')
        self.assertEqual(item['hex'], '#EF4444')
        self.assertEqual(item['unread'], 1)
        self.assertEqual(state['counts']['groups'], 1)

    def test_archived_groups_are_left_out(self):
        state = self.snapshot(groups=[self.group(archivedAt='2026-08-01T00:00:00.000Z')])
        self.assertEqual(state['bots'], [])

    def test_a_group_follows_its_section_like_a_bot(self):
        state = self.snapshot(groups=[self.group(sectionId='s1')],
                              sections=[{'id': 's1', 'name': 'ACME'}])
        self.assertEqual(state['sections'], [{'id': 's1', 'name': 'ACME', 'bot_ids': ['group-1']}])

    def test_a_group_without_members_still_renders(self):
        item = self.snapshot(groups=[self.group(members=[])])['bots'][0]
        self.assertEqual(item['members'], 0)
        self.assertIsNone(item['hex'])

    def test_bots_and_groups_share_one_roster(self):
        state = self.snapshot(bots=[bot()], groups=[self.group()])
        self.assertEqual([item['id'] for item in state['bots']], ['bot-1', 'group-1'])


class SignatureTest(WatcherHarness):
    def test_the_signature_changes_only_when_something_drawn_changes(self):
        first = self.snapshot(bots=[bot()])
        self.assertEqual(self.module.signature_of(first), self.module.signature_of(self.snapshot(bots=[bot()])))
        self.assertNotEqual(self.module.signature_of(first),
                            self.module.signature_of(self.snapshot(bots=[bot(unread=True)])))
        self.assertNotEqual(self.module.signature_of(first),
                            self.module.signature_of(self.snapshot(bots=[bot(status='waiting_input')])))

    def test_a_dead_server_is_a_different_signature(self):
        alive = self.snapshot(bots=[bot()])
        self.server.stop()
        dead = self.module.snapshot(self.config())
        self.assertNotEqual(self.module.signature_of(alive), self.module.signature_of(dead))


class CommandLineTest(WatcherHarness):
    def run_watcher(self, *arguments, **environment):
        env = dict(os.environ)
        env.update(environment)
        return subprocess.run([sys.executable, '-B', str(WATCHER), *arguments],
                              capture_output=True, text=True, timeout=30, env=env, check=False)

    def test_once_prints_one_snapshot_and_exits(self):
        self.config()
        self.server.bots = [bot(unread=True), bot(id='bot-2', status='waiting_input', preview='Need a decision')]
        result = self.run_watcher('--once')
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, 'expected exactly one snapshot line')
        state = json.loads(lines[0])
        self.assertTrue(state['app']['running'])
        self.assertEqual(state['counts'], {'bots': 2, 'awaiting': 1, 'working': 0, 'unread': 1,
                                           'unread_messages': 1, 'groups': 0})

    def test_once_without_configuration_still_prints_a_snapshot(self):
        os.environ['RAKABOT_CONFIG'] = str(self.home / 'absent.json')
        os.environ.pop('RAKABOT_TOKEN', None)
        result = self.run_watcher('--once')
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(state['app']['running'])
        self.assertEqual(state['bots'], [])

    def test_a_configuration_written_while_watching_is_picked_up(self):
        # The bar is already up when `rakabot-setup` runs, so a watcher that only
        # read its configuration at startup would leave the widget reporting "no
        # server configured" until the shell was restarted.
        config_file = self.home / 'config.json'
        token_file = self.home / 'token'
        environment = dict(os.environ, RAKABOT_CONFIG=str(config_file))
        environment.pop('RAKABOT_TOKEN', None)
        process = subprocess.Popen([sys.executable, '-B', str(WATCHER), '--interval', '1'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env=environment)
        try:
            first = json.loads(process.stdout.readline())
            self.assertFalse(first['app']['running'], 'nothing is configured yet')
            self.assertIn('no server configured', first['app']['error'])

            self.server.bots = [bot(name='Chief')]
            token_file.write_text('tok-123')
            config_file.write_text(json.dumps({'url': self.server.url, 'tokenFile': str(token_file)}))

            second = json.loads(process.stdout.readline())
            self.assertTrue(second['app']['running'], 'the new configuration was not picked up')
            self.assertEqual(second['counts']['bots'], 1)
        finally:
            process.terminate()
            process.wait(timeout=10)

    def test_the_stream_emits_again_when_the_roster_changes(self):
        self.config()
        self.server.bots = [bot()]
        process = subprocess.Popen([sys.executable, '-B', str(WATCHER), '--interval', '1'],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env=dict(os.environ))
        try:
            first = json.loads(process.stdout.readline())
            self.assertEqual(first['counts']['bots'], 1)
            self.server.bots = [bot(), bot(id='bot-2', status='waiting_input')]
            second = json.loads(process.stdout.readline())
            self.assertEqual(second['counts']['bots'], 2)
            self.assertEqual(second['counts']['awaiting'], 1)
        finally:
            process.terminate()
            process.wait(timeout=10)


class ApiParityTest(unittest.TestCase):
    """Guards the assumptions this plugin makes about Rakazo's own contracts."""

    def test_shape_keys_match_the_shipped_order(self):
        self.assertEqual(load_watcher().SHAPE_KEYS,
                         ['hex', 'wedge', 'squircle', 'tablet', 'pebble', 'blob', 'teardrop', 'cloud'])

    def test_palette_hexes_are_the_shipped_palette(self):
        self.assertEqual(load_watcher().COLORS, {
            'white': '#FFFFFF', 'violet': '#8B5CF6', 'green': '#10B981', 'orange': '#F97316',
            'cyan': '#06B6D4', 'blue': '#3B82F6', 'yellow': '#EAB308', 'brown': '#8D6E63',
            'red': '#EF4444', 'magenta': '#EC4899', 'gray': '#64748B'})


if __name__ == '__main__':
    unittest.main()
