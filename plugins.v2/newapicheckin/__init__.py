import json
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


class NewApiCheckin(_PluginBase):
    plugin_name = "New API每日签到"
    plugin_desc = "支持多个 New API 站点每日签到，每个站点独立配置 URL、用户 ID 和 Cookie。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.10"
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
    _retry_count = 2
    _retry_interval = 3
    _site_count = 1
    _site_configs: List[Dict[str, Any]] = []
    _accounts_json = ""
    _providers_json = "{}"
    _last_result: Dict[str, Any] = {}
    MAX_SITE_COUNT = 50
    QUOTA_UNIT = 500000
    RETRY_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
    ALREADY_CHECKED_IN_KEYWORDS = ("已签到", "已经签到", "已签过", "今日已签", "already", "重复签到")
    SUCCESS_KEYWORDS = ("签到成功", "check in success", "checkin success", "checked in")
    BALANCE_KEYS = {
        "balance", "amount", "credit", "credits", "money", "wallet",
        "remaining_balance", "remain_balance", "available_balance", "quota",
    }

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

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify", True))
        self._cron = config.get("cron") or self._cron
        self._timeout = self.__to_int(config.get("timeout"), 30)
        self._retry_count = max(0, self.__to_int(config.get("retry_count"), 2))
        self._retry_interval = max(0, self.__to_int(config.get("retry_interval"), 3))
        self._site_configs = self.__load_site_configs(config)
        default_site_count = max([
            index for index, site in enumerate(self._site_configs, start=1)
            if site.get("name") or site.get("url") or site.get("api_user") or site.get("cookie")
            or site.get("system_access_token") or site.get("check_in_path") or site.get("user_info_path")
            or site.get("visit_path") or site.get("checkin_mode") == "visit"
        ] or [1])
        self._site_count = max(
            1,
            min(
                self.MAX_SITE_COUNT,
                self.__to_int(config.get("site_count"), default_site_count),
            ),
        )
        self._accounts_json = config.get("accounts_json") or ""
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
        model = {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "cron": "25 8 * * *",
            "timeout": 30,
            "retry_count": 2,
            "retry_interval": 3,
            "site_count": 1,
        }
        for index in range(1, self.MAX_SITE_COUNT + 1):
            model.update({
                f"site_{index}_enabled": index == 1,
                f"site_{index}_name": "",
                f"site_{index}_url": "",
                f"site_{index}_api_user": "",
                f"site_{index}_cookie": "",
                f"site_{index}_checkin_mode": "api",
                f"site_{index}_visit_path": "",
                f"site_{index}_system_access_token": "",
                f"site_{index}_check_in_path": "",
                f"site_{index}_user_info_path": "",
            })

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
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
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
                                "props": {"cols": 12, "md": 4},
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
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 2},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "retry_count",
                                            "label": "失败重试次数",
                                            "type": "number",
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
                                            "model": "retry_interval",
                                            "label": "重试间隔秒数",
                                            "type": "number",
                                        },
                                    }
                                ],
                            },
                        ],
                    },
                    *[self.__site_config_card(index) for index in range(1, self.MAX_SITE_COUNT + 1)],
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "tonal",
                                            "prepend-icon": "mdi-plus",
                                            "disabled": "{{ site_count >= 50 }}",
                                            "onClick": (
                                                "function(event) { "
                                                "const next = Math.min(50, Number(site_count || 1) + 1); "
                                                "model['site_' + next + '_enabled'] = true; "
                                                "site_count = next; "
                                                "}"
                                            ),
                                        },
                                        "text": "新增站点",
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
        ], model

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
                    {"component": "td", "text": item.get("detail") or "-"},
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
                                    {"component": "th", "text": "详情"},
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
            logger.info(
                f"{self.plugin_name} 开始处理站点：{name}，origin={origin}，"
                f"mode={account.get('checkin_mode') or 'api'}，"
                f"check_in_path={cfg.get('check_in_path')}，user_info_path={cfg.get('user_info_path')}"
            )

            api_user = account.get("api_user")
            checkin_mode = account.get("checkin_mode") or "api"
            cookies = self.__parse_cookies(account.get("cookies"))
            if cookies:
                session.cookies.update(cookies)

            if not account.get("system_access_token") and not cookies:
                return self.__item(False, name, origin, "缺少 system_access_token 或 cookies")

            headers = self.__auth_headers(account, cfg, origin, api_user)

            if checkin_mode == "visit":
                visit_result = self.__execute_visit_checkin(session, cfg, origin, headers, name, account.get("visit_path"))
                if not visit_result.get("success"):
                    return self.__item(
                        False,
                        name,
                        origin,
                        visit_result.get("message"),
                        visit_result.get("detail"),
                    )
                user_info = self.__get_user_info(session, cfg, origin, headers, name)
                message = visit_result.get("message") or "访问完成"
                if user_info:
                    message = f"{message}。{user_info}"
                return self.__item(True, name, origin, message, visit_result.get("detail"))

            if not api_user:
                return self.__item(False, name, origin, "缺少 api_user")

            if self.__already_checked_in(session, cfg, origin, headers, name):
                user_info = self.__get_user_info(session, cfg, origin, headers, name)
                return self.__item(True, name, origin, f"今日已签到。{user_info}")

            checkin_result = self.__execute_checkin(session, cfg, origin, headers, name)
            if not checkin_result.get("success"):
                return self.__item(
                    False,
                    name,
                    origin,
                    checkin_result.get("message"),
                    checkin_result.get("detail"),
                )

            user_info = self.__get_user_info(session, cfg, origin, headers, name)
            message = checkin_result.get("message") or "签到成功"
            if user_info:
                message = f"{message}。{user_info}"
            return self.__item(True, name, origin, message)

        except requests.RequestException as err:
            return self.__item(False, name, account.get("origin") or provider, f"请求失败：{err}")
        except Exception as err:
            logger.exception(f"{self.plugin_name} 处理账号 {name} 异常：{err}")
            return self.__item(False, name, account.get("origin") or provider, f"执行异常：{err}")

    def __build_accounts_from_form(self, providers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        configured_sites = [
            site for site in self._site_configs
            if site.get("enabled") and self.__clean(site.get("url"))
        ]

        # 兼容旧版 JSON 配置：如果没有新表单站点配置，但存在旧 JSON，则继续读取。
        if not configured_sites and (self._accounts_json or "").strip():
            return self.__loads_list(self._accounts_json, "账号配置 JSON")

        accounts: List[Dict[str, Any]] = []
        for idx, site in enumerate(configured_sites, start=1):
            account: Dict[str, Any] = {
                "name": site.get("name") or f"New API {idx}",
            }
            site_url = site.get("url") or ""
            if not site_url.startswith("http://") and not site_url.startswith("https://"):
                raise ValueError(f"{account['name']} 的网站地址必须是 http:// 或 https:// 开头")
            account["origin"] = site_url.rstrip("/")
            account["api_user"] = site.get("api_user")
            account["cookies"] = site.get("cookie")
            account["checkin_mode"] = site.get("checkin_mode") or "api"
            account["visit_path"] = site.get("visit_path")
            account["system_access_token"] = site.get("system_access_token")
            account["check_in_path"] = site.get("check_in_path")
            account["user_info_path"] = site.get("user_info_path")
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
                "url": site,
                "api_user": parts[2] if len(parts) > 2 else "",
                "cookie": parts[3] if len(parts) > 3 else "",
            })
        return result

    def __load_site_configs(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        sites: List[Dict[str, Any]] = []
        for index in range(1, self.MAX_SITE_COUNT + 1):
            site = {
                "enabled": bool(config.get(f"site_{index}_enabled", index == 1)),
                "name": self.__clean(config.get(f"site_{index}_name")),
                "url": self.__clean(config.get(f"site_{index}_url")),
                "api_user": self.__clean(config.get(f"site_{index}_api_user")),
                "cookie": self.__clean(config.get(f"site_{index}_cookie")),
                "checkin_mode": self.__checkin_mode(config.get(f"site_{index}_checkin_mode")),
                "visit_path": self.__clean(config.get(f"site_{index}_visit_path")),
                "system_access_token": self.__clean(config.get(f"site_{index}_system_access_token")),
                "check_in_path": self.__clean(config.get(f"site_{index}_check_in_path")),
                "user_info_path": self.__clean(config.get(f"site_{index}_user_info_path")),
            }
            sites.append(site)

        if any(site.get("url") for site in sites):
            return sites

        legacy_sites = self.__parse_sites(config.get("sites") or "")
        if not legacy_sites:
            return sites

        migrated: List[Dict[str, Any]] = []
        for site in legacy_sites[:self.MAX_SITE_COUNT]:
            migrated.append({
                "enabled": True,
                "name": site.get("name") or "",
                "url": site.get("url") or "",
                "api_user": site.get("api_user") or self.__clean(config.get("api_user")),
                "cookie": site.get("cookie") or self.__clean(config.get("cookie")),
                "checkin_mode": "api",
                "visit_path": "",
                "system_access_token": "",
                "check_in_path": "",
                "user_info_path": "",
            })
        while len(migrated) < self.MAX_SITE_COUNT:
            index = len(migrated) + 1
            migrated.append({
                "enabled": index == 1,
                "name": "",
                "url": "",
                "api_user": "",
                "cookie": "",
                "checkin_mode": "api",
                "visit_path": "",
                "system_access_token": "",
                "check_in_path": "",
                "user_info_path": "",
            })
        return migrated

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
        cfg.update({k: v for k, v in account.items() if v and k in {
            "origin", "login_path", "status_path", "auth_state_path", "check_in_path",
            "check_in_status", "user_info_path", "api_user_key",
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
        return requests.Session()

    def __auth_headers(self, account: Dict[str, Any], cfg: Dict[str, Any], origin: str, api_user: Any) -> Dict[str, str]:
        headers = self.__common_headers(account)
        if api_user:
            headers[cfg["api_user_key"]] = str(api_user)
        headers["Referer"] = urljoin(f"{origin}/", cfg["login_path"].lstrip("/"))
        headers["Origin"] = origin
        token = account.get("system_access_token")
        if token:
            token = str(token).strip()
            headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        return headers

    def __request(self, session: requests.Session, method: str, url: str, name: str, action: str, **kwargs) -> requests.Response:
        method = method.upper()
        attempts = max(1, self._retry_count + 1)
        request_func = getattr(session, method.lower())
        last_error = None
        kwargs.setdefault("timeout", self._timeout)

        for attempt in range(1, attempts + 1):
            try:
                response = request_func(url, **kwargs)
                if response.status_code not in self.RETRY_STATUS_CODES or attempt >= attempts:
                    return response
                logger.warning(
                    f"{self.plugin_name} [{name}] {action} 第 {attempt}/{attempts} 次返回 "
                    f"HTTP {response.status_code}，{self._retry_interval} 秒后重试：{method} {url}"
                )
            except Exception as err:
                last_error = err
                if attempt >= attempts:
                    logger.warning(f"{self.plugin_name} [{name}] {action} 请求失败且已无重试：{method} {url}，错误：{err}")
                    raise
                logger.warning(
                    f"{self.plugin_name} [{name}] {action} 第 {attempt}/{attempts} 次请求异常，"
                    f"{self._retry_interval} 秒后重试：{method} {url}，错误：{err}"
                )

            if self._retry_interval > 0:
                time.sleep(self._retry_interval)

        if last_error:
            raise last_error
        raise RuntimeError(f"{action} 请求失败：{method} {url}")

    def __checkin_message(self, data: Dict[str, Any]) -> str:
        reward = data.get("reward")
        raw_message = (
            data.get("message")
            or data.get("msg")
            or ("今日已签到" if data.get("already_checked_in") is True else "")
            or (f"签到成功，获得 ${self.__format_number(float(reward))}" if self.__is_number(reward) else "")
            or data.get("data")
            or ""
        )
        if isinstance(raw_message, str):
            return raw_message
        try:
            return json.dumps(raw_message, ensure_ascii=False)
        except Exception:
            return str(raw_message)

    def __is_checkin_success(self, data: Dict[str, Any], message: str) -> bool:
        status = str(data.get("status") or "").lower()
        return (
            data.get("success") is True
            or status == "success"
            or data.get("ret") == 1
            or self.__is_zero(data.get("code"))
            or data.get("ok") is True
            or data.get("already_checked_in") is True
            or self.__contains_keyword(message, self.ALREADY_CHECKED_IN_KEYWORDS)
            or self.__contains_keyword(message, self.SUCCESS_KEYWORDS)
        )

    @staticmethod
    def __contains_keyword(value: str, keywords: Tuple[str, ...]) -> bool:
        text = str(value or "").lower()
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def __is_zero(value: Any) -> bool:
        try:
            return float(value) == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def __is_number(value: Any) -> bool:
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    def __already_checked_in(
        self,
        session: requests.Session,
        cfg: Dict[str, Any],
        origin: str,
        headers: Dict[str, str],
        name: str,
    ) -> bool:
        if not cfg.get("check_in_status", True):
            return False
        month = datetime.now().strftime("%Y-%m")
        url = urljoin(f"{origin}/", cfg["check_in_path"].lstrip("/")) + f"?month={month}"
        logger.info(f"{self.plugin_name} [{name}] 查询签到状态：GET {url}")
        response = self.__request(session, "GET", url, name, "查询签到状态", headers=headers)
        if response.status_code != 200:
            logger.warning(f"{self.plugin_name} [{name}] 查询签到状态失败：{self.__response_detail('GET', url, response)}")
            return False
        data = self.__json(response)
        if not data or not data.get("success"):
            logger.warning(f"{self.plugin_name} [{name}] 查询签到状态返回异常：{self.__response_detail('GET', url, response)}")
            return False
        stats = (data.get("data") or {}).get("stats") or {}
        logger.info(f"{self.plugin_name} [{name}] 签到状态：checked_in_today={bool(stats.get('checked_in_today'))}")
        return bool(stats.get("checked_in_today"))

    def __execute_checkin(
        self,
        session: requests.Session,
        cfg: Dict[str, Any],
        origin: str,
        headers: Dict[str, str],
        name: str,
    ) -> Dict[str, Any]:
        url = urljoin(f"{origin}/", cfg["check_in_path"].lstrip("/"))
        post_headers = dict(headers)
        post_headers.update({"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"})
        logger.info(f"{self.plugin_name} [{name}] 执行签到：POST {url}")
        response = self.__request(session, "POST", url, name, "执行签到", headers=post_headers)
        data = self.__json(response)
        text = response.text or ""
        detail = self.__response_detail("POST", url, response)

        if response.status_code not in (200, 400):
            logger.warning(f"{self.plugin_name} [{name}] 签到请求失败：{detail}")
            return {"success": False, "message": f"HTTP {response.status_code}", "detail": detail}
        if not data:
            success = self.__contains_keyword(text, self.SUCCESS_KEYWORDS + self.ALREADY_CHECKED_IN_KEYWORDS)
            if not success:
                logger.warning(f"{self.plugin_name} [{name}] 签到返回非 JSON：{detail}")
            message = "非 JSON 响应"
            if self.__is_js_challenge(text):
                message = "命中站点 JS 防护，请在浏览器通过验证后复制完整 Cookie"
            return {"success": success, "message": message, "detail": detail}

        message = self.__checkin_message(data)
        success = self.__is_checkin_success(data, message)
        detail = message or ("签到成功" if success else "签到失败")
        quota_awarded = ((data.get("data") or {}).get("quota_awarded") or 0)
        if self.__is_number(quota_awarded) and float(quota_awarded) > 0:
            detail = f"{detail}，获得 ${self.__format_number(float(quota_awarded) / self.QUOTA_UNIT)}"
        if not success:
            logger.warning(f"{self.plugin_name} [{name}] 签到接口返回失败：{self.__response_detail('POST', url, response)}")
        else:
            logger.info(f"{self.plugin_name} [{name}] 签到接口返回成功：{detail}")
        return {"success": success, "message": detail, "detail": self.__response_detail("POST", url, response)}

    def __execute_visit_checkin(
        self,
        session: requests.Session,
        cfg: Dict[str, Any],
        origin: str,
        headers: Dict[str, str],
        name: str,
        visit_path: str = "",
    ) -> Dict[str, Any]:
        path = self.__clean(visit_path) or "/"
        url = urljoin(f"{origin}/", path.lstrip("/"))
        visit_headers = dict(headers)
        visit_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7"
        logger.info(f"{self.plugin_name} [{name}] 访问页面触发签到：GET {url}")
        response = self.__request(session, "GET", url, name, "访问页面触发签到", headers=visit_headers)
        text = response.text or ""
        detail = self.__response_detail("GET", url, response)

        if response.status_code not in (200, 204):
            logger.warning(f"{self.plugin_name} [{name}] 访问页面触发失败：{detail}")
            return {"success": False, "message": f"HTTP {response.status_code}", "detail": detail}
        if self.__is_js_challenge(text):
            logger.warning(f"{self.plugin_name} [{name}] 访问页面命中 JS 防护：{detail}")
            return {
                "success": False,
                "message": "命中站点 JS 防护，请在浏览器通过验证后复制完整 Cookie",
                "detail": detail,
            }

        message = self.__visit_message(text) or "访问完成，若站点支持登录触发签到则已触发"
        logger.info(f"{self.plugin_name} [{name}] 访问页面触发完成：{message}")
        return {"success": True, "message": message, "detail": detail}

    def __get_user_info(
        self,
        session: requests.Session,
        cfg: Dict[str, Any],
        origin: str,
        headers: Dict[str, str],
        name: str,
    ) -> str:
        for url in self.__balance_urls(cfg, origin):
            logger.info(f"{self.plugin_name} [{name}] 查询用户信息：GET {url}")
            response = self.__request(session, "GET", url, name, "查询用户信息", headers=headers)
            if response.status_code != 200:
                logger.warning(f"{self.plugin_name} [{name}] 查询用户信息失败：{self.__response_detail('GET', url, response)}")
                continue
            data = self.__json(response)
            if not data:
                logger.warning(f"{self.plugin_name} [{name}] 查询用户信息返回非 JSON：{self.__response_detail('GET', url, response)}")
                continue
            info = self.__format_user_info(data)
            if info:
                logger.info(f"{self.plugin_name} [{name}] 查询用户信息成功：{info}")
                return info
            logger.warning(f"{self.plugin_name} [{name}] 查询用户信息未识别到余额：{self.__response_detail('GET', url, response)}")
        return ""

    def __balance_urls(self, cfg: Dict[str, Any], origin: str) -> List[str]:
        paths = [
            cfg.get("user_info_path") or "/api/user/self",
            "/api/user/self",
            "/api/status",
            "/api/u/dashboard",
            "/api/v1/user/info",
            "/api/v1/user",
        ]
        urls = []
        for path in paths:
            url = urljoin(f"{origin}/", str(path).lstrip("/"))
            if url not in urls:
                urls.append(url)
        return urls

    def __format_user_info(self, data: Dict[str, Any]) -> str:
        user = data.get("data") if isinstance(data.get("data"), dict) else data
        if isinstance(user, dict) and any(key in user for key in ("quota", "used_quota", "bonus_quota")):
            quota = self.__format_balance_value(user.get("quota"), "quota") or "$0"
            used = self.__format_balance_value(user.get("used_quota"), "used_quota") or "$0"
            bonus = self.__format_balance_value(user.get("bonus_quota"), "bonus_quota") or "$0"
            return f"余额 {quota}，已用 {used}，赠送 {bonus}"

        extracted = self.__extract_balance_from_data(data)
        if extracted:
            key, value = extracted
            balance = self.__format_balance_value(value, key)
            if balance:
                return f"余额 {balance}"
        return ""

    def __extract_balance_from_data(self, value: Any) -> Optional[Tuple[str, Any]]:
        if not isinstance(value, dict):
            return None
        for key, child in value.items():
            if key.lower() in self.BALANCE_KEYS and child not in (None, ""):
                return key, child
        for child in value.values():
            if isinstance(child, dict):
                extracted = self.__extract_balance_from_data(child)
                if extracted:
                    return extracted
            if isinstance(child, list):
                for item in child:
                    extracted = self.__extract_balance_from_data(item)
                    if extracted:
                        return extracted
        return None

    def __format_balance_value(self, value: Any, key: str = "") -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, str):
            normalized = " ".join(value.split())
            if not normalized:
                return ""
            try:
                numeric = float(normalized.replace("$", "").replace("¥", "").replace("￥", "").replace(",", ""))
            except ValueError:
                return normalized
        else:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return ""

        if "quota" in key.lower():
            return f"${self.__format_number(numeric / self.QUOTA_UNIT)}"
        prefix = "$" if isinstance(value, str) and value.strip().startswith("$") else ""
        return f"{prefix}{self.__format_number(numeric)}"

    @staticmethod
    def __format_number(value: float) -> str:
        if abs(value - round(value)) < 0.000001:
            return str(int(round(value)))
        return f"{value:.2f}".rstrip("0").rstrip(".")

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
    def __json(response: requests.Response) -> Optional[Dict[str, Any]]:
        try:
            data = response.json()
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def __response_detail(method: str, url: str, response: requests.Response) -> str:
        content_type = response.headers.get("Content-Type") or response.headers.get("content-type") or "-"
        preview = NewApiCheckin.__response_preview(response)
        final_url = getattr(response, "url", "") or url
        detail = f"{method} {final_url} -> HTTP {response.status_code}, Content-Type: {content_type}"
        if preview:
            detail = f"{detail}, Body: {preview}"
        return detail

    @staticmethod
    def __response_preview(response: requests.Response, limit: int = 500) -> str:
        try:
            text = response.text or ""
        except Exception:
            return ""
        text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if len(text) > limit:
            return f"{text[:limit]}..."
        return text

    @staticmethod
    def __is_js_challenge(text: str) -> bool:
        text = text or ""
        return (
            "var arg1=" in text
            or "acw_sc__v2" in text
            or "window.location" in text and "document.cookie" in text
        )

    @staticmethod
    def __visit_message(text: str) -> str:
        text = text or ""
        keywords = [
            "签到成功",
            "已签到",
            "赠送",
            "奖励",
            "quota",
            "checkin",
            "check-in",
        ]
        compact = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        for keyword in keywords:
            index = compact.lower().find(keyword.lower())
            if index >= 0:
                start = max(0, index - 80)
                end = min(len(compact), index + 160)
                return compact[start:end]
        return ""

    @staticmethod
    def __checkin_mode(value: Any) -> str:
        value = str(value or "api").strip().lower()
        return "visit" if value == "visit" else "api"

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
        config = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "notify": self._notify,
            "cron": self._cron,
            "timeout": self._timeout,
            "retry_count": self._retry_count,
            "retry_interval": self._retry_interval,
            "site_count": self._site_count,
        }
        for index, site in enumerate(self._site_configs[:self.MAX_SITE_COUNT], start=1):
            config.update({
                f"site_{index}_enabled": bool(site.get("enabled")),
                f"site_{index}_name": site.get("name") or "",
                f"site_{index}_url": site.get("url") or "",
                f"site_{index}_api_user": site.get("api_user") or "",
                f"site_{index}_cookie": site.get("cookie") or "",
                f"site_{index}_checkin_mode": site.get("checkin_mode") or "api",
                f"site_{index}_visit_path": site.get("visit_path") or "",
                f"site_{index}_system_access_token": site.get("system_access_token") or "",
                f"site_{index}_check_in_path": site.get("check_in_path") or "",
                f"site_{index}_user_info_path": site.get("user_info_path") or "",
            })
        self.update_config(config)

    @staticmethod
    def __item(success: bool, name: str, origin: str, message: str, detail: str = "") -> Dict[str, Any]:
        return {
            "success": success,
            "name": name,
            "origin": origin,
            "message": message or "",
            "detail": detail or "",
        }

    @staticmethod
    def __col_switch(model: str, label: str, md: int) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{"component": "VSwitch", "props": {"model": model, "label": label}}],
        }

    @staticmethod
    def __site_config_card(index: int) -> dict:
        show_props = {"show": f"{{{{ site_count >= {index} }}}}"} if index > 1 else {}
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "class": "mb-3", **show_props},
            "content": [
                {
                    "component": "VCardTitle",
                    "props": {"class": "text-subtitle-1"},
                    "text": f"站点 {index}",
                },
                {
                    "component": "VCardText",
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
                                            "props": {
                                                "model": f"site_{index}_enabled",
                                                "label": "启用",
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
                                                "model": f"site_{index}_name",
                                                "label": "站点名称",
                                                "placeholder": "可选",
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
                                                "model": f"site_{index}_url",
                                                "label": "站点URL",
                                                "placeholder": "https://example.com",
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
                                            "component": "VSelect",
                                            "props": {
                                                "model": f"site_{index}_checkin_mode",
                                                "label": "签到方式",
                                                "items": [
                                                    {"title": "API签到", "value": "api"},
                                                    {"title": "访问页面触发", "value": "visit"},
                                                ],
                                            },
                                        }
                                    ],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 4},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": f"site_{index}_visit_path",
                                                "label": "访问触发路径",
                                                "placeholder": "/",
                                            },
                                        }
                                    ],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 4},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": f"site_{index}_api_user",
                                                "label": "New API用户ID",
                                            },
                                        }
                                    ],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 8},
                                    "content": [
                                        {
                                            "component": "VTextarea",
                                            "props": {
                                                "model": f"site_{index}_cookie",
                                                "label": "Cookie",
                                                "rows": 3,
                                                "auto-grow": True,
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
                                                "model": f"site_{index}_system_access_token",
                                                "label": "Authorization Token",
                                                "placeholder": "可选，填写 token 或 Bearer token",
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
                                    "props": {"cols": 12, "md": 6},
                                    "content": [
                                        {
                                            "component": "VTextField",
                                            "props": {
                                                "model": f"site_{index}_check_in_path",
                                                "label": "签到接口路径",
                                                "placeholder": "/api/user/checkin",
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
                                                "model": f"site_{index}_user_info_path",
                                                "label": "用户信息路径",
                                                "placeholder": "/api/user/self",
                                            },
                                        }
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }

    @staticmethod
    def __clean(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def __to_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
