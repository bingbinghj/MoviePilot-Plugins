"""使用真实 MoviePilot v3 SDK、临时 SQLite 和媒体 DTO；外部服务调用均隔离。"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get('MOVIEPILOT_BACKEND', '/app'))
from app.testing.bootstrap import prepare_v3_backend
prepare_v3_backend(REPO)

from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.sdk.media import MediaInfo, MusicInfo
from app.sdk.plugin import _PluginBase
from app.schemas.file import FileItem
from app.schemas.context import MediaInfo as MediaDTO
from app.schemas.transfer import TransferJob, TransferJobTask
from app.schemas.types import EventType, MediaSource, MediaType

NAMES = ['TemoxSignin', 'NewApiCheckin', 'RedisAutoRestart', 'HeyboxSignin', 'ETKScrapeWebhook']
MODULES = {name: importlib.import_module(f'app.plugins.{name.lower()}') for name in NAMES}
CLASSES = {name: getattr(module, name) for name, module in MODULES.items()}
ETK = MODULES['ETKScrapeWebhook']
CHAIN_PATCH = patch('app.sdk.plugin.base.PluginChain', return_value=Mock())


def setUpModule():
    # SDK/数据库真实运行，通知与模块调度不启动外部宿主服务。
    CHAIN_PATCH.start()


def tearDownModule():
    CHAIN_PATCH.stop()


class PluginHostContractTests(unittest.TestCase):
    def test_all_five_market_entries_match_native_classes(self):
        manifest = json.loads((REPO / 'package.v3.json').read_text())
        self.assertEqual(set(manifest), set(NAMES))
        for name in NAMES:
            with self.subTest(plugin=name):
                self.assertTrue(issubclass(CLASSES[name], _PluginBase))
                self.assertEqual(manifest[name]['version'], CLASSES[name].plugin_version)
                self.assertEqual(manifest[name]['system_version'], '>=3.0.0')

    def test_v3_market_selects_native_packages_and_rejects_legacy_fallback(self):
        from app.adapters.external.plugin.client import PluginMarketTransport
        manifest = json.loads((REPO / 'package.v3.json').read_text())
        with patch('app.adapters.external.plugin.client.get_runtime_setting', return_value='v3'):
            self.assertEqual(PluginMarketTransport._package_version_candidates('v3')[0], 'v3')
            for name in NAMES:
                self.assertTrue(PluginMarketTransport.is_package_plugin_compatible(manifest[name], 'v3'))
                for filename, generation in [('package.json', ''), ('package.v2.json', 'v2')]:
                    old = json.loads((REPO / filename).read_text())[name]
                    self.assertFalse(PluginMarketTransport.is_package_plugin_compatible(old, generation))

    def test_all_five_forms_pages_and_persistent_config(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                form, defaults = plugin.get_form()
                config = {**defaults, 'enabled': False, 'onlyonce': False, 'notify': False}
                plugin.update_config(config)
                plugin.init_plugin(plugin.get_config())
                self.assertFalse(plugin.get_state())
                self.assertIsInstance(form, list)
                self.assertIsInstance(defaults, dict)
                self.assertTrue(plugin.get_page() is None or isinstance(plugin.get_page(), list))
                plugin.save_data('v3_contract_test', {'name': name})
                self.assertEqual(plugin.get_data('v3_contract_test'), {'name': name})
                plugin.stop_service()

    def test_four_scheduled_plugins_register_working_cron_and_api(self):
        for name in NAMES[:-1]:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                plugin.init_plugin({'enabled': True, 'notify': False})
                services = plugin.get_service()
                self.assertEqual(len(services), 1)
                self.assertTrue(callable(services[0]['func']))
                self.assertTrue(hasattr(services[0]['trigger'], 'get_next_fire_time'))
                api = plugin.get_api()[0]
                self.assertEqual(api['methods'], ['POST'])
                self.assertEqual(api['auth'], 'bear')
                self.assertTrue(callable(api['endpoint']))
                plugin.stop_service()

    def test_manual_commands_dispatch_and_ignore_other_actions(self):
        for name, remote, action in [
            ('TemoxSignin', 'remote_signin', 'signin'),
            ('NewApiCheckin', 'remote_checkin', 'checkin'),
            ('RedisAutoRestart', 'remote_check', 'check'),
            ('HeyboxSignin', 'remote_signin', 'signin'),
        ]:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                with patch.object(plugin, action) as execute:
                    getattr(plugin, remote)(Event(EventType.PluginAction, plugin.get_command()[0]['data']))
                    execute.assert_called_once_with(manual=True)
                    getattr(plugin, remote)(Event(EventType.PluginAction, {'action': 'unrelated'}))
                    self.assertEqual(execute.call_count, 1)

    def test_run_once_is_persistently_reset_for_four_plugins(self):
        for name, action in [('TemoxSignin', 'signin'), ('NewApiCheckin', 'checkin'),
                             ('RedisAutoRestart', 'check'), ('HeyboxSignin', 'signin')]:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                with patch.object(plugin, action) as execute:
                    plugin.init_plugin({'onlyonce': True, 'notify': False})
                    execute.assert_called_once_with(manual=True)
                self.assertFalse(plugin.get_config()['onlyonce'])


class ETKV3Tests(unittest.TestCase):
    def setUp(self):
        self.plugin = ETK.ETKScrapeWebhook()
        self.plugin._enabled = True
        self.plugin._send_webhook = Mock()
        chain_patch = patch.object(ETK, 'TransferChain')
        self.chain = chain_patch.start()
        self.addCleanup(chain_patch.stop)
        self.chain.return_value.get_queue_tasks.return_value = []
        for patcher in (patch.object(ETK.threading, 'Timer'),
                        patch.object(ETK.ScrapingChain, '__init__', return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.original = Mock()
        type(self.plugin)._original_scrape_handler = self.original

    def tearDown(self):
        self.plugin.stop_service()

    def event_data(self, path='/tmp/Show', source=MediaSource.TMDB, media_id='85995'):
        return {
            'fileitem': FileItem(storage='local', path=path, type='dir', name='Show'),
            'mediainfo': MediaInfo(media_source=source, media_id=media_id, type=MediaType.TV),
            'file_list': [],
        }

    def test_native_identity_generates_tmdb_payload_and_episode_group(self):
        data = self.event_data()
        data['mediainfo'].episode_group = 'selected-group'
        payload = self.plugin._build_payload(event_data=data, batch_id='batch', success=True, error='', duration=1)
        self.assertEqual(payload['tmdb_id'], '85995')
        self.assertEqual(payload['media_type'], '电视剧')
        self.assertEqual(payload['episode_group'], 'selected-group')

    def test_different_source_with_same_number_is_not_same_transfer(self):
        data = self.event_data()
        job = TransferJob(media=MediaDTO(media_source=MediaSource.Douban, media_id='85995', type='电视剧'),
                          tasks=[TransferJobTask(state='running')])
        self.chain.return_value.get_queue_tasks.return_value = [job]
        self.assertFalse(self.plugin._has_pending_transfer(data))
        job.media.media_source = MediaSource.TMDB
        self.assertTrue(self.plugin._has_pending_transfer(data))

    def test_slow_51_file_job_only_notifies_when_all_transfers_finish(self):
        data = self.event_data()
        job = TransferJob(media=MediaDTO(media_source=MediaSource.TMDB, media_id='85995', type='电视剧'),
                          tasks=[TransferJobTask(state='waiting') for _ in range(51)])
        self.chain.return_value.get_queue_tasks.return_value = [job]
        with patch.object(self.plugin, '_verify_scrape_outputs', return_value=(True, '')):
            for index, task in enumerate(job.tasks):
                task.state = 'running'
                self.plugin._handle_scrape_event(Event(EventType.MetadataScrape, {
                    **data, 'file_list': [f'/tmp/Show/E{index}.strm'],
                }))
                key = self.plugin._event_key(data)
                self.plugin._flush_scrape(key)
                self.original.assert_not_called()
                task.state = 'completed'
            self.plugin._flush_scrape(key)
        self.original.assert_called_once()
        self.plugin._send_webhook.assert_called_once()
        self.assertEqual(len(self.plugin._send_webhook.call_args.args[0]['file_list']), 51)

    def test_music_and_non_tmdb_media_keep_native_scraping(self):
        for media in [MusicInfo(media_source=MediaSource.MusicBrainz, media_id='music-id'),
                      MediaInfo(media_source=MediaSource.Douban, media_id='123', type=MediaType.TV)]:
            with self.subTest(media_type=media.type):
                event = Event(EventType.MetadataScrape, {**self.event_data(), 'mediainfo': media})
                self.plugin._handle_scrape_event(event)
        self.assertEqual(self.original.call_count, 2)
        self.plugin._send_webhook.assert_not_called()

    def test_late_music_event_after_stop_does_not_call_cleared_handler(self):
        event = Event(EventType.MetadataScrape, {
            **self.event_data(),
            'mediainfo': MusicInfo(media_source=MediaSource.MusicBrainz, media_id='music-id'),
        })
        self.plugin.stop_service()
        self.assertIsNone(self.plugin._handle_scrape_event(event))
        self.original.assert_not_called()

    def test_listener_replaces_and_restores_real_scraping_chain(self):
        self.plugin._install_listener()
        handlers = eventmanager.visualize_handlers()
        native = [row for row in handlers if 'ScrapingChain.scrape_metadata_event' in str(row)]
        self.assertTrue(native)
        self.assertTrue(all(row['status'] == 'disabled' for row in native))
        self.plugin.stop_service()
        self.assertFalse(type(self.plugin)._listener_installed)
        native = [row for row in eventmanager.visualize_handlers()
                  if 'ScrapingChain.scrape_metadata_event' in row['handler_identifier']]
        self.assertTrue(all(row['status'] == 'enabled' for row in native))

    def test_enabled_plugin_initialization_uses_v3_logger_and_listener(self):
        with patch.object(ETK.LoggerManager, 'current_writer', return_value=None):
            self.plugin.init_plugin({'enabled': True, 'webhook_url': 'http://etk.invalid/webhook/moviepilot', 'secret': 'test'})
        self.assertTrue(self.plugin.get_state())
        self.assertTrue(type(self.plugin)._listener_installed)
        self.assertIs(type(self.plugin)._original_scrape_handler, ETK.ScrapingChain.scrape_metadata_event)

    def test_v3_log_writer_rotation_and_missing_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(type(self.plugin), '_plugin_log_path', return_value=Path(directory) / 'etk.log'):
                writer = Mock()
                handler = writer._get_rotating_handler.return_value
                with patch.object(ETK.LoggerManager, 'current_writer', return_value=writer):
                    self.plugin._configure_plugin_log_rotation()
                self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
                self.assertEqual(handler.backupCount, 10)
                with patch.object(ETK.LoggerManager, 'current_writer', return_value=None):
                    self.plugin._configure_plugin_log_rotation()


class BrowserAndRedisV3Tests(unittest.TestCase):
    def test_browser_sdk_releases_context_on_success_and_failure(self):
        module = MODULES['NewApiCheckin']
        plugin = CLASSES['NewApiCheckin']()
        for fail in (False, True):
            with self.subTest(failure=fail):
                context = Mock()
                page = context.new_page.return_value
                page.context = context
                page.content.return_value = '<html>signed in</html>'
                page.evaluate.return_value = 'signed in'
                page.title.return_value = 'site'
                page.url = 'https://example.invalid/console'
                page.goto.return_value.status = 200
                context.cookies.return_value = [{'name': 'session', 'value': 'test'}]
                if fail:
                    page.goto.side_effect = RuntimeError('navigation failed')
                with patch.object(module, 'launch_browser_context', return_value=context) as launch:
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'navigation failed'):
                            plugin._NewApiCheckin__run_browser_action(page.url, [], {}, 1)
                    else:
                        result = plugin._NewApiCheckin__run_browser_action(page.url, [], {}, 1)
                        self.assertEqual(result['status'], 200)
                        self.assertEqual(result['text'], 'signed in')
                    launch.assert_called_once_with(headless=True)
                context.close.assert_called_once()

    def test_redis_reads_v3_backend_url_only_when_selected(self):
        plugin = CLASSES['RedisAutoRestart']()
        with patch.object(settings, 'CACHE_BACKEND_TYPE', 'redis'), \
             patch.object(settings, 'CACHE_BACKEND_URL', 'redis://cache.example:6380/2'):
            self.assertEqual(plugin._RedisAutoRestart__settings_redis_url(), 'redis://cache.example:6380/2')
        with patch.object(settings, 'CACHE_BACKEND_TYPE', 'cachetools'), \
             patch.object(settings, 'CACHE_BACKEND_URL', 'redis://localhost:6379'):
            self.assertEqual(plugin._RedisAutoRestart__settings_redis_url(), '')
            result = plugin._RedisAutoRestart__check_redis()
            self.assertFalse(result['failed'])
            self.assertTrue(result['inconclusive'])


if __name__ == '__main__':
    unittest.main()
