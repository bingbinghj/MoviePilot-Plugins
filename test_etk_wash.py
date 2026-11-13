"""Run the three published plugin variants against real temporary media/NFO files."""
import importlib.util
import sys
import tempfile
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent


class Event:
    def __init__(self, kind, data):
        self.event_data = data


class Manager:
    def register(self, kind):
        return lambda function: function

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class Timer:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def cancel(self):
        pass


def load_plugin(tree):
    names = (
        "app", "app.chain", "app.chain.media", "app.chain.scraping", "app.chain.transfer",
        "app.core", "app.core.config", "app.core.event", "app.core.metainfo", "app.log",
        "app.plugins", "app.schemas", "app.schemas.types", "app.utils", "app.utils.http",
        "app.sdk", "app.sdk.config", "app.sdk.events", "app.sdk.logging", "app.sdk.plugin",
        "app.sdk.network", "app.sdk.media",
    )
    modules = {name: types.ModuleType(name) for name in names}
    settings = types.SimpleNamespace(RMT_MEDIAEXT={".strm", ".mkv", ".mp4", ".m2ts"}, LOG_PATH=ROOT, RENAME_FORMAT_S0_NAMES=("Specials", "SPs"))
    for name in ("app.core.config", "app.sdk.config"):
        modules[name].settings = settings
    for name in ("app.core.event", "app.sdk.events"):
        modules[name].Event = Event
        modules[name].eventmanager = Manager()
    for name in ("app.log", "app.sdk.logging"):
        modules[name].logger = types.SimpleNamespace(**{
            method: lambda *args, **kwargs: None for method in ("info", "warning", "error")
        })
    modules["app.log"].LoggerManager = types.SimpleNamespace()
    for name in ("app.plugins", "app.sdk.plugin"):
        modules[name]._PluginBase = type("PluginBase", (), {})
    for name, symbol in (("app.chain.media", "MediaChain"), ("app.chain.scraping", "ScrapingChain")):
        setattr(modules[name], symbol, type(symbol, (), {}))
    modules["app.chain.transfer"].TransferChain = type("TransferChain", (), {"get_queue_tasks": lambda self: []})
    modules["app.schemas.types"].EventType = types.SimpleNamespace(MetadataScrape="scrape", TransferComplete="transfer")
    modules["app.core.metainfo"].MetaInfoPath = lambda *args: None
    for name in ("app.core.metainfo", "app.sdk.media"):
        modules[name].MetaInfo = lambda name: types.SimpleNamespace(begin_season=1 if name.startswith("Season") else None)
    for name in ("app.utils.http", "app.sdk.network"):
        modules[name].RequestUtils = type("RequestUtils", (), {})
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(tree.replace(".", "_"), ROOT / tree / "etkscrapewebhook/__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


PLUGINS = {tree: load_plugin(tree) for tree in ("plugins", "plugins.v2", "plugins.v3")}


class WashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def media(self, name="Show.S01E01.strm", xml="<episodedetails/>"):
        path = self.root / name
        path.write_text("/cloud/" + path.name)
        if xml is not None:
            path.with_suffix(".nfo").write_text(xml)
        return path

    def data(self, paths=None, **fields):
        return {"fileitem": {"path": str(self.root), "storage": "local"},
                "mediainfo": {"type": "TV", "tmdb_id": "1", "media_source": "themoviedb", "media_id": "1"},
                "file_list": [str(path) for path in paths or []], **fields}

    def verify(self, data, expected):
        for tree, module in PLUGINS.items():
            with self.subTest(tree=tree):
                frozen = deepcopy(data)
                actual, error = module.ETKScrapeWebhook._verify_scrape_outputs(frozen)
                self.assertEqual(actual, expected, error)

    def flush(self, module, events, during_scrape=None):
        cls = module.ETKScrapeWebhook
        cls._pending.clear()
        if hasattr(cls, "_running"):
            cls._running.clear()
        plugin = cls()
        plugin._enabled = True
        payloads = []
        plugin._send_webhook = payloads.append
        enqueue = lambda data: plugin._enqueue_completed(data) if hasattr(plugin, "_enqueue_completed") else plugin._enqueue_scrape(Event("scrape", data))
        if hasattr(cls, "_original_scrape_handler"):
            cls._original_scrape_handler = staticmethod(lambda *args: during_scrape(enqueue) if during_scrape else None)
        with patch.object(module.threading, "Timer", Timer):
            for data in events:
                enqueue(data)
            key = plugin._event_key(events[0])
            flush = plugin._flush_completed if hasattr(plugin, "_flush_completed") else plugin._flush_scrape
            flush(key)
            if cls._pending:
                cls._original_scrape_handler = staticmethod(lambda *args: None)
                flush(key)
        return payloads

    def test_old_nfo_without_media_fails(self):
        path = self.root / "deleted.strm"
        path.with_suffix(".nfo").write_text("<episodedetails/>")
        self.verify(self.data([path]), False)
        self.verify(self.data(), False)

    def test_bad_xml_and_wrong_nfo_root_fail(self):
        path = self.media()
        for xml in ("", "<episodedetails>", "<tvshow/>", "<movie/>"):
            path.with_suffix(".nfo").write_text(xml)
            self.verify(self.data([path]), False)

    def test_old_valid_nfo_reuse_and_movie_root(self):
        path = self.media()
        self.verify(self.data([path]), True)
        path.with_suffix(".nfo").write_text("<movie/>")
        self.verify(self.data([path], mediainfo={"type": "Movie"}), True)

    def test_full_directory_requires_each_physical_media_nfo(self):
        self.media("Show.S01E01.mkv")
        self.media("Show.S01E02.mkv", None)
        (self.root / "tvshow.nfo").write_text("<tvshow/>")
        self.verify(self.data(), False)

    def test_uppercase_media_and_nfo_extensions(self):
        path = self.media("Show.S01E01.STRM")
        path.with_suffix(".nfo").rename(path.with_suffix(".NFO"))
        self.verify(self.data(), True)

    def test_deleted_a_new_b_only_sends_existing_b(self):
        a = self.media("A.strm")
        b = self.media("B.strm")
        a.unlink()
        for tree, module in PLUGINS.items():
            with self.subTest(tree=tree):
                payload = self.flush(module, [self.data([a, b])])[0]
                self.assertTrue(payload["success"])
                self.assertEqual(payload["file_list"], [str(b)])
                self.assertFalse(payload["full_scan"])

    def test_mixed_scope_preserves_full_scan_in_both_orders(self):
        a, b = self.media("A.strm"), self.media("B.strm")
        for tree, module in PLUGINS.items():
            for events in ((self.data([a]), self.data()), (self.data(), self.data([a]))):
                with self.subTest(tree=tree, events=events):
                    payload = self.flush(module, events)[0]
                    self.assertTrue(payload["full_scan"])
                    self.assertEqual(payload["file_list"], [str(a), str(b)])

    def test_precise_empty_scope_does_not_expand(self):
        self.media()
        self.verify(self.data(full_scan=False), False)

    def test_following_batch_full_scope_is_preserved(self):
        path, other = self.media("A.strm"), self.media("B.strm")
        for tree in ("plugins.v2", "plugins.v3"):
            with self.subTest(tree=tree):
                first = self.data([path])
                later = self.data()
                payloads = self.flush(PLUGINS[tree], [first], during_scrape=lambda enqueue: enqueue(later))
                self.assertEqual(len(payloads), 1)
                self.assertTrue(payloads[0]["full_scan"])
                self.assertEqual(payloads[0]["file_list"], [str(path), str(other)])

    def test_http_retry_reuses_payload_batch_and_media_snapshot(self):
        path = self.media()
        for tree, module in PLUGINS.items():
            with self.subTest(tree=tree):
                plugin = module.ETKScrapeWebhook()
                payload = self.flush(module, [self.data([path])])[0]
                plugin._retry_count = 1
                received = []
                def send(_url, json):
                    received.append(deepcopy(json))
                    return types.SimpleNamespace(status_code=503 if len(received) == 1 else 200, text="retry")
                with patch.object(module, "RequestUtils", return_value=types.SimpleNamespace(post_res=send)), patch.object(module.time, "sleep"):
                    plugin._send_webhook(payload)
                self.assertEqual(len(received), 2)
                self.assertEqual(received[0], received[1])

    def test_notification_does_not_add_unvalidated_files_after_verification(self):
        path = self.media()
        for tree in ("plugins.v2", "plugins.v3"):
            with self.subTest(tree=tree):
                module = PLUGINS[tree]
                parse = module.ElementTree.parse
                late = self.root / "late.mkv"
                def parse_and_add(*args, **kwargs):
                    result = parse(*args, **kwargs)
                    late.write_text("new media without NFO")
                    return result
                with patch.object(module.ElementTree, "parse", side_effect=parse_and_add):
                    payload = self.flush(module, [self.data()])[0]
                self.assertTrue(payload["success"])
                self.assertEqual(payload["file_list"], [str(path)])
                late.unlink()

    def test_media_removed_during_xml_parse_does_not_succeed(self):
        for tree, module in PLUGINS.items():
            with self.subTest(tree=tree):
                path = self.media()
                parse = module.ElementTree.parse
                def parse_and_remove(*args, **kwargs):
                    result = parse(*args, **kwargs)
                    path.unlink()
                    return result
                data = self.data([path])
                with patch.object(module.ElementTree, "parse", side_effect=parse_and_remove):
                    success, error = module.ETKScrapeWebhook._verify_scrape_outputs(data)
                self.assertFalse(success, error)
                self.assertEqual(data["file_list"], [])

    def test_directory_read_error_sends_one_failure_payload(self):
        for tree, module in PLUGINS.items():
            with self.subTest(tree=tree):
                with patch.object(module.ETKScrapeWebhook, "_final_media_files", side_effect=PermissionError("blocked")):
                    payloads = self.flush(module, [self.data()])
                self.assertEqual(len(payloads), 1)
                self.assertFalse(payloads[0]["success"])
                self.assertEqual(payloads[0]["file_list"], [])

    def test_movie_full_scan_skips_extras_but_series_keeps_seasons(self):
        main = self.media("Movie.mkv", "<movie/>")
        extras = self.root / "Extras"
        extras.mkdir()
        (extras / "trailer.mkv").write_text("extra")
        self.verify(self.data(mediainfo={"type": "Movie"}), True)
        season = self.root / "Season 01"
        season.mkdir()
        episode = season / "Show.S01E01.strm"
        episode.write_text("/cloud/episode")
        episode.with_suffix(".nfo").write_text("<episodedetails/>")
        main.unlink()
        self.verify(self.data(), True)

    def test_bluray_checks_directory_nfo_and_never_sends_stream_fragments(self):
        stream = self.root / "BDMV" / "STREAM"
        stream.mkdir(parents=True)
        segment = stream / "00001.m2ts"
        segment.write_text("disc media")
        (self.root / f"{self.root.name}.nfo").write_text("<movie/>")
        for tree, module in PLUGINS.items():
            for paths in ([], [segment]):
                with self.subTest(tree=tree, paths=paths):
                    payload = self.flush(module, [self.data(paths, mediainfo={"type": "Movie"})])[0]
                    self.assertTrue(payload["success"], payload["error"])
                    self.assertEqual(payload["file_list"], [str(self.root)])
        segment.unlink()
        self.verify(self.data(mediainfo={"type": "Movie"}), False)

    def test_external_precise_media_cannot_pass_using_its_own_valid_nfo(self):
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / "outside.strm"
            external.write_text("/cloud/outside")
            external.with_suffix(".nfo").write_text("<episodedetails/>")
            self.verify(self.data([external]), False)

    def test_single_file_root_only_allows_that_file(self):
        first, second = self.media("A.strm"), self.media("B.strm")
        root = {"path": str(first), "storage": "local"}
        self.verify(self.data([first], fileitem=root), True)
        self.verify(self.data([second], fileitem=root), False)

    def test_symlink_root_keeps_the_host_visible_media_path(self):
        path = self.media()
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "alias"
            alias.symlink_to(self.root, target_is_directory=True)
            visible = alias / path.name
            for tree, module in PLUGINS.items():
                for paths in ([], [visible]):
                    with self.subTest(tree=tree, paths=paths):
                        data = self.data(paths, fileitem={"path": str(alias), "storage": "local"})
                        payload = self.flush(module, [data])[0]
                        self.assertTrue(payload["success"], payload["error"])
                        self.assertEqual(payload["root_path"], str(alias))
                        self.assertEqual(payload["file_list"], [str(visible)])

    def test_symlink_inside_root_cannot_forward_external_media(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "outside.strm"
            outside.write_text("/cloud/outside")
            outside.with_suffix(".nfo").write_text("<episodedetails/>")
            link = self.root / outside.name
            link.symlink_to(outside)
            link.with_suffix(".nfo").symlink_to(outside.with_suffix(".nfo"))
            self.verify(self.data([link]), False)
            self.verify(self.data(), False)

    def test_season_symlink_cycle_does_not_duplicate_media(self):
        path = self.media()
        (self.root / "Season 01").symlink_to(self.root, target_is_directory=True)
        for tree, module in PLUGINS.items():
            with self.subTest(tree=tree):
                payload = self.flush(module, [self.data()])[0]
                self.assertTrue(payload["success"], payload["error"])
                self.assertEqual(payload["file_list"], [str(path)])


if __name__ == "__main__":
    unittest.main()
