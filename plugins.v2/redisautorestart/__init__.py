import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from apscheduler.triggers.cron import CronTrigger

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

try:
    from app.core.config import settings
except Exception:
    settings = None


class RedisAutoRestart(_PluginBase):
    plugin_name = "Redis异常自动重启"
    plugin_desc = "检测 Redis 连接异常或自动诊断日志中的 Redis 故障，并自动重启 MoviePilot。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = "你能少吃点吗"
    author_url = "https://github.com/bingbinghj/MoviePilot-Plugins"
    plugin_config_prefix = "redisautorestart_"
    plugin_order = 52
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _notify = True
    _cron = "*/5 * * * *"
    _timeout = 5
    _direct_check = True
    _redis_url = ""
    _log_scan = False
    _log_path = ""
    _log_tail_kb = 512
    _log_keywords = "Redis连接失败\nRedis缓存，异常信息：Redis连接失败"
    _failure_threshold = 2
    _cooldown_minutes = 30
    _restart_mode = "exit"
    _restart_command = ""
    _exit_code = 1
    _restart_delay = 3
    _last_result: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify", True))
        self._cron = config.get("cron") or self._cron
        self._timeout = self.__to_int(config.get("timeout"), 5)
        self._direct_check = bool(config.get("direct_check", True))
        self._redis_url = self.__clean(config.get("redis_url"))
        self._log_scan = bool(config.get("log_scan"))
        self._log_path = self.__clean(config.get("log_path"))
        self._log_tail_kb = max(16, self.__to_int(config.get("log_tail_kb"), 512))
        self._log_keywords = config.get("log_keywords") or self._log_keywords
        self._failure_threshold = max(1, self.__to_int(config.get("failure_threshold"), 2))
        self._cooldown_minutes = max(0, self.__to_int(config.get("cooldown_minutes"), 30))
        self._restart_mode = self.__restart_mode(config.get("restart_mode"))
        self._restart_command = self.__clean(config.get("restart_command"))
        self._exit_code = self.__to_int(config.get("exit_code"), 1)
        self._restart_delay = max(0, self.__to_int(config.get("restart_delay"), 3))

        try:
            self._last_result = self.get_data("last_result") or {}
        except Exception:
            self._last_result = {}

        if self._onlyonce:
            self.check(manual=True)
            self._onlyonce = False
            self.__save_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/redis_auto_restart_check",
                "event": EventType.PluginAction,
                "desc": "立即检测 Redis 并按配置重启",
                "category": "插件命令",
                "data": {"action": "redis_auto_restart_check"},
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self.get_state():
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as err:
            logger.error(f"{self.plugin_name} Cron 表达式无效：{err}")
            return []
        return [
            {
                "id": f"{self.__class__.__name__}.check",
                "name": self.plugin_name,
                "trigger": trigger,
                "func": self.check,
                "kwargs": {},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/check",
                "endpoint": self.api_check,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即检测 Redis 并按配置重启",
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            self.__col_switch("enabled", "启用插件", 4),
                            self.__col_switch("onlyonce", "仅运行一次", 4),
                            self.__col_switch("notify", "发送通知", 4),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self.__col_text("cron", "Cron 表达式", "*/5 * * * *", 4),
                            self.__col_text("timeout", "Redis超时秒数", "5", 2, "number"),
                            self.__col_text("failure_threshold", "连续失败阈值", "2", 2, "number"),
                            self.__col_text("cooldown_minutes", "重启冷却分钟", "30", 2, "number"),
                            self.__col_text("restart_delay", "重启延迟秒数", "3", 2, "number"),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self.__col_switch("direct_check", "直接PING Redis", 4),
                            self.__col_switch("log_scan", "扫描自动诊断日志", 4),
                            self.__col_text("log_tail_kb", "日志扫描KB", "512", 4, "number"),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self.__col_text("redis_url", "Redis URL", "留空则尝试读取 MoviePilot 配置", 12),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self.__col_text("log_path", "自动诊断日志路径", "/path/to/moviepilot.log", 12),
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "log_keywords",
                                            "label": "Redis异常关键字",
                                            "rows": 3,
                                            "auto-grow": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSelect",
                                        "props": {
                                            "model": "restart_mode",
                                            "label": "重启方式",
                                            "items": [
                                                {"title": "退出进程", "value": "exit"},
                                                {"title": "执行命令", "value": "command"},
                                                {"title": "只通知不重启", "value": "notify"},
                                            ],
                                        },
                                    }
                                ],
                            },
                            self.__col_text("exit_code", "退出码", "1", 2, "number"),
                            self.__col_text("restart_command", "自定义重启命令", "docker restart moviepilot", 6),
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "cron": "*/5 * * * *",
            "timeout": 5,
            "direct_check": True,
            "redis_url": "",
            "log_scan": False,
            "log_path": "",
            "log_tail_kb": 512,
            "log_keywords": self._log_keywords,
            "failure_threshold": 2,
            "cooldown_minutes": 30,
            "restart_mode": "exit",
            "restart_command": "",
            "exit_code": 1,
            "restart_delay": 3,
        }

    def get_page(self) -> List[dict]:
        if not self._last_result:
            return [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "暂无执行记录"}}]

        status = "success" if self._last_result.get("success") else "error"
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": status,
                    "variant": "tonal",
                    "title": self._last_result.get("title") or "最近一次检测",
                    "text": self._last_result.get("message") or "",
                },
            },
            {
                "component": "VTable",
                "content": [
                    {
                        "component": "tbody",
                        "content": [
                            self.__table_row("检测时间", self._last_result.get("time")),
                            self.__table_row("连续失败", self._last_result.get("failure_count")),
                            self.__table_row("是否触发重启", "是" if self._last_result.get("restart_triggered") else "否"),
                            self.__table_row("详情", self._last_result.get("detail")),
                        ],
                    }
                ],
            },
        ]

    def stop_service(self):
        pass

    def api_check(self) -> Dict[str, Any]:
        return self.check(manual=True)

    @eventmanager.register(EventType.PluginAction)
    def remote_check(self, event: Event):
        event_data = event.event_data or {}
        if event_data.get("action") == "redis_auto_restart_check":
            self.check(manual=True)

    def check(self, manual: bool = False) -> Dict[str, Any]:
        logger.info(f"{self.plugin_name} 开始检测")
        checks = []

        if self._direct_check:
            checks.append(self.__check_redis())
        if self._log_scan:
            checks.append(self.__scan_log())

        if not checks:
            return self.__finish(False, "配置错误", "至少启用一种检测方式", "未启用 Redis PING 或日志扫描", False)

        failures = [item for item in checks if item.get("failed")]
        inconclusive = [item for item in checks if item.get("inconclusive")]
        detail = "\n".join(item.get("message") or "" for item in checks)

        if not failures:
            self.__save_runtime_state({"failure_count": 0})
            title = "Redis检测正常" if not inconclusive else "Redis检测未发现异常"
            return self.__finish(True, title, "未检测到 Redis 异常", detail, False)

        state = self.__runtime_state()
        failure_count = self.__to_int(state.get("failure_count"), 0) + 1
        self.__save_runtime_state({"failure_count": failure_count, "last_failure_at": time.time()})

        message = f"检测到 Redis 异常，连续失败 {failure_count}/{self._failure_threshold}"
        if failure_count < self._failure_threshold:
            return self.__finish(False, "Redis异常", message, detail, False, failure_count)

        allowed, cooldown_message = self.__restart_allowed(state)
        if not allowed:
            return self.__finish(False, "Redis异常", f"{message}，{cooldown_message}", detail, False, failure_count)

        restart_message = self.__trigger_restart(detail)
        self.__save_runtime_state({
            "failure_count": failure_count,
            "last_restart_at": time.time(),
        })
        return self.__finish(False, "Redis异常，已触发重启", f"{message}，{restart_message}", detail, True, failure_count)

    def __check_redis(self) -> Dict[str, Any]:
        try:
            import redis
        except Exception as err:
            return {"failed": False, "inconclusive": True, "message": f"Redis PING：无法导入 redis 模块：{err}"}

        redis_url = self._redis_url or self.__settings_redis_url()
        if not redis_url:
            return {"failed": False, "inconclusive": True, "message": "Redis PING：未配置 Redis URL，且未能从 MoviePilot 配置读取"}

        try:
            client = redis.Redis.from_url(redis_url, socket_timeout=self._timeout, socket_connect_timeout=self._timeout)
            pong = client.ping()
            return {"failed": not pong, "message": f"Redis PING：{'正常' if pong else '失败'}"}
        except Exception as err:
            logger.warning(f"{self.plugin_name} Redis PING 失败：{err}")
            return {"failed": True, "message": f"Redis PING：失败，{err}"}

    def __scan_log(self) -> Dict[str, Any]:
        if not self._log_path:
            return {"failed": False, "inconclusive": True, "message": "日志扫描：未配置日志路径"}

        path = Path(self._log_path)
        if not path.exists() or not path.is_file():
            return {"failed": False, "inconclusive": True, "message": f"日志扫描：日志文件不存在：{path}"}

        try:
            text = self.__tail_text(path, self._log_tail_kb * 1024)
        except Exception as err:
            return {"failed": False, "inconclusive": True, "message": f"日志扫描：读取失败：{err}"}

        keywords = [line.strip() for line in (self._log_keywords or "").splitlines() if line.strip()]
        matched = []
        for keyword in keywords:
            if keyword in text or re.search(re.escape(keyword), text):
                matched.append(keyword)

        if matched:
            return {"failed": True, "message": f"日志扫描：命中 Redis 异常关键字：{', '.join(matched)}"}
        return {"failed": False, "message": "日志扫描：未命中 Redis 异常关键字"}

    def __trigger_restart(self, detail: str) -> str:
        if self._notify:
            try:
                self.post_message(title=f"{self.plugin_name}：触发重启", text=detail)
            except Exception as err:
                logger.warning(f"{self.plugin_name} 发送重启通知失败：{err}")

        if self._restart_mode == "notify":
            return "当前配置为只通知不重启"

        if self._restart_mode == "command":
            if not self._restart_command:
                return "未配置自定义重启命令，未执行重启"
            subprocess.Popen(self._restart_command, shell=True)
            return f"已执行自定义重启命令：{self._restart_command}"

        delay = self._restart_delay
        exit_code = self._exit_code

        def delayed_exit():
            if delay > 0:
                time.sleep(delay)
            logger.warning(f"{self.plugin_name} 正在退出 MoviePilot 进程，exit_code={exit_code}")
            os._exit(exit_code)

        threading.Thread(target=delayed_exit, daemon=True).start()
        return f"将在 {delay} 秒后退出 MoviePilot 进程，等待外部守护或 Docker 重启"

    def __restart_allowed(self, state: Dict[str, Any]) -> Tuple[bool, str]:
        if self._cooldown_minutes <= 0:
            return True, ""
        last_restart_at = float(state.get("last_restart_at") or 0)
        if last_restart_at <= 0:
            return True, ""
        elapsed = time.time() - last_restart_at
        cooldown_seconds = self._cooldown_minutes * 60
        if elapsed >= cooldown_seconds:
            return True, ""
        remain = int((cooldown_seconds - elapsed) / 60) + 1
        return False, f"仍处于重启冷却期，约 {remain} 分钟后可再次重启"

    def __settings_redis_url(self) -> str:
        if not settings:
            return ""

        for attr in ("REDIS_URL", "CACHE_REDIS_URL", "REDIS_URI"):
            value = getattr(settings, attr, None)
            if value:
                return str(value)

        host = self.__first_setting("REDIS_HOST", "CACHE_REDIS_HOST")
        if not host:
            return ""
        port = self.__first_setting("REDIS_PORT", "CACHE_REDIS_PORT") or 6379
        db = self.__first_setting("REDIS_DB", "CACHE_REDIS_DB") or 0
        username = self.__first_setting("REDIS_USERNAME", "CACHE_REDIS_USERNAME")
        password = self.__first_setting("REDIS_PASSWORD", "CACHE_REDIS_PASSWORD")

        auth = ""
        if username and password:
            auth = f"{quote(str(username))}:{quote(str(password))}@"
        elif password:
            auth = f":{quote(str(password))}@"
        return f"redis://{auth}{host}:{port}/{db}"

    @staticmethod
    def __first_setting(*names: str) -> Any:
        if not settings:
            return None
        for name in names:
            value = getattr(settings, name, None)
            if value not in (None, ""):
                return value
        return None

    @staticmethod
    def __tail_text(path: Path, max_bytes: int) -> str:
        size = path.stat().st_size
        with path.open("rb") as file:
            if size > max_bytes:
                file.seek(-max_bytes, os.SEEK_END)
            data = file.read()
        return data.decode("utf-8", errors="ignore")

    def __finish(
        self,
        success: bool,
        title: str,
        message: str,
        detail: str,
        restart_triggered: bool,
        failure_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        if failure_count is None:
            failure_count = self.__to_int(self.__runtime_state().get("failure_count"), 0)
        result = {
            "success": success,
            "title": title,
            "message": message,
            "detail": detail,
            "restart_triggered": restart_triggered,
            "failure_count": failure_count,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._last_result = result
        try:
            self.save_data("last_result", result)
        except Exception as err:
            logger.warning(f"{self.plugin_name} 保存执行结果失败：{err}")

        if self._notify and (restart_triggered or not success):
            try:
                self.post_message(title=f"{self.plugin_name}：{title}", text=f"{message}\n{detail}".strip())
            except Exception as err:
                logger.warning(f"{self.plugin_name} 发送通知失败：{err}")

        if success:
            logger.info(f"{self.plugin_name} {title}：{message}")
        else:
            logger.warning(f"{self.plugin_name} {title}：{message}，详情：{detail}")
        return result

    def __runtime_state(self) -> Dict[str, Any]:
        try:
            return self.get_data("runtime_state") or {}
        except Exception:
            return {}

    def __save_runtime_state(self, data: Dict[str, Any]):
        state = self.__runtime_state()
        state.update(data)
        try:
            self.save_data("runtime_state", state)
        except Exception as err:
            logger.warning(f"{self.plugin_name} 保存运行状态失败：{err}")

    def __save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cron": self._cron,
            "timeout": self._timeout,
            "direct_check": self._direct_check,
            "redis_url": self._redis_url,
            "log_scan": self._log_scan,
            "log_path": self._log_path,
            "log_tail_kb": self._log_tail_kb,
            "log_keywords": self._log_keywords,
            "failure_threshold": self._failure_threshold,
            "cooldown_minutes": self._cooldown_minutes,
            "restart_mode": self._restart_mode,
            "restart_command": self._restart_command,
            "exit_code": self._exit_code,
            "restart_delay": self._restart_delay,
        })

    @staticmethod
    def __col_switch(model: str, label: str, md: int) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{"component": "VSwitch", "props": {"model": model, "label": label}}],
        }

    @staticmethod
    def __col_text(model: str, label: str, placeholder: str, md: int, field_type: str = "text") -> dict:
        props = {"model": model, "label": label, "placeholder": placeholder}
        if field_type:
            props["type"] = field_type
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{"component": "VTextField", "props": props}],
        }

    @staticmethod
    def __table_row(name: str, value: Any) -> dict:
        return {
            "component": "tr",
            "content": [
                {"component": "td", "props": {"class": "text-subtitle-2"}, "text": name},
                {"component": "td", "text": str(value or "-")},
            ],
        }

    @staticmethod
    def __restart_mode(value: Any) -> str:
        value = str(value or "exit").strip().lower()
        return value if value in {"exit", "command", "notify"} else "exit"

    @staticmethod
    def __clean(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
