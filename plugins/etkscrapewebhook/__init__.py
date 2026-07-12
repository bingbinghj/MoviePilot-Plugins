import hashlib
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.chain.media import MediaChain
from app.core.config import settings
from app.core.event import Event, eventmanager
from app.log import LoggerManager, logger
from app.plugins import _PluginBase
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class ETKScrapeWebhook(_PluginBase):
    plugin_name = "ETK刮削完成通知"
    plugin_desc = "合并MoviePilot重复刮削请求，并在实际刮削完成后通知ETK。"
    plugin_icon = "webhook.png"
    plugin_version = "1.0.5"
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
    _lock = threading.RLock()

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._webhook_url = str(config.get("webhook_url") or "").strip()
        self._secret = str(config.get("secret") or "").strip()
        self._debounce_seconds = max(1, int(config.get("debounce_seconds") or 10))
        self._timeout_seconds = max(1, int(config.get("timeout_seconds") or 15))
        self._retry_count = max(0, int(config.get("retry_count") or 2))

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
        except OSError as exc:
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
        logger.info("【ETK刮削完成通知】已接管MoviePilot元数据刮削事件")

    def _handle_scrape_event(self, event: Event):
        return self._enqueue_scrape(event)

    @staticmethod
    def _field(value: Any, name: str, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _event_key(cls, event_data: Dict[str, Any]) -> Optional[str]:
        fileitem = event_data.get("fileitem")
        path = str(cls._field(fileitem, "path", "") or "").strip()
        storage = str(cls._field(fileitem, "storage", "") or "").strip()
        if not path:
            return None
        return hashlib.sha256(f"{storage}\n{path}".encode("utf-8")).hexdigest()

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
                timer = pending.get("timer")
                if timer:
                    timer.cancel()
                pending["file_list"].update(incoming_files)
                pending["full_scan"] = pending["full_scan"] or not incoming_files
                pending["event_data"].update(event_data)
            else:
                pending = {
                    "event_data": event_data,
                    "file_list": set(incoming_files),
                    "full_scan": not incoming_files,
                    "timer": None,
                }
                type(self)._pending[key] = pending

            timer = threading.Timer(self._debounce_seconds, self._flush_scrape, args=(key,))
            timer.daemon = True
            pending["timer"] = timer
            timer.start()

        fileitem = event_data.get("fileitem")
        logger.info(
            "【ETK刮削完成通知】已合并刮削请求: %s，等待 %s 秒",
            self._field(fileitem, "path", "未知路径"),
            self._debounce_seconds,
        )
        return None

    def _flush_scrape(self, key: str):
        with type(self)._lock:
            pending = type(self)._pending.pop(key, None)
        if not pending or not self._enabled:
            return

        event_data = dict(pending["event_data"])
        if pending["full_scan"]:
            event_data["file_list"] = []
        else:
            event_data["file_list"] = sorted(pending["file_list"])

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
            logger.error("【ETK刮削完成通知】MoviePilot刮削失败: %s", exc, exc_info=True)
        finally:
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

    @classmethod
    def _verify_scrape_outputs(cls, event_data: Dict[str, Any]) -> Tuple[bool, str]:
        fileitem = event_data.get("fileitem")
        root_path = Path(str(cls._field(fileitem, "path", "") or ""))
        if not root_path.exists():
            return False, f"MoviePilot刮削根路径不存在: {root_path}"

        media_extensions = {str(ext).lower() for ext in settings.RMT_MEDIAEXT}
        file_list = [
            Path(str(path))
            for path in event_data.get("file_list") or []
            if path and Path(str(path)).suffix.lower() in media_extensions
        ]
        expected_nfos = [path.with_suffix(".nfo") for path in file_list]
        if expected_nfos:
            existing_count = sum(path.is_file() for path in expected_nfos)
            if existing_count == len(expected_nfos):
                return True, ""
            return False, f"MoviePilot未生成完整分集NFO: {existing_count}/{len(expected_nfos)}"

        if root_path.is_file():
            nfo_path = root_path.with_suffix(".nfo")
            if nfo_path.is_file():
                return True, ""
            return False, f"MoviePilot未生成NFO: {nfo_path}"

        strm_files = sorted(root_path.rglob("*.strm"))
        if strm_files:
            existing_count = sum(path.with_suffix(".nfo").is_file() for path in strm_files)
            if existing_count == len(strm_files):
                return True, ""
            return False, f"MoviePilot未生成完整STRM NFO: {existing_count}/{len(strm_files)}"

        for _, _, filenames in os.walk(root_path):
            if any(filename.lower().endswith(".nfo") for filename in filenames):
                return True, ""
        return False, f"MoviePilot刮削目录内未找到NFO: {root_path}"

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
            "root_path": str(self._field(fileitem, "path", "") or ""),
            "storage": str(self._field(fileitem, "storage", "") or ""),
            "file_list": [str(path) for path in event_data.get("file_list") or [] if path],
            "full_scan": not bool(event_data.get("file_list")),
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
                    logger.info(
                        "【ETK刮削完成通知】ETK已接收批次 %s: %s",
                        payload["batch_id"],
                        payload["root_path"],
                    )
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
