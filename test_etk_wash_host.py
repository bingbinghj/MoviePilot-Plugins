"""V3 integration: run with MoviePilot on PYTHONPATH and -p tests.conftest."""
import importlib.util
from pathlib import Path

import pytest

bootstrap = pytest.importorskip("app.testing.bootstrap")
bootstrap.prepare_v3_backend(Path(__file__).resolve().parent)

from app.chain.scraping import ScrapingChain
from app.chain.transfer import TransferChain
from app.modules.filemanager.module import FileManagerModule
from app.modules.filemanager.storages.local import LocalStorage
from app.sdk.events import Event
from app.sdk.media import MediaInfo, MetaInfo
from app.schemas import FileItem
from app.schemas.types import EventType, MediaType


@pytest.fixture
def host_plugin(monkeypatch):
    source = Path(__file__).resolve().parent / "plugins.v3/etkscrapewebhook/__init__.py"
    spec = importlib.util.spec_from_file_location("etk_real_host", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = module.ETKScrapeWebhook
    plugin = cls()
    plugin._enabled = True
    monkeypatch.setattr(cls, "_pending", {})
    monkeypatch.setattr(cls, "_running", set())
    monkeypatch.setattr(cls, "_original_scrape_handler", ScrapingChain.scrape_metadata_event)
    monkeypatch.setattr(TransferChain, "get_queue_tasks", lambda self: [])
    monkeypatch.setattr(plugin, "_schedule_scrape", lambda *args: None)
    payloads = []
    monkeypatch.setattr(plugin, "_send_webhook", payloads.append)

    # Assemble real local FileManager and StorageChain methods; remote metadata is mocked.
    filemanager = FileManagerModule()
    monkeypatch.setattr(filemanager, "_storage_schemas", [LocalStorage])
    monkeypatch.setattr(filemanager, "_support_storages", ["local"])
    chain = ScrapingChain()
    monkeypatch.setattr(chain.storagechain, "run_module", lambda name, **kwargs: getattr(filemanager, name)(**kwargs))
    monkeypatch.setattr(chain, "metadata_nfo", lambda **kwargs: "<movie><title>Test</title></movie>")
    monkeypatch.setattr(chain, "metadata_img", lambda **kwargs: {})
    yield plugin, module, chain, payloads
    for pending in cls._pending.values():
        if pending.get("timer"):
            pending["timer"].cancel()
    cls._pending.clear()
    cls._running.clear()


def event(root, paths=None):
    return Event(event_type=EventType.MetadataScrape, event_data={
        "fileitem": FileItem(storage="local", type="dir", path=str(root), name=root.name),
        "mediainfo": MediaInfo(type=MediaType.MOVIE, title="Test", year="2026",
                               media_source="themoviedb", media_id="1"),
        "meta": MetaInfo("Test (2026)"),
        "file_list": [str(path) for path in paths or []],
    })


def flush(plugin, events):
    for value in events:
        plugin._handle_scrape_event(value)
    plugin._flush_scrape(plugin._event_key(events[0].event_data))


def test_real_host_exact_deleted_a_existing_b(host_plugin, tmp_path):
    plugin, module, _, payloads = host_plugin
    old, new = tmp_path / "Test.old.strm", tmp_path / "Test.new.strm"
    old.with_suffix(".nfo").write_text("<movie/>")
    new.write_text("/cloud/new.mkv")
    flush(plugin, [event(tmp_path, [old, new])])
    assert payloads[0]["success"], payloads[0]["error"]
    assert payloads[0]["file_list"] == [str(new)]
    assert new.with_suffix(".nfo").is_file()
    assert payloads[0]["full_scan"] is False
    assert module.ETKScrapeWebhook.plugin_version == "3.0.6"


def test_real_host_mixed_scope_preserves_full_directory_and_skips_extras(host_plugin, tmp_path):
    plugin, _, _, payloads = host_plugin
    first, second = tmp_path / "Test.A.strm", tmp_path / "Test.B.strm"
    first.write_text("/cloud/a.mkv")
    second.write_text("/cloud/b.mkv")
    extras = tmp_path / "Extras"
    extras.mkdir()
    (extras / "trailer.mkv").write_text("trailer")
    flush(plugin, [event(tmp_path, [first]), event(tmp_path)])
    assert payloads[0]["success"], payloads[0]["error"]
    assert payloads[0]["full_scan"] is True
    assert payloads[0]["file_list"] == [str(first), str(second)]
    assert first.with_suffix(".nfo").is_file()
    assert second.with_suffix(".nfo").is_file()


def test_real_host_bluray_uses_only_directory_nfo(host_plugin, tmp_path):
    plugin, _, _, payloads = host_plugin
    stream = tmp_path / "BDMV" / "STREAM"
    stream.mkdir(parents=True)
    fragment = stream / "00001.m2ts"
    fragment.write_text("disc media")
    flush(plugin, [event(tmp_path, [fragment])])
    assert payloads[0]["success"], payloads[0]["error"]
    assert payloads[0]["file_list"] == [str(tmp_path)]
    assert (tmp_path / f"{tmp_path.name}.nfo").is_file()
    assert not fragment.with_suffix(".nfo").exists()


def test_real_host_invalid_generated_xml_fails(host_plugin, monkeypatch, tmp_path):
    plugin, _, chain, payloads = host_plugin
    video = tmp_path / "Test.strm"
    video.write_text("/cloud/video.mkv")
    monkeypatch.setattr(chain, "metadata_nfo", lambda **kwargs: "<movie>")
    flush(plugin, [event(tmp_path, [video])])
    assert payloads[0]["success"] is False
    assert "NFO" in payloads[0]["error"]


def test_real_host_existing_valid_nfo_can_be_reused(host_plugin, monkeypatch, tmp_path):
    plugin, _, chain, payloads = host_plugin
    video = tmp_path / "Test.strm"
    video.write_text("/cloud/video.mkv")
    nfo = video.with_suffix(".nfo")
    nfo.write_text("<movie><title>Existing</title></movie>")
    def unexpected(**kwargs):
        raise AssertionError("Valid existing NFO must not be overwritten")
    monkeypatch.setattr(chain, "metadata_nfo", unexpected)
    flush(plugin, [event(tmp_path, [video])])
    assert payloads[0]["success"], payloads[0]["error"]
    assert nfo.read_text() == "<movie><title>Existing</title></movie>"
