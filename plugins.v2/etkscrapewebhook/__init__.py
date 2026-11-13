import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import copy
from pathlib import Path
from xml.etree import ElementTree
from typing import Any, Dict, List, Optional, Tuple

from app.chain.media import MediaChain
from app.chain.transfer import TransferChain
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.core.metainfo import MetaInfo
from app.log import LoggerManager, logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class ETKScrapeWebhook(_PluginBase):
    plugin_name = "ETK刮削完成通知"
    plugin_desc = "合并MoviePilot重复刮削请求，并在实际刮削完成后通知ETK。"
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

    _original_scrape_handler = None
    _listener_installed = False
    _pending: Dict[str, Dict[str, Any]] = {}
    _running = set()
    _lock = threading.RLock()

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
            logger.error("【ETK刮削完成通知】Webhook地址或共享密钥未配置，插件未启用")
            self._enabled = False
            return
        self._configure_plugin_log_rotation()
        self._install_listener()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_page(self) -> Optional[List[dict]]:
        pass

    @staticmethod
    def _plugin_log_path() -> Path:
        return Path(settings.LOG_PATH) / "plugins" / "etkscrapewebhook.log"

    @classmethod
    def _configure_plugin_log_rotation(cls):
        log_path = cls._plugin_log_path()
        try:
            handler = LoggerManager._file_handler._get_rotating_handler(log_path)
            handler.maxBytes = 5 * 1024 * 1024
            handler.backupCount = 10

            backups = sorted(
                log_path.parent.glob(f"{log_path.name}.*"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for old_backup in backups[10:]:
                old_backup.unlink(missing_ok=True)
        except (OSError, AttributeError) as exc:
            logger.warning("【ETK刮削完成通知】配置插件日志轮转失败: %s", exc)

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"},
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 9},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "webhook_url",
                                            "label": "ETK Webhook地址",
                                            "placeholder": "http://emby-toolkit:5257/webhook/moviepilot",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "secret",
                                            "label": "ETK Webhook共享密钥",
                                            "type": "password",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "debounce_seconds",
                                            "label": "合并等待(秒)",
                                            "type": "number",
                                            "min": 1,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "timeout_seconds",
                                            "label": "请求超时(秒)",
                                            "type": "number",
                                            "min": 1,
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "retry_count",
                                            "label": "失败重试",
                                            "type": "number",
                                            "min": 0,
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "webhook_url": "",
            "secret": "",
            "debounce_seconds": 10,
            "timeout_seconds": 15,
            "retry_count": 2,
        }

    def _install_listener(self):
        cls = type(self)
        with cls._lock:
            if cls._listener_installed:
                return
            cls._original_scrape_handler = MediaChain.scrape_metadata_event
            eventmanager.disable_event_handler(cls._original_scrape_handler)
            eventmanager.add_event_listener(EventType.MetadataScrape, self._handle_scrape_event)
            cls._listener_installed = True

    def _handle_scrape_event(self, event: Event):
        data = getattr(event, "event_data", None) or {}
        media_type = self._media_identity(data.get("mediainfo") or data.get("meta"))[1]
        if media_type not in {"movie", "series"}:
            handler = type(self)._original_scrape_handler
            if handler is not None:
                # 直接执行宿主处理器，保留上下文与同步完成，避免 ETK 帧污染宿主日志归属。
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="MoviePilot-MusicScrape") as executor:
                    return executor.submit(copy_context().run, handler, MediaChain(), event).result()
            return None
        return self._enqueue_scrape(event)

    @staticmethod
    def _field(value: Any, name: str, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _root_key(cls, event_data: Dict[str, Any]) -> Optional[str]:
        fileitem = event_data.get("fileitem")
        path = str(cls._field(fileitem, "path", "") or "").strip()
        storage = str(cls._field(fileitem, "storage", "") or "").strip()
        if not path:
            return None
        return hashlib.sha256(f"{storage}\n{path}".encode("utf-8")).hexdigest()

    @classmethod
    def _event_key(cls, event_data: Dict[str, Any]) -> Optional[str]:
        root_key = cls._root_key(event_data)
        if not root_key:
            return None
        identity = cls._media_identity(event_data.get("mediainfo") or event_data.get("meta"))
        return hashlib.sha256(f"{root_key}\n{identity!r}".encode("utf-8")).hexdigest()

    @classmethod
    def _media_identity(cls, media):
        media_type = cls._field(media, "type", "")
        media_type = str(getattr(media_type, "value", media_type)).lower()
        media_type = {"tv": "series", "电视剧": "series", "电影": "movie"}.get(media_type, media_type)
        return str(cls._field(media, "tmdb_id") or cls._field(media, "tmdbid") or ""), media_type

    @classmethod
    def _episode_group(cls, media) -> str:
        if cls._media_identity(media)[-1] != "series":
            return ""
        return str(cls._field(media, "episode_group", "") or "").strip()

    @classmethod
    def _carry_episode_group(cls, previous_media, incoming_media):
        group = cls._episode_group(previous_media)
        identity = cls._media_identity(previous_media)
        if (not group or cls._episode_group(incoming_media)
                or not all(identity) or identity != cls._media_identity(incoming_media)):
            return incoming_media
        # 只补同一电视剧缺失的组，不回退新媒体信息，也不修改原事件对象。
        if isinstance(incoming_media, dict):
            return {**incoming_media, "episode_group": group}
        merged_media = copy(incoming_media)
        merged_media.episode_group = group
        return merged_media

    def _has_pending_transfer(self, event_data):
        identity = self._media_identity(event_data.get("mediainfo") or event_data.get("meta"))
        if not identity[0]:
            return False  # 手动文件刮削可能没有整理任务或媒体 ID。
        try:
            for job in TransferChain().get_queue_tasks():
                if self._media_identity(self._field(job, "media")) != identity:
                    continue
                if any(self._field(task, "state") not in {"completed", "failed"}
                       for task in self._field(job, "tasks", []) or []):
                    return True
        except Exception as exc:
            logger.warning("【ETK刮削完成通知】读取整理状态失败，保留批次等待重试: %s", exc)
            return True
        return False

    def _schedule_scrape(self, key, pending):
        if pending.get("timer"):
            pending["timer"].cancel()
        token = object()
        pending["token"] = token
        timer = threading.Timer(self._debounce_seconds, self._flush_scrape, args=(key, token))
        timer.daemon = True
        pending["timer"] = timer
        timer.start()

    def _enqueue_scrape(self, event: Event):
        event_data = dict(getattr(event, "event_data", None) or {})
        key = self._event_key(event_data)
        if not key:
            logger.warning("【ETK刮削完成通知】缺少刮削根路径，已忽略请求")
            return None

        incoming_files = [str(path) for path in event_data.get("file_list") or [] if path]
        with type(self)._lock:
            pending = type(self)._pending.get(key)
            if pending:
                previous_mediainfo = pending["event_data"].get("mediainfo")
                pending["file_list"].update(incoming_files)
                pending["full_scan"] = pending["full_scan"] or self._is_full_scan(event_data)
                pending["event_data"].update(event_data)
                pending["event_data"]["mediainfo"] = self._carry_episode_group(
                    previous_mediainfo, event_data.get("mediainfo"),
                )
            else:
                pending = {
                    "event_data": event_data,
                    "file_list": set(incoming_files),
                    "full_scan": self._is_full_scan(event_data),
                    "timer": None,
                }
                type(self)._pending[key] = pending

            self._schedule_scrape(key, pending)

        fileitem = event_data.get("fileitem")
        logger.info(
            "【ETK刮削完成通知】已合并刮削请求: %s，等待 %s 秒",
            self._field(fileitem, "path", "未知路径"),
            self._debounce_seconds,
        )
        return None

    def _flush_scrape(self, key: str, token=None):
        with type(self)._lock:
            pending = type(self)._pending.get(key)
            if not pending or not self._enabled or (token is not None and token is not pending.get("token")):
                return
            # 不同媒体分批，但同一根目录的宿主刮削仍串行，避免并发写入。
            root_key = self._root_key(pending["event_data"])
            if root_key in type(self)._running or self._has_pending_transfer(pending["event_data"]):
                if not pending.get("waiting_for_transfer"):
                    logger.info("【ETK刮削完成通知】仍有整理或刮削任务，等待本批全部完成: %s",
                                self._field(pending["event_data"].get("fileitem"), "path"))
                    pending["waiting_for_transfer"] = True
                self._schedule_scrape(key, pending)
                return
            type(self)._pending.pop(key)
            type(self)._running.add(root_key)

        event_data = dict(pending["event_data"])
        if pending["full_scan"]:
            event_data["file_list"] = []
        else:
            event_data["file_list"] = sorted(pending["file_list"])

        event_data["full_scan"] = pending["full_scan"]
        event = Event(EventType.MetadataScrape, event_data)
        fileitem = event_data.get("fileitem")
        root_path = str(self._field(fileitem, "path", "") or "")
        batch_id = uuid.uuid4().hex
        started_at = time.time()
        success = False
        error = ""

        try:
            logger.info("【ETK刮削完成通知】MoviePilot基础刮削开始: %s", root_path)
            type(self)._original_scrape_handler(MediaChain(), event)
            success, error = self._verify_scrape_outputs(event_data)
            if success:
                logger.info("【ETK刮削完成通知】MoviePilot基础刮削输出验证成功: %s", root_path)
            else:
                logger.error("【ETK刮削完成通知】MoviePilot基础刮削无有效输出: %s", root_path)
        except Exception as exc:
            error = str(exc)
            event_data["file_list"] = []
            logger.error("【ETK刮削完成通知】MoviePilot刮削失败: %s", exc, exc_info=True)
        with type(self)._lock:
            type(self)._running.discard(root_key)
            if not self._enabled:
                return
            following = type(self)._pending.get(key)
            if following or self._has_pending_transfer(event_data):
                following = following or pending
                following["file_list"].update(pending["file_list"])
                following["full_scan"] = following["full_scan"] or pending["full_scan"]
                following["event_data"]["mediainfo"] = self._carry_episode_group(
                    event_data.get("mediainfo"), following["event_data"].get("mediainfo"),
                )
                type(self)._pending[key] = following
                self._schedule_scrape(key, following)
                logger.info("【ETK刮削完成通知】刮削期间收到后续文件，合并后再通知ETK: %s", root_path)
                return

        payload = self._build_payload(
            event_data=event_data,
            batch_id=batch_id,
            success=success,
            error=error,
            duration=round(time.time() - started_at, 3),
        )
        self._send_webhook(payload)

        if not success:
            logger.error("【ETK刮削完成通知】批次刮削失败，不触发ETK处理: %s", root_path)

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

    def _build_payload(
        self,
        *,
        event_data: Dict[str, Any],
        batch_id: str,
        success: bool,
        error: str,
        duration: float,
    ) -> Dict[str, Any]:
        fileitem = event_data.get("fileitem")
        mediainfo = event_data.get("mediainfo")
        meta = event_data.get("meta")
        media_type = self._field(mediainfo, "type") or self._field(meta, "type")
        if hasattr(media_type, "value"):
            media_type = media_type.value
        tmdb_id = (
            self._field(mediainfo, "tmdb_id")
            or self._field(mediainfo, "tmdbid")
            or self._field(meta, "tmdb_id")
            or self._field(meta, "tmdbid")
        )
        return {
            "event": "metadata.scrape.complete",
            "batch_id": batch_id,
            "success": success,
            "error": error or None,
            "duration_seconds": duration,
            "media_type": str(media_type or ""),
            "tmdb_id": str(tmdb_id or ""),
            "episode_group": self._episode_group(mediainfo or meta),
            "root_path": str(self._field(fileitem, "path", "") or ""),
            "storage": str(self._field(fileitem, "storage", "") or ""),
            "file_list": [str(path) for path in event_data.get("file_list") or [] if path],
            "full_scan": self._is_full_scan(event_data),
        }

    def _send_webhook(self, payload: Dict[str, Any]):
        headers = {
            "Content-Type": "application/json",
            "X-Emby-Toolkit-Token": self._secret,
        }
        attempts = self._retry_count + 1
        for attempt in range(1, attempts + 1):
            try:
                response = RequestUtils(
                    headers=headers,
                    timeout=self._timeout_seconds,
                ).post_res(self._webhook_url, json=payload)
                if response and 200 <= response.status_code < 300:
                    file_count = len(payload.get("file_list") or [])
                    scope_label = f"精确文件 {file_count} 个" if file_count else "整目录"
                    message = "【ETK刮削完成通知】ETK已接收批次 %s: %s，范围: %s"
                    args = (payload["batch_id"], payload["root_path"], scope_label)
                    if self._media_identity({"type": payload.get("media_type")})[-1] == "series":
                        message += "，剧集组: %s"
                        args += (payload.get("episode_group") or "官方季",)
                    logger.info(message, *args)
                    return
                detail = response.text if response is not None else "无响应"
                logger.warning(
                    "【ETK刮削完成通知】第 %s/%s 次通知失败: %s",
                    attempt,
                    attempts,
                    detail,
                )
            except Exception as exc:
                logger.warning(
                    "【ETK刮削完成通知】第 %s/%s 次通知异常: %s",
                    attempt,
                    attempts,
                    exc,
                )
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 5))

    def stop_service(self):
        cls = type(self)
        with cls._lock:
            for pending in cls._pending.values():
                timer = pending.get("timer")
                if timer:
                    timer.cancel()
            cls._pending.clear()

            if cls._listener_installed:
                eventmanager.remove_event_listener(EventType.MetadataScrape, self._handle_scrape_event)
                if cls._original_scrape_handler is not None:
                    eventmanager.enable_event_handler(cls._original_scrape_handler)
            cls._listener_installed = False
            cls._original_scrape_handler = None
        self._enabled = False
