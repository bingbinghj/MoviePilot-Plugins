import hashlib
import threading
import uuid
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from xml.etree import ElementTree
from typing import Any, Dict, List, Optional, Tuple

from app.chain.media import MediaChain
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfo, MetaInfoPath
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class ETKScrapeWebhook(_PluginBase):
    plugin_name = "ETK刮削完成通知"
    plugin_desc = "合并MoviePilot已完成的整理与手动刮削，校验NFO后通知ETK。"
    plugin_icon = "webhook.png"
    plugin_version = "1.1.3"
    plugin_author = "bingbinghj"
    author_url = "https://github.com/bingbinghj"
    plugin_config_prefix = "etkscrapewebhook_"
    plugin_order = 15
    auth_level = 1

    _enabled = False
    _webhook_url = ""
    _secret = ""
    _debounce_seconds = 10
    _timeout_seconds = 15
    _retry_count = 2
    _pending = {}
    _lock = threading.RLock()
    _original_manual_scrape = None
    _manual_wrapper = None

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._webhook_url = str(config.get("webhook_url") or "").strip()
        self._secret = str(config.get("secret") or "").strip()
        self._debounce_seconds = max(1, int(config.get("debounce_seconds") or 10))
        self._timeout_seconds = max(1, int(config.get("timeout_seconds") or 15))
        self._retry_count = max(0, int(config.get("retry_count", 2)))
        if not self._enabled:
            return
        if not self._webhook_url or not self._secret:
            self._enabled = False
            logger.error("【ETK刮削完成通知】Webhook地址或共享密钥未配置，插件未启用")
            return
        cls = type(self)
        with cls._lock:
            original = MediaChain.manual_scrape
            cls._original_manual_scrape = original
            depth = threading.local()

            def completed(chain, storage, fileitem, meta=None, mediainfo=None, init_folder=True):
                if self._media_identity(mediainfo or meta)[1] in {"music", "音乐"}:
                    # 音乐仅转交宿主，不参与影视 NFO 校验或通知；独立调用栈保持宿主日志归属。
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="MoviePilot-MusicScrape") as executor:
                        return executor.submit(
                            copy_context().run, original, chain, storage, fileitem, meta, mediainfo, init_folder,
                        ).result()
                nesting = getattr(depth, "value", 0)
                depth.value = nesting + 1
                try:
                    result = original(chain, storage, fileitem, meta, mediainfo, init_folder)
                finally:
                    depth.value = nesting
                if nesting == 0 and self._enabled and storage == "local":
                    try:
                        media = mediainfo or chain.recognize_by_meta(meta or MetaInfoPath(Path(fileitem.path)))
                        self._enqueue_completed({
                            "fileitem": {"path": str(fileitem.path), "storage": storage},
                            "mediainfo": media, "meta": meta, "file_list": [],
                        })
                    except Exception as exc:
                        logger.warning("【ETK刮削完成通知】手动刮削完成通知失败: %s", exc)
                return result

            cls._manual_wrapper = completed
            MediaChain.manual_scrape = completed

    @eventmanager.register(EventType.TransferComplete)
    def _handle_transfer_complete(self, event: Event):
        if not self._enabled:
            return
        data = event.event_data or {}
        transfer = data.get("transferinfo")
        path = self._field(transfer, "target_path")
        files = self._field(transfer, "file_list_new", []) or self._field(transfer, "file_list", []) or []
        if path:
            self._enqueue_completed({
                "fileitem": {"path": str(path), "storage": "local"},
                "mediainfo": data.get("mediainfo"), "meta": data.get("meta"),
                "file_list": files,
            })

    def _enqueue_completed(self, event_data):
        if self._media_identity(event_data.get("mediainfo") or event_data.get("meta"))[1] not in {"movie", "series"}:
            return
        key = self._event_key(event_data)
        if not key or not self._enabled:
            return
        with type(self)._lock:
            pending = type(self)._pending.setdefault(key, {"event_data": {}, "file_list": set(), "full_scan": False, "timer": None})
            pending["full_scan"] = pending["full_scan"] or self._is_full_scan(event_data)
            pending["event_data"].update(event_data)
            pending["file_list"].update(str(path) for path in event_data.get("file_list") or [] if path)
            if pending["timer"]:
                pending["timer"].cancel()
            token = object()
            pending["token"] = token
            timer = threading.Timer(self._debounce_seconds, self._flush_completed, args=(key, token))
            timer.daemon = True
            pending["timer"] = timer
            timer.start()

    def _flush_completed(self, key, token=None):
        with type(self)._lock:
            pending = type(self)._pending.get(key)
            if not self._enabled or not pending or (token is not None and token is not pending["token"]):
                return
            type(self)._pending.pop(key)
        data = dict(pending["event_data"])
        data["full_scan"] = pending["full_scan"]
        data["file_list"] = [] if pending["full_scan"] else sorted(pending["file_list"])
        success, error = self._verify_scrape_outputs(data)
        self._send_webhook(self._build_payload(event_data=data, batch_id=uuid.uuid4().hex,
                                               success=success, error=error, duration=0))

    def stop_service(self):
        cls = type(self)
        with cls._lock:
            self._enabled = False
            for pending in cls._pending.values():
                if pending["timer"]:
                    pending["timer"].cancel()
            cls._pending.clear()
            if cls._manual_wrapper is not None and MediaChain.manual_scrape is cls._manual_wrapper:
                MediaChain.manual_scrape = cls._original_manual_scrape
            cls._original_manual_scrape = None
            cls._manual_wrapper = None

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> Optional[List[dict]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return ([{'component': 'VForm', 'content': [{'component': 'VRow', 'content': [{'component': 'VCol', 'props': {'cols': 12, 'md': 3}, 'content': [{'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}}]}, {'component': 'VCol', 'props': {'cols': 12, 'md': 9}, 'content': [{'component': 'VTextField', 'props': {'model': 'webhook_url', 'label': 'ETK Webhook地址', 'placeholder': 'http://emby-toolkit:5257/webhook/moviepilot'}}]}]}, {'component': 'VRow', 'content': [{'component': 'VCol', 'props': {'cols': 12, 'md': 6}, 'content': [{'component': 'VTextField', 'props': {'model': 'secret', 'label': 'ETK Webhook共享密钥', 'type': 'password'}}]}, {'component': 'VCol', 'props': {'cols': 12, 'md': 2}, 'content': [{'component': 'VTextField', 'props': {'model': 'debounce_seconds', 'label': '合并等待(秒)', 'type': 'number', 'min': 1}}]}, {'component': 'VCol', 'props': {'cols': 12, 'md': 2}, 'content': [{'component': 'VTextField', 'props': {'model': 'timeout_seconds', 'label': '请求超时(秒)', 'type': 'number', 'min': 1}}]}, {'component': 'VCol', 'props': {'cols': 12, 'md': 2}, 'content': [{'component': 'VTextField', 'props': {'model': 'retry_count', 'label': '失败重试', 'type': 'number', 'min': 0}}]}]}]}], {'enabled': False, 'webhook_url': '', 'secret': '', 'debounce_seconds': 10, 'timeout_seconds': 15, 'retry_count': 2})

    @staticmethod
    def _field(value: Any, name: str, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _event_key(cls, event_data: Dict[str, Any]) -> Optional[str]:
        fileitem = event_data.get('fileitem')
        path = str(cls._field(fileitem, 'path', '') or '').strip()
        storage = str(cls._field(fileitem, 'storage', '') or '').strip()
        if not path:
            return None
        identity = cls._media_identity(event_data.get('mediainfo') or event_data.get('meta'))
        return hashlib.sha256(f'{storage}\n{path}\n{identity!r}'.encode('utf-8')).hexdigest()

    @classmethod
    def _media_identity(cls, media):
        media_type = cls._field(media, 'type', '')
        media_type = str(getattr(media_type, 'value', media_type)).lower()
        media_type = {'tv': 'series', '电视剧': 'series', '电影': 'movie'}.get(media_type, media_type)
        return (str(cls._field(media, 'tmdb_id') or cls._field(media, 'tmdbid') or ''), media_type)

    @classmethod
    def _episode_group(cls, media) -> str:
        if cls._media_identity(media)[-1] != 'series':
            return ''
        return str(cls._field(media, 'episode_group', '') or '').strip()

    @staticmethod
    def _is_full_scan(event_data: Dict[str, Any]) -> bool:
        return bool(event_data.get("full_scan", not bool(event_data.get("file_list"))))

    @staticmethod
    def _is_disc_directory(path: Path) -> bool:
        return path.is_dir() and any((path / name).is_dir() for name in ("BDMV", "CERTIFICATE"))

    @classmethod
    def _media_exists(cls, path):
        extensions = {"." + str(ext).lower().lstrip(".") for ext in settings.RMT_MEDIAEXT} | {".strm"}
        return path.is_file() or (cls._is_disc_directory(path) and any(
            item.is_file() and item.suffix.lower() in extensions for item in path.rglob("*")
        ))

    @classmethod
    def _final_media_files(cls, event_data):
        root = Path(str(cls._field(event_data.get("fileitem"), "path", "") or ""))
        resolved_root = root.resolve()
        extensions = {"." + str(ext).lower().lstrip(".") for ext in settings.RMT_MEDIAEXT} | {".strm"}
        media_type = cls._media_identity(event_data.get("mediainfo") or event_data.get("meta"))[-1]

        def check_scope(path):
            resolved = path.resolve()
            if resolved != resolved_root and (root.is_file() or resolved_root not in resolved.parents):
                raise ValueError(f"MoviePilot媒体文件超出刮削根范围: {path}")

        def has_disc_media(path):
            return cls._media_exists(path)

        scanned_directories = set()

        def scan(path):
            check_scope(path)
            if path.is_dir():
                resolved = path.resolve()
                if resolved in scanned_directories:
                    return
                scanned_directories.add(resolved)
            if cls._is_disc_directory(path):
                if has_disc_media(path):
                    yield path
                return
            if path.is_file():
                if path.suffix.lower() in extensions:
                    yield path
            elif path.is_dir():
                for child in path.iterdir():
                    if child.is_file() and child.suffix.lower() in extensions:
                        check_scope(child)
                        yield child
                    elif child.is_dir() and media_type == "series" and (
                        child.name in getattr(settings, "RENAME_FORMAT_S0_NAMES", ())
                        or MetaInfo(child.name).begin_season is not None
                    ):
                        yield from scan(child)

        if cls._is_full_scan(event_data):
            return sorted(set(scan(root)))
        files = set()
        for value in event_data.get("file_list") or []:
            if not value:
                continue
            path = Path(str(value))
            check_scope(path)
            disc = next((parent for parent in (path, *path.parents)
                         if (parent == root or root in parent.parents) and cls._is_disc_directory(parent)), None)
            if disc:
                if has_disc_media(disc):
                    files.add(disc)
            elif path.is_file() and path.suffix.lower() in extensions:
                files.add(path)
        return sorted(files)

    @classmethod
    def _freeze_final_scope(cls, event_data):
        full_scan = cls._is_full_scan(event_data)
        files = cls._final_media_files(event_data)
        event_data["full_scan"] = full_scan
        event_data["file_list"] = [str(path) for path in files]
        return files

    @classmethod
    def _verify_scrape_outputs(cls, event_data: Dict[str, Any]) -> Tuple[bool, str]:
        try:
            files = cls._freeze_final_scope(event_data)
        except (OSError, ValueError) as exc:
            event_data["file_list"] = []
            return False, f"MoviePilot刮削范围无法验收: {exc}"
        if not files:
            return False, "MoviePilot刮削范围内没有现存媒体文件"
        media_type = cls._media_identity(event_data.get("mediainfo") or event_data.get("meta"))[-1]
        expected_roots = {"movie"} if media_type == "movie" else {"episodedetails"} if media_type == "series" else {"movie", "episodedetails"}
        for path in files:
            nfo = path / f"{path.name}.nfo" if path.is_dir() else path.with_suffix(".nfo")
            try:
                if not nfo.is_file():
                    nfo = next((item for item in nfo.parent.iterdir()
                                if item.is_file() and item.stem == nfo.stem and item.suffix.lower() == ".nfo"), nfo)
                if ElementTree.parse(nfo).getroot().tag not in expected_roots:
                    return False, f"MoviePilot NFO类型不匹配: {nfo}"
            except (OSError, ElementTree.ParseError) as exc:
                return False, f"MoviePilot NFO无效: {nfo} - {exc}"
        # 只过滤已经验收的快照，不加入验证期间新增而尚未验收的文件。
        try:
            event_data["file_list"] = [str(path) for path in files if cls._media_exists(path)]
        except OSError as exc:
            event_data["file_list"] = []
            return False, f"MoviePilot验收期间媒体状态无法确认: {exc}"
        if not event_data["file_list"]:
            return False, "MoviePilot验收期间媒体文件已失效"
        return True, ""

    def _build_payload(self, *, event_data: Dict[str, Any], batch_id: str, success: bool, error: str, duration: float) -> Dict[str, Any]:
        fileitem = event_data.get('fileitem')
        mediainfo = event_data.get('mediainfo')
        meta = event_data.get('meta')
        media_type = self._field(mediainfo, 'type') or self._field(meta, 'type')
        if hasattr(media_type, 'value'):
            media_type = media_type.value
        tmdb_id = self._field(mediainfo, 'tmdb_id') or self._field(mediainfo, 'tmdbid') or self._field(meta, 'tmdb_id') or self._field(meta, 'tmdbid')
        return {'event': 'metadata.scrape.complete', 'batch_id': batch_id, 'success': success, 'error': error or None, 'duration_seconds': duration, 'media_type': str(media_type or ''), 'tmdb_id': str(tmdb_id or ''), 'episode_group': self._episode_group(mediainfo or meta), 'root_path': str(self._field(fileitem, 'path', '') or ''), 'storage': str(self._field(fileitem, 'storage', '') or ''), 'file_list': [str(path) for path in event_data.get('file_list') or [] if path], 'full_scan': self._is_full_scan(event_data)}

    def _send_webhook(self, payload: Dict[str, Any]):
        headers = {'Content-Type': 'application/json', 'X-Emby-Toolkit-Token': self._secret}
        attempts = self._retry_count + 1
        for attempt in range(1, attempts + 1):
            try:
                response = RequestUtils(headers=headers, timeout=self._timeout_seconds).post_res(self._webhook_url, json=payload)
                if response and 200 <= response.status_code < 300:
                    file_count = len(payload.get('file_list') or [])
                    scope_label = f'精确文件 {file_count} 个' if file_count else '整目录'
                    message = '【ETK刮削完成通知】ETK已接收批次 %s: %s，范围: %s'
                    args = (payload['batch_id'], payload['root_path'], scope_label)
                    if self._media_identity({'type': payload.get('media_type')})[-1] == 'series':
                        message += '，剧集组: %s'
                        args += (payload.get('episode_group') or '官方季',)
                    logger.info(message, *args)
                    return
                detail = response.text if response is not None else '无响应'
                logger.warning('【ETK刮削完成通知】第 %s/%s 次通知失败: %s', attempt, attempts, detail)
            except Exception as exc:
                logger.warning('【ETK刮削完成通知】第 %s/%s 次通知异常: %s', attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 5))
