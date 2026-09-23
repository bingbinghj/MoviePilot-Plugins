import importlib.util
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class _Event:
    def __init__(self, event_type, event_data=None):
        self.event_type = event_type
        self.event_data = event_data or {}


class _MediaChain:
    def scrape_metadata_event(self, event):
        return None


class _TransferChain:
    jobs = []

    def get_queue_tasks(self):
        return self.jobs


class _PluginBase:
    pass


class _EventType:
    MetadataScrape = "metadata.scrape"


class _RequestUtils:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _RotatingHandler:
    maxBytes = 0
    backupCount = 0


class _FileHandler:
    handler = _RotatingHandler()

    @classmethod
    def _get_rotating_handler(cls, file_path):
        return cls.handler


class _LoggerManager:
    _file_handler = _FileHandler()


class _EventManager:
    def __init__(self):
        self.listeners = []
        self.disabled = []
        self.enabled = []

    def add_event_listener(self, event_type, handler):
        self.listeners.append((event_type, handler))

    def remove_event_listener(self, event_type, handler):
        self.listeners = [item for item in self.listeners if item != (event_type, handler)]

    def disable_event_handler(self, handler):
        self.disabled.append(handler)

    def enable_event_handler(self, handler):
        self.enabled.append(handler)


EVENT_MANAGER = _EventManager()


def _install_moviepilot_stubs():
    modules = {
        "app": types.ModuleType("app"),
        "app.chain": types.ModuleType("app.chain"),
        "app.chain.media": types.ModuleType("app.chain.media"),
        "app.chain.transfer": types.ModuleType("app.chain.transfer"),
        "app.core": types.ModuleType("app.core"),
        "app.core.config": types.ModuleType("app.core.config"),
        "app.core.event": types.ModuleType("app.core.event"),
        "app.log": types.ModuleType("app.log"),
        "app.plugins": types.ModuleType("app.plugins"),
        "app.schemas": types.ModuleType("app.schemas"),
        "app.schemas.types": types.ModuleType("app.schemas.types"),
        "app.utils": types.ModuleType("app.utils"),
        "app.utils.http": types.ModuleType("app.utils.http"),
    }
    modules["app.chain.media"].MediaChain = _MediaChain
    modules["app.chain.transfer"].TransferChain = _TransferChain
    modules["app.core.config"].settings = types.SimpleNamespace(
        RMT_MEDIAEXT={".strm", ".mkv", ".mp4"},
        LOG_PATH=Path("."),
    )
    modules["app.core.event"].Event = _Event
    modules["app.core.event"].eventmanager = EVENT_MANAGER
    modules["app.log"].logger = types.SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    modules["app.log"].LoggerManager = _LoggerManager
    modules["app.plugins"]._PluginBase = _PluginBase
    modules["app.schemas.types"].EventType = _EventType
    modules["app.utils.http"].RequestUtils = _RequestUtils
    sys.modules.update(modules)


_install_moviepilot_stubs()
MODULE_PATH = Path(__file__).parents[1] / os.environ.get("PLUGIN_TREE", "plugins.v2") / "etkscrapewebhook" / "__init__.py"
SPEC = importlib.util.spec_from_file_location("etkscrapewebhook_under_test", MODULE_PATH)
PLUGIN_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN_MODULE)


