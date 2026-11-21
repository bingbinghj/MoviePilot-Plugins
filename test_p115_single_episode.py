"""Exercise 115 transfer checkpoints, MP scrape dispatch and ETK file scope together."""
import importlib.util
import os
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_etk_wash import Event, load_plugin

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "plugins.v3/p115strmhelper/tests"))
import test_v3_transfer_strm as transfer_fixture
from test_v3_share_queue_lifecycle import _method


class SingleEpisodeTests(unittest.TestCase):
    def setUp(self):
        self.case = transfer_fixture.TestV3TransferStrm()
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        case = self.case
        case.config.transfer_monitor_paths = f"{case.library}#/cloud"
        self.season = case.library / "Example" / "Season 01"
        self.season.mkdir(parents=True)
        self.old_files = {}
        for episode in (199, 200, 203):
            video = self.season / f"Example.S01E{episode}.strm"
            video.write_text(f"https://example.invalid/old/{episode}")
            video.with_suffix(".nfo").write_text("<episodedetails><title>original</title></episodedetails>")
            for path in (video, video.with_suffix(".nfo")):
                self.old_files[path] = (path.read_bytes(), path.stat().st_mtime_ns)

        settings = sys.modules["app.sdk.config"].settings
        settings.TV_RENAME_FORMAT = "{{title}}/Season {{season}}/{{title}}"
        identity = __import__("app.schemas.media", fromlist=["resolve_media_identity"])
        self.addCleanup(patch.stopall)
        patch.object(sys.modules["app.sdk.media"], "resolve_media_identity",
                     identity.resolve_media_identity, create=True).start()
        media_chain = types.ModuleType("app.chain.media")
        media_chain.MediaChain = MagicMock()
        patch.dict(sys.modules, {"app.chain.media": media_chain}).start()
        spec = importlib.util.spec_from_file_location(
            "p115_real_scrape", ROOT / "plugins.v3/p115strmhelper/core/scrape.py")
        self.scrape = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.scrape)
        case.module.media_scrape_metadata = self.scrape.media_scrape_metadata

        self.etk_module = load_plugin("plugins.v3")
        self.plugin = self.etk_module.ETKScrapeWebhook()
        self.plugin._enabled = True
        self.plugin._schedule_scrape = lambda *args: None
        self.plugin._has_pending_transfer = lambda *args: False
        self.payloads = []
        self.plugin._send_webhook = self.payloads.append
        self.requests = []
        self.scrape.eventmanager.send_event.side_effect = self._enqueue
        self.processed = []

        def local_item(storage, path):
            path = Path(path)
            return case.file_type(storage=storage, type="dir" if path.is_dir() else "file",
                                  path=str(path), name=path.name) if path.exists() else None

        def scrape_file(**kwargs):
            path = Path(kwargs["fileitem"].path)
            files = path.rglob("*.strm") if path.is_dir() and kwargs.get("recursive", True) else [path]
            for file in files:
                if file.is_file():
                    self.processed.append(str(file))
                    file.with_suffix(".nfo").write_text("<episodedetails/>")

        host = Path(os.environ["MOVIEPILOT_SOURCE"])
        handler = _method(host / "app/chain/scraping.py", "scrape_metadata_event", {
            "Path": Path, "_SchemaFileItem": case.file_type, "MediaType": case.types.MediaType,
            "MetaInfo": self.etk_module.MetaInfo, "scraping_lock": threading.RLock(),
            "logger": case.logger,
        })
        chain = types.SimpleNamespace(
            storagechain=types.SimpleNamespace(
                get_item=lambda item: local_item(item.storage, item.path),
                get_file_item=local_item, is_bluray_folder=lambda item: False,
                get_parent_item=lambda item: local_item(item.storage, Path(item.path).parent)),
            runtime_config=types.SimpleNamespace(season_zero_names=()),
            scrape_metadata=scrape_file,
        )
        cls = type(self.plugin)
        cls._original_scrape_handler = staticmethod(lambda _, event: handler(chain, event))

    def _enqueue(self, kind, data):
        self.requests.append(data)
        self.plugin._enqueue_scrape(Event(kind, data))

    def _item(self, episode):
        name = f"Example.S01E{episode}.mkv"
        self.case.meta = self.case.module.MetaInfoPath(Path(name))
        return self.case._item(name)

    def _flush(self, episodes):
        for key in list(type(self.plugin)._pending):
            self.plugin._flush_scrape(key)
        expected = [str(self.season / f"Example.S01E{episode}.strm") for episode in episodes]
        self.assertEqual(len(self.payloads), 1)
        self.assertTrue(self.payloads[0]["success"], self.payloads[0])
        self.assertIs(self.payloads[0]["full_scan"], False)
        self.assertEqual(self.payloads[0]["file_list"], expected)
        self.assertEqual(self.processed, expected)
        for path, original in self.old_files.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_episode_201_and_replay_after_restart(self):
        item = self._item(201)
        self.case._run(item)
        self.case.helper = self.case.module.TransferStrmHelper()
        replay = self.case.durable.restore_transfer_result(self.case.durable.snapshot_transfer_result(item))
        self.case._run(replay)
        self.assertEqual(len(self.requests), 1)
        self._flush([201])

    def test_batch_merges_only_transferred_episodes(self):
        for episode in (201, 202, 201):
            self.case._run(self._item(episode))
        self.assertEqual(len(self.requests), 2)
        self._flush([201, 202])

    def test_failed_dispatch_retries_only_episode_201(self):
        item = self._item(201)
        self.scrape.eventmanager.send_event.side_effect = RuntimeError("dispatch unavailable")
        with self.assertRaisesRegex(RuntimeError, "dispatch unavailable"):
            self.case._run(item)
        self.scrape.eventmanager.send_event.side_effect = self._enqueue
        self.case.helper = self.case.module.TransferStrmHelper()
        self.case._run(item)
        self.assertEqual(len(self.requests), 1)
        self._flush([201])


if __name__ == "__main__":
    unittest.main()
