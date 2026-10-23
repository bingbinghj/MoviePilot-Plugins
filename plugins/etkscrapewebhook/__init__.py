import hashlib
import os
import threading
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.chain.media import MediaChain
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfoPath
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class ETKScrapeWebhook(_PluginBase):
    plugin_name = "ETK刮削完成通知"
    plugin_desc = "合并MoviePilot已完成的整理与手动刮削，校验NFO后通知ETK。"
    plugin_icon = "webhook.png"
    plugin_version = "1.1.0"
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
            pending = type(self)._pending.setdefault(key, {"event_data": {}, "file_list": set(), "timer": None})
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
        data["file_list"] = sorted(pending["file_list"])
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
        return hashlib.sha256(f'{storage}\n{path}'.encode('utf-8')).hexdigest()

    @classmethod
    def _media_identity(cls, media):
        media_type = cls._field(media, 'type', '')
        media_type = str(getattr(media_type, 'value', media_type)).lower()
        media_type = {'tv': 'series', '电视剧': 'series', '电影': 'movie'}.get(media_type, media_type)
        return (str(cls._field(media, 'tmdb_id') or cls._field(media, 'tmdbid') or ''), media_type)

    @classmethod
    def _verify_scrape_outputs(cls, event_data: Dict[str, Any]) -> Tuple[bool, str]:
        fileitem = event_data.get('fileitem')
        root_path = Path(str(cls._field(fileitem, 'path', '') or ''))
        if not root_path.exists():
            return (False, f'MoviePilot刮削根路径不存在: {root_path}')
        media_extensions = {str(ext).lower() for ext in settings.RMT_MEDIAEXT}
        file_list = [Path(str(path)) for path in event_data.get('file_list') or [] if path and Path(str(path)).suffix.lower() in media_extensions]
        expected_nfos = [path.with_suffix('.nfo') for path in file_list]
        if expected_nfos:
            existing_count = sum((path.is_file() for path in expected_nfos))
            if existing_count == len(expected_nfos):
                return (True, '')
            return (False, f'MoviePilot未生成完整分集NFO: {existing_count}/{len(expected_nfos)}')
        if root_path.is_file():
            nfo_path = root_path.with_suffix('.nfo')
            if nfo_path.is_file():
                return (True, '')
            return (False, f'MoviePilot未生成NFO: {nfo_path}')
        strm_files = sorted(root_path.rglob('*.strm'))
        if strm_files:
            existing_count = sum((path.with_suffix('.nfo').is_file() for path in strm_files))
            if existing_count == len(strm_files):
                return (True, '')
            return (False, f'MoviePilot未生成完整STRM NFO: {existing_count}/{len(strm_files)}')
        for _, _, filenames in os.walk(root_path):
            if any((filename.lower().endswith('.nfo') for filename in filenames)):
                return (True, '')
        return (False, f'MoviePilot刮削目录内未找到NFO: {root_path}')

    def _build_payload(self, *, event_data: Dict[str, Any], batch_id: str, success: bool, error: str, duration: float) -> Dict[str, Any]:
        fileitem = event_data.get('fileitem')
        mediainfo = event_data.get('mediainfo')
        meta = event_data.get('meta')
        media_type = self._field(mediainfo, 'type') or self._field(meta, 'type')
        if hasattr(media_type, 'value'):
            media_type = media_type.value
        tmdb_id = self._field(mediainfo, 'tmdb_id') or self._field(mediainfo, 'tmdbid') or self._field(meta, 'tmdb_id') or self._field(meta, 'tmdbid')
        return {'event': 'metadata.scrape.complete', 'batch_id': batch_id, 'success': success, 'error': error or None, 'duration_seconds': duration, 'media_type': str(media_type or ''), 'tmdb_id': str(tmdb_id or ''), 'episode_group': str(self._field(mediainfo, 'episode_group', '') or ''), 'root_path': str(self._field(fileitem, 'path', '') or ''), 'storage': str(self._field(fileitem, 'storage', '') or ''), 'file_list': [str(path) for path in event_data.get('file_list') or [] if path], 'full_scan': not bool(event_data.get('file_list'))}

    def _send_webhook(self, payload: Dict[str, Any]):
        headers = {'Content-Type': 'application/json', 'X-Emby-Toolkit-Token': self._secret}
        attempts = self._retry_count + 1
        for attempt in range(1, attempts + 1):
            try:
                response = RequestUtils(headers=headers, timeout=self._timeout_seconds).post_res(self._webhook_url, json=payload)
                if response and 200 <= response.status_code < 300:
                    file_count = len(payload.get('file_list') or [])
                    scope_label = f'精确文件 {file_count} 个' if file_count else '整目录'
                    episode_group = payload.get('episode_group') or '官方季'
                    logger.info('【ETK刮削完成通知】ETK已接收批次 %s: %s，范围: %s，剧集组: %s', payload['batch_id'], payload['root_path'], scope_label, episode_group)
                    return
                detail = response.text if response is not None else '无响应'
                logger.warning('【ETK刮削完成通知】第 %s/%s 次通知失败: %s', attempt, attempts, detail)
            except Exception as exc:
                logger.warning('【ETK刮削完成通知】第 %s/%s 次通知异常: %s', attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 5))