class ETKScrapeWebhookTests(unittest.TestCase):
    def setUp(self):
        self.log_dir = tempfile.TemporaryDirectory()
        PLUGIN_MODULE.settings.LOG_PATH = Path(self.log_dir.name)
        self.plugin = PLUGIN_MODULE.ETKScrapeWebhook()
        self.plugin._enabled = True
        plugin_class = type(self.plugin)
        plugin_class._pending.clear()
        plugin_class._original_scrape_handler = _MediaChain.scrape_metadata_event
        plugin_class._listener_installed = False
        EVENT_MANAGER.listeners.clear()
        EVENT_MANAGER.disabled.clear()
        EVENT_MANAGER.enabled.clear()
        _FileHandler.handler.maxBytes = 0
        _FileHandler.handler.backupCount = 0
        self.original_calls = []
        self.webhook_payloads = []
        _TransferChain.jobs = []

        def original(chain, event):
            self.original_calls.append(event.event_data)

        plugin_class._original_scrape_handler = original
        self.plugin._send_webhook = self.webhook_payloads.append

    def tearDown(self):
        plugin_class = type(self.plugin)
        with plugin_class._lock:
            for pending in plugin_class._pending.values():
                timer = pending.get("timer")
                if timer:
                    timer.cancel()
            plugin_class._pending.clear()
            plugin_class._original_scrape_handler = None
            plugin_class._listener_installed = False
        self.log_dir.cleanup()

    def test_same_root_requests_are_merged_and_notified_once(self):
        fileitem = {"storage": "local", "path": "/media/Series"}
        first = _Event(_EventType.MetadataScrape, {"fileitem": fileitem, "file_list": []})
        second = _Event(_EventType.MetadataScrape, {"fileitem": fileitem, "file_list": []})

        self.plugin._enqueue_scrape(first)
        self.plugin._enqueue_scrape(second)

        plugin_class = type(self.plugin)
        with plugin_class._lock:
            self.assertEqual(len(plugin_class._pending), 1)
            key, pending = next(iter(plugin_class._pending.items()))
            self.assertIsInstance(pending["timer"], threading.Timer)
            pending["timer"].cancel()

        with tempfile.TemporaryDirectory() as temp_dir:
            nfo_path = os.path.join(temp_dir, "tvshow.nfo")
            with open(nfo_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("<tvshow />")
            pending["event_data"]["fileitem"]["path"] = temp_dir
            self.plugin._flush_scrape(key)

        self.assertEqual(len(self.original_calls), 1)
        self.assertEqual(len(self.webhook_payloads), 1)
        self.assertTrue(self.webhook_payloads[0]["success"])
        self.assertEqual(self.webhook_payloads[0]["root_path"], temp_dir)
        self.assertTrue(self.webhook_payloads[0]["full_scan"])

    @patch.object(PLUGIN_MODULE.threading, "Timer")
    def test_slow_51_episode_transfer_waits_for_whole_job(self, timer):
        tasks = [{"state": "waiting"} for _ in range(51)]
        _TransferChain.jobs = [{"media": {"tmdb_id": 85995, "type": "电视剧"}, "tasks": tasks}]
        event_data = {
            "fileitem": {"storage": "local", "path": "/media/铁甲小宝"},
            "mediainfo": {"tmdb_id": 85995, "type": "电视剧"},
        }
        with patch.object(self.plugin, "_verify_scrape_outputs", return_value=(True, "")):
            for index in range(51):
                tasks[index]["state"] = "running"
                self.plugin._enqueue_scrape(_Event(_EventType.MetadataScrape, {
                    **event_data, "file_list": [f"/media/铁甲小宝/S01E{index + 1:02d}.strm"],
                }))
                key = self.plugin._event_key(event_data)
                # 模拟 22～38 秒的逐集间隔：10 秒计时器在下一集到达前已经触发。
                self.plugin._flush_scrape(key)
                self.assertEqual(self.original_calls, [])
                self.assertEqual(self.webhook_payloads, [])
                tasks[index]["state"] = "completed"
            self.plugin._flush_scrape(key)

        self.assertEqual(len(self.original_calls), 1)
        self.assertEqual(len(self.original_calls[0]["file_list"]), 51)
        self.assertEqual(len(self.webhook_payloads), 1)

    @patch.object(PLUGIN_MODULE.threading, "Timer")
    def test_finished_failed_and_other_media_jobs_do_not_block(self, timer):
        _TransferChain.jobs = [
            {"media": {"tmdb_id": 1, "type": "电视剧"}, "tasks": [{"state": "completed"}, {"state": "failed"}]},
            {"media": {"tmdb_id": 2, "type": "电视剧"}, "tasks": [{"state": "running"}]},
            {"media": {"tmdb_id": 1, "type": "电影"}, "tasks": [{"state": "running"}]},
        ]
        event_data = {"fileitem": {"path": "/media/Show"}, "mediainfo": {"tmdb_id": 1, "type": "电视剧"}}
        self.plugin._enqueue_scrape(_Event(_EventType.MetadataScrape, event_data))
        with patch.object(self.plugin, "_verify_scrape_outputs", return_value=(True, "")):
            self.plugin._flush_scrape(self.plugin._event_key(event_data))
        self.assertEqual(len(self.webhook_payloads), 1)

    @patch.object(PLUGIN_MODULE.threading, "Timer")
    def test_cancelled_timer_cannot_flush_replaced_batch(self, timer):
        event = _Event(_EventType.MetadataScrape, {"fileitem": {"path": "/media/Show"}})
        self.plugin._enqueue_scrape(event)
        key = self.plugin._event_key(event.event_data)
        old_token = type(self.plugin)._pending[key]["token"]
        self.plugin._enqueue_scrape(event)
        self.plugin._flush_scrape(key, old_token)
        self.assertEqual(self.original_calls, [])
        self.assertIn(key, type(self.plugin)._pending)

    @patch.object(PLUGIN_MODULE.threading, "Timer")
    @patch.object(_TransferChain, "get_queue_tasks", side_effect=RuntimeError("temporarily unavailable"))
    def test_transfer_state_error_keeps_batch_pending(self, jobs, timer):
        data = {"fileitem": {"path": "/media/Show"}, "mediainfo": {"tmdb_id": 1, "type": "电视剧"}}
        self.plugin._enqueue_scrape(_Event(_EventType.MetadataScrape, data))
        key = self.plugin._event_key(data)
        self.plugin._flush_scrape(key)
        self.assertEqual(self.webhook_payloads, [])
        self.assertIn(key, type(self.plugin)._pending)

    @patch.object(PLUGIN_MODULE.threading, "Timer")
    def test_requests_arriving_during_scrape_wait_and_notify_combined_files(self, timer):
        event_data = {"fileitem": {"path": "/media/Show"}, "file_list": ["/media/Show/E1.strm"]}
        key = self.plugin._event_key(event_data)
        def original(chain, event):
            self.original_calls.append(event.event_data)
            if len(self.original_calls) == 1:
                self.plugin._enqueue_scrape(_Event(_EventType.MetadataScrape, {
                    **event_data, "file_list": ["/media/Show/E2.strm"],
                }))
                self.plugin._flush_scrape(key)
        type(self.plugin)._original_scrape_handler = original
        self.plugin._enqueue_scrape(_Event(_EventType.MetadataScrape, event_data))
        with patch.object(self.plugin, "_verify_scrape_outputs", return_value=(True, "")):
            self.plugin._flush_scrape(key)
            self.assertEqual(self.webhook_payloads, [])
            self.assertEqual(len(self.original_calls), 1)
            self.plugin._flush_scrape(key)
        self.assertEqual(len(self.webhook_payloads), 1)
        self.assertEqual(self.webhook_payloads[0]["file_list"], ["/media/Show/E1.strm", "/media/Show/E2.strm"])

    def test_listener_replaces_and_restores_original_handler(self):
        self.plugin._install_listener()

        self.assertEqual(EVENT_MANAGER.disabled, [_MediaChain.scrape_metadata_event])
        self.assertEqual(len(EVENT_MANAGER.listeners), 1)

        self.plugin.stop_service()

        self.assertEqual(EVENT_MANAGER.listeners, [])
        self.assertEqual(EVENT_MANAGER.enabled, [_MediaChain.scrape_metadata_event])

    def test_payload_includes_explicit_moviepilot_episode_group(self):
        payload = self.plugin._build_payload(
            event_data={
                "fileitem": {"storage": "local", "path": "/media/Series"},
                "mediainfo": {"type": "TV", "tmdb_id": 1, "episode_group": "group-id"},
                "file_list": [],
            },
            batch_id="batch-1",
            success=True,
            error="",
            duration=1.0,
        )

        self.assertEqual(payload["episode_group"], "group-id")

    def test_payload_uses_empty_episode_group_for_official_seasons(self):
        payload = self.plugin._build_payload(
            event_data={
                "fileitem": {"storage": "local", "path": "/media/Series"},
                "mediainfo": {"type": "TV", "tmdb_id": 1},
                "file_list": [],
            },
            batch_id="batch-1",
            success=True,
            error="",
            duration=1.0,
        )

        self.assertEqual(payload["episode_group"], "")

    def test_precise_files_and_episode_group_survive_empty_duplicate_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "Show.S02E01.strm")
            with open(media_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("https://example.invalid/video.mkv")
            with open(os.path.splitext(media_path)[0] + ".nfo", "w", encoding="utf-8") as file_obj:
                file_obj.write("<episodedetails />")

            fileitem = {"storage": "local", "path": temp_dir}
            self.plugin._enqueue_scrape(_Event(
                _EventType.MetadataScrape,
                {
                    "fileitem": fileitem,
                    "mediainfo": {"type": "TV", "tmdb_id": 1, "episode_group": "group-id"},
                    "file_list": [media_path],
                },
            ))
            self.plugin._enqueue_scrape(_Event(
                _EventType.MetadataScrape,
                {
                    "fileitem": fileitem,
                    "mediainfo": {"type": "TV", "tmdb_id": 1},
                    "file_list": [],
                },
            ))

            plugin_class = type(self.plugin)
            with plugin_class._lock:
                key, pending = next(iter(plugin_class._pending.items()))
                pending["timer"].cancel()
            self.plugin._flush_scrape(key)

        self.assertEqual(self.original_calls[0]["file_list"], [media_path])
        self.assertFalse(self.webhook_payloads[0]["full_scan"])
        self.assertEqual(self.webhook_payloads[0]["episode_group"], "group-id")

    def test_no_moviepilot_nfo_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            event = _Event(
                _EventType.MetadataScrape,
                {"fileitem": {"storage": "local", "path": temp_dir}, "file_list": []},
            )
            self.plugin._enqueue_scrape(event)
            plugin_class = type(self.plugin)
            with plugin_class._lock:
                key, pending = next(iter(plugin_class._pending.items()))
                pending["timer"].cancel()

            self.plugin._flush_scrape(key)

        self.assertEqual(len(self.webhook_payloads), 1)
        self.assertFalse(self.webhook_payloads[0]["success"])
        self.assertIn("未找到NFO", self.webhook_payloads[0]["error"])

    def test_incomplete_strm_nfo_reports_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for episode in (1, 2):
                with open(os.path.join(temp_dir, f"Show.S01E{episode:02d}.strm"), "w", encoding="utf-8") as file_obj:
                    file_obj.write("https://example.invalid/video.mkv")
            with open(os.path.join(temp_dir, "Show.S01E01.nfo"), "w", encoding="utf-8") as file_obj:
                file_obj.write("<episodedetails />")

            success, error = self.plugin._verify_scrape_outputs(
                {"fileitem": {"storage": "local", "path": temp_dir}, "file_list": []}
            )

        self.assertFalse(success)
        self.assertIn("1/2", error)

    def test_non_media_file_list_entries_do_not_require_nfo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = os.path.join(temp_dir, "Show.S01E01.strm")
            subtitle_path = os.path.join(temp_dir, "Show.S01E01.zh.srt")
            with open(media_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("https://example.invalid/video.mkv")
            with open(subtitle_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("1\n00:00:00,000 --> 00:00:01,000\nsubtitle")
            with open(os.path.splitext(media_path)[0] + ".nfo", "w", encoding="utf-8") as file_obj:
                file_obj.write("<episodedetails />")

            success, error = self.plugin._verify_scrape_outputs(
                {
                    "fileitem": {"storage": "local", "path": temp_dir},
                    "file_list": [media_path, subtitle_path],
                }
            )

        self.assertTrue(success, error)

    def test_plugin_log_rotation_keeps_ten_backups(self):
        plugin_log = self.plugin._plugin_log_path()
        plugin_log.parent.mkdir(parents=True)
        for index in range(1, 12):
            backup = Path(f"{plugin_log}.{index}")
            backup.write_text(str(index), encoding="utf-8")
            os.utime(backup, (index, index))

        self.plugin._configure_plugin_log_rotation()

        self.assertEqual(_FileHandler.handler.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(_FileHandler.handler.backupCount, 10)
        self.assertEqual(len(list(plugin_log.parent.glob(f"{plugin_log.name}.*"))), 10)


if __name__ == "__main__":
    unittest.main()
