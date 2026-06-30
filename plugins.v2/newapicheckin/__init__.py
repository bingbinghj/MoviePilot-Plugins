import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from apscheduler.triggers.cron import CronTrigger

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except Exception:
    curl_requests = None
    HAS_CURL_CFFI = False

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except Exception:
    cloudscraper = None
    HAS_CLOUDSCRAPER = False


class NewApiCheckin(_PluginBase):
    plugin_name = "New API每日签到"
    plugin_desc = "支持多个 New API 站点每日签到，可选择 Linux.do 账号密码或 Cookie 认证，并兼容 Cloudflare 防护。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.2"
    plugin_author = "你能少吃点吗"
    author_url = "https://github.com/bingbinghj/MoviePilot-Plugins"
    plugin_config_prefix = "newapicheckin_"
    plugin_order = 51
    auth_level = 1

    _enabled = False
    _onlyonce = False
    _notify = True
    _cron = "25 8 * * *"
    _timeout = 30
    _auth_mode = "linuxdo"
    _sites = "AnyRouter|anyrouter\nHotaru|hotaru"
    _linuxdo_username = ""
    _linuxdo_password = ""
    _cookie = ""
    _api_user = ""
    _cf_bypass = True
    _accounts_json = "[]"
    _providers_json = "{}"
    _last_result: Dict[str, Any] = {}

    DEFAULT_PROVIDERS = {
        "anyrouter": {"origin": "https://anyrouter.top"},
        "wong": {"origin": "https://wzw.pp.ua"},
        "x666": {"origin": "https://x666.me"},
        "huan666": {"origin": "https://ai.huan666.de"},
        "kfc": {"origin": "https://kfc-api.sxxe.net"},
        "hotaru": {"origin": "https://hotaruapi.com", "linuxdo_client_id": "qVGkHnU8fLzJVEMgHCuNUCYifUQwePWn"},
        "elysiver": {
            "origin": "https://elysiver.h-e.top",
            "linuxdo_client_id": "E2eaCQVl9iecd4aJBeTKedXfeKiJpSPF",
            "linuxdo_auth_redirect_path": "/oauth-redirect.html**",
        },
        "2020111_xyz": {
            "origin": "https://api.2020111.xyz",
            "linuxdo_client_id": "gnyvfmAfXrnYrt9ierq3Onj1ADvdVmmm",
        },
        "yyds_215_im": {
            "origin": "https://yyds.215.im",
            "linuxdo_client_id": "BvCzH7KoNBVpQIfdWCgUMIGaPMOpgbwI",
        },
        "freeapi_dgbmc_top": {
            "origin": "https://freeapi.dgbmc.top",
            "linuxdo_client_id": "brvJ43mVybVm6j3k3NYT7gCZJsZYNDCG",
        },
        "zuodachen_zdc_mom": {
            "origin": "https://zuodachen.zdc.mom",
            "linuxdo_client_id": "SlYHFegF69I3DdRCPvmgdfghDxxis9h0",
        },
        "callxyq_xyz": {
            "origin": "https://callxyq.xyz",
            "linuxdo_client_id": "GBFGsKRHGmlUUHNKBodEqisSqxhalVtE",
        },
        "sorai_me": {
            "origin": "https://newapi.sorai.me",
            "linuxdo_client_id": "2MHHdMV5TNrb11ichVnmII2HAgL5kPZr",
        },
        "muyuan_do": {
            "origin": "https://muyuan.do",
            "linuxdo_client_id": "BhXQoUAlShhv8gX3J7AwTIYflzanZghI",
        },
        "925214_xyz": {
            "origin": "https://api.925214.xyz",
            "linuxdo_client_id": "TiWkKaSK5jZ2P7n6NqlWxrh8JjjSMYWb",
        },
        "takeapi": {
            "origin": "https://codex.661118.xyz",
            "linuxdo_client_id": "CeGKoyvGjd9JuUYOz57qbOqcM3ur3Y69",
        },
        "thatapi": {
            "origin": "https://gyapi.zxiaoruan.cn",
            "linuxdo_client_id": "doAqU5TVU6L7sXudST9MQ102aaJObESS",
        },
        "duckcoding": {
            "origin": "https://duckcoding.ai",
            "linuxdo_client_id": "MGPwGpfcyKGHsdnsY0BMpt6VZPrkxOBd",
        },
        "free-duckcoding": {
            "origin": "https://free.duckcoding.ai",
            "linuxdo_client_id": "XNJfOdoSeXkcx80mDydoheJ0nZS4tjIf",
        },
    }

    DEFAULT_ACCOUNT_EXAMPLE = json.dumps([
        {
            "name": "AnyRouter",
            "provider": "anyrouter",
            "api_user": "123",
            "system_access_token": "sk-xxxxxxxxxxxxxxxx",
        },
        {
            "name": "自定义站点",
            "origin": "https://example.com",
            "api_user": "123",
            "cookies": {"session": "new-api-session-value"},
        },
        {
            "name": "Linux.do Cookie OAuth",
            "provider": "hotaru",
            "linuxdo_cookies": "_t=linuxdo_session_value",
        },
    ], ensure_ascii=False, indent=2)

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify", True))
        self._cron = config.get("cron") or self._cron
        self._timeout = self.__to_int(config.get("timeout"), 30)
        self._auth_mode = config.get("auth_mode") or self._auth_mode
        self._sites = config.get("sites") or self._sites
        self._linuxdo_username = config.get("linuxdo_username") or ""
        self._linuxdo_password = config.get("linuxdo_password") or ""
        self._cookie = config.get("cookie") or ""
        self._api_user = config.get("api_user") or ""
        self._cf_bypass = bool(config.get("cf_bypass", True))
        self._accounts_json = config.get("accounts_json") or self.DEFAULT_ACCOUNT_EXAMPLE
        self._providers_json = config.get("providers_json") or "{}"

        try:
            self._last_result = self.get_data("last_result") or {}
        except Exception:
            self._last_result = {}

        if self._onlyonce:
            self.checkin(manual=True)
            self._onlyonce = False
            self.__save_config()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/newapi_checkin",
                "event": EventType.PluginAction,
                "desc": "立即执行 New API 签到",
                "category": "插件命令",
                "data": {"action": "newapi_checkin"},
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
                "id": f"{self.__class__.__name__}.checkin",
                "name": self.plugin_name,
                "trigger": trigger,
                "func": self.checkin,
                "kwargs": {},
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/checkin",
                "endpoint": self.api_checkin,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行 New API 签到",
                "description": "触发一次多站点 New API 签到",
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
                            self.__col_switch("cf_bypass", "Cloudflare兼容", 12),
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
                                            "model": "cron",
                                            "label": "Cron 表达式",
                                            "placeholder": "25 8 * * *",
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
                                        "component": "VSelect",
                                        "props": {
                                            "model": "auth_mode",
                                            "label": "认证方式",
                                            "items": [
                                                {"title": "Linux.do账号密码", "value": "linuxdo"},
                                                {"title": "Cookie", "value": "cookie"},
                                            ],
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
                                            "model": "api_user",
                                            "label": "New API用户ID",
                                            "placeholder": "Cookie方式必填，可在 Local Storage 的 user.id 获取",
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
                                            "model": "linuxdo_username",
                                            "label": "Linux.do用户名",
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
                                            "model": "linuxdo_password",
                                            "label": "Linux.do密码",
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "sites",
                                            "label": "站点列表",
                                            "placeholder": "每行一个：名称|provider或站点URL，例如 AnyRouter|anyrouter",
                                            "rows": 8,
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie",
                                            "label": "Cookie",
                                            "placeholder": "Cookie方式填写 New API 站点 Cookie，例如 session=xxx；Linux.do方式可留空",
                                            "rows": 6,
                                            "auto-grow": True,
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "cron": "25 8 * * *",
            "timeout": 30,
            "auth_mode": "linuxdo",
            "sites": "AnyRouter|anyrouter\nHotaru|hotaru",
            "linuxdo_username": "",
            "linuxdo_password": "",
            "api_user": "",
            "cookie": "",
            "cf_bypass": True,
        }

    def get_page(self) -> List[dict]:
        if not self._last_result:
            return [
                {
                    "component": "VAlert",
                    "props": {"type": "info", "variant": "tonal", "text": "暂无执行记录"},
                }
            ]

        rows = []
        for item in self._last_result.get("items", []):
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": item.get("name") or "-"},
                    {"component": "td", "text": item.get("origin") or "-"},
                    {"component": "td", "text": "成功" if item.get("success") else "失败"},
                    {"component": "td", "text": item.get("message") or "-"},
                ],
            })

        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "success" if self._last_result.get("success") else "error",
                    "variant": "tonal",
                    "title": self._last_result.get("title") or "最近一次执行结果",
                    "text": self._last_result.get("message") or "",
                },
            },
            {
                "component": "VTable",
                "content": [
                    {
                        "component": "thead",
                        "content": [
                            {
                                "component": "tr",
                                "content": [
                                    {"component": "th", "text": "名称"},
                                    {"component": "th", "text": "站点"},
                                    {"component": "th", "text": "状态"},
                                    {"component": "th", "text": "结果"},
                                ],
                            }
                        ],
                    },
                    {"component": "tbody", "content": rows},
                ],
            },
        ]

    def stop_service(self):
        pass

    def api_checkin(self) -> Dict[str, Any]:
        return self.checkin(manual=True)

    @eventmanager.register(EventType.PluginAction)
    def remote_checkin(self, event: Event):
        event_data = event.event_data or {}
        if event_data.get("action") == "newapi_checkin":
            self.checkin(manual=True)

    def checkin(self, manual: bool = False) -> Dict[str, Any]:
        logger.info(f"{self.plugin_name} 开始执行")
        try:
            providers = self.__load_providers()
            accounts = self.__build_accounts_from_form(providers)
        except ValueError as err:
            return self.__finish(False, "配置错误", str(err), [])

        if not accounts:
            return self.__finish(False, "配置错误", "账号配置为空", [])

        items = []
        for index, account in enumerate(accounts, start=1):
            if not isinstance(account, dict):
                items.append(self.__item(False, f"账号 {index}", "", "账号配置必须是 JSON 对象"))
                continue
            item = self.__run_one(account, providers, index)
            items.append(item)

        success_count = len([item for item in items if item.get("success")])
        total = len(items)
        ok = success_count == total and total > 0
        title = "签到完成" if ok else "签到部分失败"
        message = f"成功 {success_count}/{total}"
        return self.__finish(ok, title, message, items)

    def __run_one(self, account: Dict[str, Any], providers: Dict[str, Dict[str, Any]], index: int) -> Dict[str, Any]:
        provider = str(account.get("provider") or "custom")
        name = account.get("name") or f"{provider} {index}"
        try:
            cfg = self.__merge_provider_config(account, providers)
            origin = cfg["origin"].rstrip("/")
            session = self.__new_session(account)
            session.headers.update(self.__common_headers(account))

            linuxdo_cookies = account.get("linuxdo_cookies") or account.get("linux.do_cookies")
            if linuxdo_cookies and not account.get("cookies") and not account.get("system_access_token"):
                oauth_result = self.__linuxdo_oauth(session, account, cfg, origin)
                if not oauth_result.get("success"):
                    return self.__item(False, name, origin, oauth_result.get("message"))
                account = dict(account)
                account["cookies"] = oauth_result.get("cookies") or {}
                account["api_user"] = oauth_result.get("api_user")

            linuxdo_account = account.get("linux.do")
            if linuxdo_account and not account.get("cookies") and not account.get("system_access_token"):
                oauth_result = self.__linuxdo_password_oauth(session, account, cfg, origin, linuxdo_account)
                if not oauth_result.get("success"):
                    return self.__item(False, name, origin, oauth_result.get("message"))
                account = dict(account)
                account["cookies"] = oauth_result.get("cookies") or {}
                account["api_user"] = oauth_result.get("api_user")

            api_user = account.get("api_user")
            if not api_user:
                return self.__item(False, name, origin, "缺少 api_user")

            headers = self.__auth_headers(account, cfg, origin, api_user)
            cookies = self.__parse_cookies(account.get("cookies"))
            if cookies:
                session.cookies.update(cookies)

            if not account.get("system_access_token") and not cookies:
                return self.__item(False, name, origin, "缺少 system_access_token 或 cookies")

            if self.__already_checked_in(session, cfg, origin, headers):
                user_info = self.__get_user_info(session, cfg, origin, headers)
                return self.__item(True, name, origin, f"今日已签到。{user_info}")

            checkin_result = self.__execute_checkin(session, cfg, origin, headers)
            if not checkin_result.get("success"):
                return self.__item(False, name, origin, checkin_result.get("message"))

            user_info = self.__get_user_info(session, cfg, origin, headers)
            message = checkin_result.get("message") or "签到成功"
            if user_info:
                message = f"{message}。{user_info}"
            return self.__item(True, name, origin, message)

        except requests.RequestException as err:
            return self.__item(False, name, account.get("origin") or provider, f"请求失败：{err}")
        except Exception as err:
            logger.exception(f"{self.plugin_name} 处理账号 {name} 异常：{err}")
            return self.__item(False, name, account.get("origin") or provider, f"执行异常：{err}")

    def __linuxdo_oauth(
        self,
        provider_session: requests.Session,
        account: Dict[str, Any],
        cfg: Dict[str, Any],
        origin: str,
    ) -> Dict[str, Any]:
        client_id = account.get("linuxdo_client_id") or cfg.get("linuxdo_client_id")
        if not client_id:
            status = provider_session.get(urljoin(f"{origin}/", cfg["status_path"].lstrip("/")), timeout=self._timeout)
            data = self.__json(status)
            client_id = (((data or {}).get("data") or {}).get("linuxdo_client_id"))
        if not client_id:
            return {"success": False, "message": "未获取到 Linux.do client_id"}

        auth_state_url = urljoin(f"{origin}/", cfg["auth_state_path"].lstrip("/"))
        state_response = provider_session.get(auth_state_url, timeout=self._timeout)
        state_data = self.__json(state_response)
        state = (state_data or {}).get("data")
        if not state:
            return {"success": False, "message": "未获取到 OAuth state"}

        linux_session = self.__new_session(account)
        linux_session.headers.update(self.__common_headers(account))
        linux_session.cookies.update(self.__parse_cookies(account.get("linuxdo_cookies") or account.get("linux.do_cookies")))

        authorize_url = (
            "https://connect.linux.do/oauth2/authorize?"
            + urlencode({"response_type": "code", "client_id": client_id, "state": state})
        )
        auth_response = linux_session.get(authorize_url, timeout=self._timeout, allow_redirects=True)
        approve_url = self.__extract_approve_url(auth_response.text)
        if approve_url:
            auth_response = linux_session.get(urljoin("https://connect.linux.do", approve_url), timeout=self._timeout, allow_redirects=True)

        callback_query = parse_qs(urlparse(auth_response.url).query)
        if "code" not in callback_query:
            return {"success": False, "message": "Linux.do OAuth 未返回 code，可能 Cookie 失效或遇到 Cloudflare 验证"}

        callback_url = urljoin(f"{origin}/", cfg["linuxdo_auth_path"].lstrip("/"))
        callback_response = provider_session.get(
            f"{callback_url}?{urlencode(callback_query, doseq=True)}",
            headers={"Referer": urljoin(f"{origin}/", cfg["login_path"].lstrip("/")), "Origin": origin},
            timeout=self._timeout,
        )
        callback_data = self.__json(callback_response)
        if not callback_data or not callback_data.get("success"):
            return {"success": False, "message": (callback_data or {}).get("message") or "OAuth 回调失败"}

        api_user = ((callback_data.get("data") or {}).get("id"))
        if not api_user:
            return {"success": False, "message": "OAuth 回调成功但未返回用户 ID"}
        return {"success": True, "api_user": api_user, "cookies": provider_session.cookies.get_dict()}

    def __linuxdo_password_oauth(
        self,
        provider_session: requests.Session,
        account: Dict[str, Any],
        cfg: Dict[str, Any],
        origin: str,
        linuxdo_account: Dict[str, Any],
    ) -> Dict[str, Any]:
        username = (linuxdo_account or {}).get("username")
        password = (linuxdo_account or {}).get("password")
        if not username or not password:
            return {"success": False, "message": "缺少 Linux.do 用户名或密码"}

        linux_session = self.__new_session(account)
        linux_session.headers.update(self.__common_headers(account))
        csrf_url = "https://connect.linux.do/session/csrf.json"
        csrf_response = linux_session.get(csrf_url, timeout=self._timeout)
        if self.__is_cloudflare_page(csrf_response.text):
            return {"success": False, "message": "Linux.do 触发 Cloudflare 验证，账号密码直登不可用，请改用 Cookie 方式"}

        csrf_data = self.__json(csrf_response)
        csrf_token = (csrf_data or {}).get("csrf")
        if not csrf_token:
            return {"success": False, "message": "未获取到 Linux.do CSRF Token"}

        login_response = linux_session.post(
            "https://connect.linux.do/session",
            data={
                "login": username,
                "password": password,
                "authenticity_token": csrf_token,
            },
            headers={
                "Referer": "https://connect.linux.do/login",
                "X-CSRF-Token": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=self._timeout,
        )
        if self.__is_cloudflare_page(login_response.text):
            return {"success": False, "message": "Linux.do 登录触发 Cloudflare 验证，请改用 Cookie 方式"}

        login_data = self.__json(login_response)
        if login_response.status_code >= 400 or (login_data and login_data.get("error")):
            return {
                "success": False,
                "message": (login_data or {}).get("error") or f"Linux.do 登录失败：HTTP {login_response.status_code}",
            }

        oauth_account = dict(account)
        oauth_account["linuxdo_cookies"] = linux_session.cookies.get_dict()
        return self.__linuxdo_oauth(provider_session, oauth_account, cfg, origin)

    def __build_accounts_from_form(self, providers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        # 兼容旧版 JSON 配置：如果没有新表单站点配置，但存在旧 JSON，则继续读取。
        if not (self._sites or "").strip() and (self._accounts_json or "").strip():
            return self.__loads_list(self._accounts_json, "账号配置 JSON")

        sites = self.__parse_sites(self._sites)
        accounts: List[Dict[str, Any]] = []
        for idx, site in enumerate(sites, start=1):
            account: Dict[str, Any] = {
                "name": site.get("name") or f"New API {idx}",
            }
            site_key = site.get("site") or ""
            if site_key in providers:
                account["provider"] = site_key
            elif site_key.startswith("http://") or site_key.startswith("https://"):
                account["origin"] = site_key.rstrip("/")
            else:
                account["provider"] = site_key

            if site.get("client_id"):
                account["linuxdo_client_id"] = site.get("client_id")

            if self._auth_mode == "cookie":
                api_user = site.get("api_user") or self._api_user
                cookie = site.get("cookie") or self._cookie
                account["api_user"] = api_user
                account["cookies"] = cookie
            else:
                account["linux.do"] = {
                    "username": self._linuxdo_username,
                    "password": self._linuxdo_password,
                }
            accounts.append(account)

        return accounts

    @staticmethod
    def __parse_sites(value: str) -> List[Dict[str, str]]:
        result = []
        for raw in (value or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) == 1:
                site = parts[0]
                name = site
            else:
                name = parts[0]
                site = parts[1]
            result.append({
                "name": name,
                "site": site,
                "api_user": parts[2] if len(parts) > 2 else "",
                "cookie": parts[3] if len(parts) > 3 else "",
                "client_id": parts[2] if len(parts) > 2 and not parts[2].isdigit() else "",
            })
        return result

    def __load_providers(self) -> Dict[str, Dict[str, Any]]:
        providers = {k: dict(v) for k, v in self.DEFAULT_PROVIDERS.items()}
        if not (self._providers_json or "").strip():
            return providers
        custom = json.loads(self._providers_json)
        if not isinstance(custom, dict):
            raise ValueError("自定义 Provider JSON 必须是对象")
        for key, value in custom.items():
            if isinstance(value, dict):
                providers[key] = value
        return providers

    def __merge_provider_config(self, account: Dict[str, Any], providers: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        provider = str(account.get("provider") or "")
        cfg = dict(providers.get(provider, {}))
        cfg.update({k: v for k, v in account.items() if k in {
            "origin", "login_path", "status_path", "auth_state_path", "check_in_path",
            "check_in_status", "user_info_path", "api_user_key", "linuxdo_client_id",
            "linuxdo_auth_path", "linuxdo_auth_redirect_path",
        }})
        if not cfg.get("origin"):
            raise ValueError("缺少 origin 或未知 provider")
        cfg.setdefault("login_path", "/login")
        cfg.setdefault("status_path", "/api/status")
        cfg.setdefault("auth_state_path", "/api/oauth/state")
        cfg.setdefault("check_in_path", "/api/user/checkin")
        cfg.setdefault("check_in_status", True)
        cfg.setdefault("user_info_path", "/api/user/self")
        cfg.setdefault("api_user_key", "new-api-user")
        cfg.setdefault("linuxdo_auth_path", "/api/oauth/linuxdo")
        return cfg

    def __common_headers(self, account: Dict[str, Any]) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "User-Agent": account.get("user_agent")
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        extra = account.get("headers")
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    def __new_session(self, account: Dict[str, Any]):
        if self._cf_bypass and HAS_CURL_CFFI:
            try:
                session = curl_requests.Session(impersonate=account.get("impersonate") or "chrome110", timeout=self._timeout)
                logger.debug(f"{self.plugin_name} 使用 curl_cffi 会话")
                return session
            except Exception as err:
                logger.warning(f"{self.plugin_name} curl_cffi 会话创建失败：{err}")

        if self._cf_bypass and HAS_CLOUDSCRAPER:
            try:
                scraper = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
                logger.debug(f"{self.plugin_name} 使用 cloudscraper 会话")
                return scraper
            except Exception as err:
                logger.warning(f"{self.plugin_name} cloudscraper 会话创建失败：{err}")

        return requests.Session()

    def __auth_headers(self, account: Dict[str, Any], cfg: Dict[str, Any], origin: str, api_user: Any) -> Dict[str, str]:
        headers = self.__common_headers(account)
        headers[cfg["api_user_key"]] = str(api_user)
        headers["Referer"] = urljoin(f"{origin}/", cfg["login_path"].lstrip("/"))
        headers["Origin"] = origin
        token = account.get("system_access_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def __already_checked_in(self, session: requests.Session, cfg: Dict[str, Any], origin: str, headers: Dict[str, str]) -> bool:
        if not cfg.get("check_in_status", True):
            return False
        month = datetime.now().strftime("%Y-%m")
        url = urljoin(f"{origin}/", cfg["check_in_path"].lstrip("/")) + f"?month={month}"
        response = session.get(url, headers=headers, timeout=self._timeout)
        if response.status_code != 200:
            return False
        data = self.__json(response)
        if not data or not data.get("success"):
            return False
        stats = (data.get("data") or {}).get("stats") or {}
        return bool(stats.get("checked_in_today"))

    def __execute_checkin(self, session: requests.Session, cfg: Dict[str, Any], origin: str, headers: Dict[str, str]) -> Dict[str, Any]:
        url = urljoin(f"{origin}/", cfg["check_in_path"].lstrip("/"))
        post_headers = dict(headers)
        post_headers.update({"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"})
        response = session.post(url, headers=post_headers, timeout=self._timeout)
        data = self.__json(response)
        text = response.text or ""

        if response.status_code not in (200, 400):
            return {"success": False, "message": f"HTTP {response.status_code}"}
        if not data:
            return {"success": "success" in text.lower(), "message": "非 JSON 响应"}

        message = data.get("message") or data.get("msg") or ""
        success = (
            data.get("ret") == 1
            or data.get("code") == 0
            or data.get("success") is True
            or "已经签到" in message
            or "签到成功" in message
        )
        detail = message or ("签到成功" if success else "签到失败")
        quota_awarded = ((data.get("data") or {}).get("quota_awarded") or 0)
        if quota_awarded:
            detail = f"{detail}，获得 ${round(quota_awarded / 500000, 2)}"
        return {"success": success, "message": detail}

    def __get_user_info(self, session: requests.Session, cfg: Dict[str, Any], origin: str, headers: Dict[str, str]) -> str:
        url = urljoin(f"{origin}/", cfg["user_info_path"].lstrip("/"))
        response = session.get(url, headers=headers, timeout=self._timeout)
        if response.status_code != 200:
            return ""
        data = self.__json(response)
        if not data or not data.get("success"):
            return ""
        user = data.get("data") or {}
        quota = round((user.get("quota") or 0) / 500000, 2)
        used = round((user.get("used_quota") or 0) / 500000, 2)
        bonus = round((user.get("bonus_quota") or 0) / 500000, 2)
        return f"余额 ${quota}，已用 ${used}，赠送 ${bonus}"

    @staticmethod
    def __parse_cookies(value: Any) -> Dict[str, str]:
        if not value:
            return {}
        if isinstance(value, dict):
            return {str(k): str(v) for k, v in value.items() if v is not None}
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return {}
            if "=" not in value:
                return {"session": value}
            cookies = {}
            for item in value.split(";"):
                if "=" not in item:
                    continue
                key, val = item.split("=", 1)
                cookies[key.strip()] = val.strip()
            return cookies
        return {}

    @staticmethod
    def __extract_approve_url(text: str) -> Optional[str]:
        match = re.search(r'href=["\']([^"\']*/oauth2/approve[^"\']*)["\']', text or "", re.I)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def __is_cloudflare_page(text: str) -> bool:
        text = text or ""
        return "Just a moment" in text or "cf_chl" in text or "Checking your browser" in text

    @staticmethod
    def __json(response: requests.Response) -> Optional[Dict[str, Any]]:
        try:
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def __loads_list(value: str, name: str) -> List[Any]:
        data = json.loads(value)
        if not isinstance(data, list):
            raise ValueError(f"{name} 必须是数组")
        return data

    def __finish(self, success: bool, title: str, message: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = {
            "success": success,
            "title": title,
            "message": message,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "items": items,
        }
        self._last_result = result
        try:
            self.save_data("last_result", result)
        except Exception as err:
            logger.warning(f"{self.plugin_name} 保存执行结果失败：{err}")
        if self._notify:
            try:
                detail = "\n".join([
                    f"{'成功' if item.get('success') else '失败'} {item.get('name')}: {item.get('message')}"
                    for item in items
                ])
                self.post_message(title=f"{self.plugin_name}：{title}", text=f"{message}\n{detail}".strip())
            except Exception as err:
                logger.warning(f"{self.plugin_name} 发送通知失败：{err}")
        return result

    def __save_config(self):
        self.update_config({
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cron": self._cron,
            "timeout": self._timeout,
            "auth_mode": self._auth_mode,
            "sites": self._sites,
            "linuxdo_username": self._linuxdo_username,
            "linuxdo_password": self._linuxdo_password,
            "api_user": self._api_user,
            "cookie": self._cookie,
            "cf_bypass": self._cf_bypass,
            "accounts_json": self._accounts_json,
            "providers_json": self._providers_json,
        })

    @staticmethod
    def __item(success: bool, name: str, origin: str, message: str) -> Dict[str, Any]:
        return {"success": success, "name": name, "origin": origin, "message": message or ""}

    @staticmethod
    def __col_switch(model: str, label: str, md: int) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{"component": "VSwitch", "props": {"model": model, "label": label}}],
        }

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
