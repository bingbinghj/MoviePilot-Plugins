import html
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from apscheduler.triggers.cron import CronTrigger

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType


class TemoxSignin(_PluginBase):
    plugin_name = "中国特摄联盟自动登录"
    plugin_desc = "每天自动登录中国特摄联盟，并处理站点算术验证。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.1"
    plugin_author = "你能少吃点吗"
    author_url = "https://github.com/jxxghp/MoviePilot-Plugins"
    plugin_config_prefix = "temoxsignin_"
    plugin_order = 50
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _notify = True
    _site_url = "http://bt.temox.com:8080"
    _username = ""
    _password = ""
    _cron = "15 8 * * *"
    _timeout = 20
    _questionid = "0"
    _security_answer = ""
    _last_result: Dict[str, Any] = {}
    DAILY_REWARD_MESSAGE = "每天登录 经验+1p 人气+1点 分享度+1 人品+1p"

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify", True))
        self._site_url = (config.get("site_url") or self._site_url).rstrip("/")
        self._username = config.get("username") or ""
        self._password = config.get("password") or ""
        self._cron = config.get("cron") or self._cron
        self._timeout = self._to_int(config.get("timeout"), 20)
        self._questionid = str(config.get("questionid") or "0")
        self._security_answer = config.get("security_answer") or ""

        try:
            self._last_result = self.get_data("last_result") or {}
        except Exception:
            self._last_result = {}

        if self._onlyonce:
            self.signin(manual=True)
            self._onlyonce = False
            self.__save_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/temox_signin",
                "event": EventType.PluginAction,
                "desc": "立即登录中国特摄联盟",
                "category": "插件命令",
                "data": {"action": "temox_signin"},
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
                "id": f"{self.__class__.__name__}.signin",
                "name": self.plugin_name,
                "trigger": trigger,
                "func": self.signin,
                "kwargs": {},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/signin",
                "endpoint": self.api_signin,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即登录中国特摄联盟",
                "description": "触发一次中国特摄联盟登录任务",
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
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "enabled",
                                            "label": "启用插件",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "onlyonce",
                                            "label": "仅运行一次",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "notify",
                                            "label": "发送通知",
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
                                            "model": "site_url",
                                            "label": "站点地址",
                                            "placeholder": "http://bt.temox.com:8080",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "Cron 表达式",
                                            "placeholder": "15 8 * * *",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "timeout",
                                            "label": "请求超时秒数",
                                            "type": "number",
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
                                            "model": "username",
                                            "label": "用户名",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 6},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "password",
                                            "label": "密码",
                                            "type": "password",
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
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "questionid",
                                            "label": "安全提问编号",
                                            "placeholder": "0",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 8},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "security_answer",
                                            "label": "安全提问答案",
                                            "type": "password",
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
            "onlyonce": False,
            "notify": True,
            "site_url": "http://bt.temox.com:8080",
            "username": "",
            "password": "",
            "cron": "15 8 * * *",
            "timeout": 20,
            "questionid": "0",
            "security_answer": "",
        }

    def get_page(self) -> List[dict]:
        if not self._last_result:
            return [
                {
                    "component": "VAlert",
                    "props": {
                        "type": "info",
                        "variant": "tonal",
                        "text": "暂无执行记录",
                    },
                }
            ]

        status = "success" if self._last_result.get("success") else "error"
        return [
            {
                "component": "VAlert",
                "props": {
                    "type": status,
                    "variant": "tonal",
                    "title": self._last_result.get("title") or "最近一次执行结果",
                    "text": self._last_result.get("message") or "",
                },
            },
            {
                "component": "VTable",
                "content": [
                    {
                        "component": "tbody",
                        "content": [
                            self.__table_row("执行时间", self._last_result.get("time")),
                            self.__table_row("站点地址", self._last_result.get("site_url")),
                            self.__table_row("账号", self._last_result.get("username")),
                        ],
                    }
                ],
            },
        ]

    def stop_service(self):
        pass

    def api_signin(self) -> Dict[str, Any]:
        return self.signin(manual=True)

    @eventmanager.register(EventType.PluginAction)
    def remote_signin(self, event: Event):
        event_data = event.event_data or {}
        if event_data.get("action") != "temox_signin":
            return
        self.signin(manual=True)

    def signin(self, manual: bool = False) -> Dict[str, Any]:
        if not self._username or not self._password:
            return self.__finish(False, "配置不完整", "请先配置中国特摄联盟用户名和密码")

        logger.info(f"{self.plugin_name} 开始执行登录任务")

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        login_url = urljoin(f"{self._site_url}/", "member.php?mod=logging&action=login")

        try:
            response = self.__get_with_gate(session, login_url)
            text = self.__response_text(response)

            form = self.__extract_login_form(text)
            if not form:
                if self.__is_logged_in(text):
                    message = self.__success_message("当前会话已处于登录状态", text)
                    return self.__finish(True, "登录成功", message)
                return self.__finish(False, "登录失败", "未能在页面中找到 Discuz 登录表单")

            action, payload = form
            post_url = urljoin(response.url or login_url, action)
            payload.update({
                "username": self._username,
                "password": self._password,
                "questionid": self._questionid or "0",
                "cookietime": "2592000",
                "loginsubmit": "true",
            })

            if self._questionid and self._questionid != "0":
                payload["answer"] = self._security_answer
            else:
                payload.pop("answer", None)

            login_response = session.post(
                post_url,
                data=payload,
                headers={"Referer": login_url},
                timeout=self._timeout,
            )
            login_text = self.__response_text(login_response)

            check_url = urljoin(f"{self._site_url}/", "forum.php")
            check_response = self.__get_with_gate(session, check_url)
            check_text = self.__response_text(check_response)

            if self.__is_logged_in(login_text) or self.__is_logged_in(check_text):
                message = self.__success_message(
                    self.__extract_success_message(login_text) or "登录成功，已获取登录态",
                    login_text,
                    check_text,
                )
                return self.__finish(True, "登录成功", message)

            message = self.__extract_error_message(login_text) or "登录后未检测到有效登录态"
            return self.__finish(False, "登录失败", message)

        except requests.RequestException as err:
            logger.error(f"{self.plugin_name} 请求失败：{err}")
            return self.__finish(False, "请求失败", str(err))
        except Exception as err:
            logger.exception(f"{self.plugin_name} 执行异常：{err}")
            return self.__finish(False, "执行异常", str(err))

    def __get_with_gate(self, session: requests.Session, url: str) -> requests.Response:
        response = session.get(url, timeout=self._timeout)
        text = self.__response_text(response)

        if self.__is_reload_page(text):
            time.sleep(1.2)
            response = session.get(url, timeout=self._timeout)
            text = self.__response_text(response)

        for _ in range(5):
            answer = self.__extract_math_answer(text)
            if answer is None:
                break
            logger.info(f"{self.plugin_name} 检测到算术验证，提交答案：{answer}")
            response = session.post(
                response.url or url,
                data={"answer": str(answer), "secqsubmit": " Submit "},
                headers={"Referer": url},
                timeout=self._timeout,
            )
            text = self.__response_text(response)

            if self.__is_reload_page(text):
                time.sleep(1.2)
                response = session.get(url, timeout=self._timeout)
                text = self.__response_text(response)

        return response

    @staticmethod
    def __response_text(response: requests.Response) -> str:
        content = response.content or b""
        encoding = response.encoding

        meta = re.search(br"charset=[\"']?([a-zA-Z0-9_\-]+)", content[:1000], re.I)
        if meta:
            encoding = meta.group(1).decode("ascii", errors="ignore")
        elif not encoding or encoding.lower() == "iso-8859-1":
            encoding = response.apparent_encoding or "utf-8"

        try:
            return content.decode(encoding or "utf-8", errors="replace")
        except LookupError:
            return content.decode("utf-8", errors="replace")

    @staticmethod
    def __is_reload_page(text: str) -> bool:
        return "页面重载开启" in text or "document.location.reload()" in text

    @staticmethod
    def __extract_math_answer(text: str) -> Optional[int]:
        if 'name="answer"' not in text and "name='answer'" not in text:
            return None
        if "secqsubmit" not in text:
            return None

        match = re.search(r"((?:\d+\s*\+\s*)+\d+)\s*=\s*\?", text)
        if not match:
            return None

        return sum(int(num) for num in re.findall(r"\d+", match.group(1)))

    def __extract_login_form(self, text: str) -> Optional[Tuple[str, Dict[str, str]]]:
        for match in re.finditer(r"<form\b(?P<attrs>[^>]*)>(?P<body>.*?)</form>", text, re.I | re.S):
            attrs = match.group("attrs")
            body = match.group("body")
            action = self.__get_attr(attrs, "action") or ""
            form_id = self.__get_attr(attrs, "id") or ""
            form_name = self.__get_attr(attrs, "name") or ""

            if not (
                "loginform" in form_id
                or form_name == "login"
                or "mod=logging" in html.unescape(action)
            ):
                continue

            payload: Dict[str, str] = {}
            for input_match in re.finditer(r"<input\b[^>]*>", body, re.I | re.S):
                input_tag = input_match.group(0)
                input_type = (self.__get_attr(input_tag, "type") or "text").lower()
                input_name = self.__get_attr(input_tag, "name")
                if not input_name:
                    continue
                if input_type not in {"hidden", "checkbox", "submit"}:
                    continue
                payload[input_name] = self.__get_attr(input_tag, "value") or ""

            return html.unescape(action), payload

        return None

    @staticmethod
    def __get_attr(tag: str, name: str) -> Optional[str]:
        pattern = rf"""{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))"""
        match = re.search(pattern, tag, re.I)
        if not match:
            return None
        value = next(group for group in match.groups() if group is not None)
        return html.unescape(value)

    @staticmethod
    def __is_logged_in(text: str) -> bool:
        if re.search(r"discuz_uid\s*=\s*'([1-9]\d*)'", text):
            return True
        return any(marker in text for marker in [
            "login_succeed",
            "欢迎您回来",
            "退出</a>",
            "title=\"访问我的空间\"",
        ])

    @staticmethod
    def __extract_success_message(text: str) -> Optional[str]:
        patterns = [
            r"<p[^>]*class=[\"']?succeedmessage[\"']?[^>]*>(.*?)</p>",
            r"id=[\"']succeedmessage[^>]*>(.*?)</",
            r"欢迎您回来[^<\r\n]*",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.S)
            if match:
                return TemoxSignin.__clean_text(match.group(1) if match.groups() else match.group(0))
        return None

    @staticmethod
    def __extract_error_message(text: str) -> Optional[str]:
        patterns = [
            r"<div[^>]*class=[\"'][^\"']*alert_error[^\"']*[\"'][^>]*>(.*?)</div>",
            r"<em[^>]*id=[\"']returnmessage[^\"']*[\"'][^>]*>(.*?)</em>",
            r"id=[\"']messagetext[\"'][^>]*>.*?<p>(.*?)</p>",
            r"登录失败[^<\r\n]*",
            r"密码错误[^<\r\n]*",
            r"抱歉[^<\r\n]*",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.S)
            if match:
                return TemoxSignin.__clean_text(match.group(1) if match.groups() else match.group(0))
        return None

    @classmethod
    def __success_message(cls, message: str, *texts: str) -> str:
        base = cls.__clean_text(message or "") or "登录成功，已获取登录态"
        reward = cls.__extract_daily_reward_message(*texts) or cls.DAILY_REWARD_MESSAGE
        if cls.__has_daily_reward_message(base):
            return base
        return f"{base}。{reward}"

    @classmethod
    def __extract_daily_reward_message(cls, *texts: str) -> Optional[str]:
        pattern = r"每天登录\s*经验\s*\+\s*\d+\s*p\s*人气\s*\+\s*\d+\s*点\s*分享度\s*\+\s*\d+\s*人品\s*\+\s*\d+\s*p"
        for text in texts:
            cleaned = cls.__clean_text(text or "")
            match = re.search(pattern, cleaned, re.I)
            if match:
                return re.sub(r"\s+", " ", match.group(0)).strip()
        return None

    @classmethod
    def __has_daily_reward_message(cls, text: str) -> bool:
        compact = re.sub(r"\s+", "", text or "")
        return all(marker in compact for marker in ("每天登录", "经验+", "人气+", "分享度+", "人品+"))

    @staticmethod
    def __clean_text(value: str) -> str:
        value = re.sub(r"<script\b.*?</script>", "", value, flags=re.I | re.S)
        value = re.sub(r"<[^>]+>", "", value)
        value = html.unescape(value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def __finish(self, success: bool, title: str, message: str) -> Dict[str, Any]:
        result = {
            "success": success,
            "title": title,
            "message": message,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "site_url": self._site_url,
            "username": self._username,
        }
        self._last_result = result

        try:
            self.save_data("last_result", result)
        except Exception as err:
            logger.warning(f"{self.plugin_name} 保存执行结果失败：{err}")

        if self._notify:
            try:
                self.post_message(title=f"{self.plugin_name}：{title}", text=message)
            except Exception as err:
                logger.warning(f"{self.plugin_name} 发送通知失败：{err}")

        if success:
            logger.info(f"{self.plugin_name} {title}：{message}")
        else:
            logger.warning(f"{self.plugin_name} {title}：{message}")

        return result

    def __save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "site_url": self._site_url,
            "username": self._username,
            "password": self._password,
            "cron": self._cron,
            "timeout": self._timeout,
            "questionid": self._questionid,
            "security_answer": self._security_answer,
        })

    @staticmethod
    def __table_row(name: str, value: Any) -> dict:
        return {
            "component": "tr",
            "content": [
                {
                    "component": "td",
                    "props": {"class": "text-subtitle-2"},
                    "text": name,
                },
                {
                    "component": "td",
                    "text": str(value or "-"),
                },
            ],
        }

    @staticmethod
    def _to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
