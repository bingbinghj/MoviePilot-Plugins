import base64
import hashlib
import json
import re
import secrets
import string
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlencode

import requests
from apscheduler.triggers.cron import CronTrigger

from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType


API_BASE = "https://api.xiaoheihe.cn"
DATA_BASE = "https://data.xiaoheihe.cn"
HKEY_API = "https://hkey.qcciii.com/hkey"
APP_UA = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2272.118 Safari/537.36 ApiMaxJia/1.0"
APP_REFERER = "http://api.maxjia.com/"
OK_STATE = "ok"

APP_PROFILE = {
    "os_type": "Android",
    "x_os_type": "Android",
    "x_client_type": "mobile",
    "os_version": "12",
    "dw": "360",
    "channel": "heybox",
    "x_app": "heybox",
    "time_zone": "Asia/Shanghai",
    "device_info": "HBP-AL00",
}

PATH_LIST = "/task/list_v2/"
PATH_SIGN = "/task/sign_v3/sign"
PATH_STATE = "/task/sign_v3/get_sign_state"
PATH_FEEDS = "/bbs/app/feeds"
PATH_GAME_RECOMMEND = "/game/all_recommend/v2"
PATH_GAME_COMMENTS = "/bbs/app/link/game/comments"
PATH_VIEW_TIME = "/bbs/app/link/view/time"
PATH_DATA_REPORT = "/account/data_report/"

WAITING_STATE = "waiting"
FINISH_STATE = "finish"
POST_SHARE_VIEW_SECONDS = 5
POST_SHARE_VIEW_MILLISECONDS = 5000
SHARE_TASK_SETTLE_SECONDS = 2.2

FEEDS_QUERY_BASE = {
    "pull": "1",
    "last_pull": "1",
    "is_first": "0",
    "list_ver": "2",
    "has_cache": "1",
    "netmode": "wifi",
}
GAME_RECOMMEND_QUERY_BASE = {"offset": "0", "limit": "1"}
GAME_COMMENTS_QUERY_BASE = {"api_version": "4", "offset": "0", "limit": "30"}


def to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def build_query_string(source: Dict[str, Any]) -> str:
    return urlencode({key: str(value) for key, value in (source or {}).items() if value not in (None, "")})


def make_nonce(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def pick_cookie(cookie: str, key: str) -> str:
    for raw in str(cookie or "").split(";"):
        item = raw.strip()
        if not item or "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip() == key:
            return value.strip()
    return ""


def decode_pkey_to_user_id(cookie: str) -> str:
    pkey = pick_cookie(cookie, "pkey")
    if not pkey:
        return ""
    try:
        encoded = unquote(pkey)
    except Exception:
        return ""
    compact = re.sub(r"_+$", "", encoded) or encoded
    padded = compact + ("=" * ((4 - (len(compact) % 4)) % 4))
    try:
        plain = base64.b64decode(padded.replace("-", "+").replace("_", "/")).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    match = re.search(r"_(\d{5,})", plain)
    return match.group(1) if match else ""


def make_imei(cookie: str) -> str:
    pkey = pick_cookie(cookie, "pkey")
    if not pkey:
        raise ValueError("Cookie 缺少 pkey")
    return hashlib.md5(pkey.encode("utf-8")).hexdigest()[:16]


def build_app_cookie(cookie: str) -> str:
    pkey = pick_cookie(cookie, "pkey")
    token_id = pick_cookie(cookie, "x_xhh_tokenid")
    if not pkey:
        raise ValueError("Cookie 缺少 pkey")
    if not token_id:
        raise ValueError("Cookie 缺少 x_xhh_tokenid")
    return f"pkey={pkey};x_xhh_tokenid={token_id}"


def response_preview(response: requests.Response, limit: int = 500) -> str:
    try:
        text = response.text or ""
    except Exception:
        return ""
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return f"{text[:limit]}..." if len(text) > limit else text


class HeyboxAccount:
    def __init__(self, name: str, cookie: str):
        self.raw_cookie = str(cookie or "").strip()
        self.heybox_id = decode_pkey_to_user_id(self.raw_cookie)
        if not self.heybox_id:
            raise ValueError("无法从 pkey 解析 heybox_id，请确认 Cookie 完整")
        self.name = str(name or "").strip() or self.heybox_id
        self.imei = make_imei(self.raw_cookie)
        self.device_info = APP_PROFILE["device_info"]
        self.app_cookie = build_app_cookie(self.raw_cookie)


class HeyboxClient:
    def __init__(self, account: HeyboxAccount, timeout: int, retry_count: int, retry_interval: int):
        self.account = account
        self.timeout = timeout
        self.retry_count = retry_count
        self.retry_interval = retry_interval
        self.runtime = {"version": "", "build": ""}
        self.session = requests.Session()

    def app_headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": APP_UA,
            "Referer": APP_REFERER,
            "Cookie": self.account.app_cookie,
            "Accept": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        data: Optional[str] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        method = method.upper()
        attempts = max(1, self.retry_count + 1)
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                    json=json_body,
                    timeout=self.timeout,
                )
                if response.status_code >= 500 and attempt < attempts:
                    logger.warning(f"小黑盒请求 HTTP {response.status_code}，第 {attempt}/{attempts} 次重试：{method} {url}")
                elif not 200 <= response.status_code < 300:
                    raise RuntimeError(f"HTTP {response.status_code}: {response_preview(response)}")
                else:
                    try:
                        data_obj = response.json()
                    except Exception:
                        raise RuntimeError(f"JSON解析失败：{response_preview(response)}")
                    if not isinstance(data_obj, dict):
                        raise RuntimeError("响应不是 JSON 对象")
                    return data_obj
            except Exception as err:
                last_error = err
                if attempt >= attempts:
                    break
                logger.warning(f"小黑盒请求异常，第 {attempt}/{attempts} 次重试：{method} {url}，错误：{err}")

            if self.retry_interval > 0:
                time.sleep(self.retry_interval)

        raise RuntimeError(str(last_error) if last_error else f"请求失败：{method} {url}")

    def request_hkey(self, path: str, time_sec: Optional[int] = None) -> Dict[str, str]:
        now = str(time_sec or int(time.time()))
        query = build_query_string({
            "mode": "request",
            "path": path,
            "time": now,
            "imei": self.account.imei,
            "heybox_id": self.account.heybox_id,
        })
        payload = self.request_json("GET", f"{HKEY_API}?{query}", headers={"User-Agent": APP_UA, "Accept": "application/json"})
        status = to_text(payload.get("status"))
        if status and status != OK_STATE:
            raise RuntimeError(f"hkey接口失败 status={status} msg={to_text(payload.get('msg')) or '无'}")
        result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        hkey = to_text(result.get("hkey"))
        version = to_text(result.get("version"))
        build = to_text(result.get("build"))
        if not hkey:
            raise RuntimeError("hkey接口未返回 hkey")
        if not version:
            raise RuntimeError("hkey接口未返回 version")
        if not re.match(r"^\d+$", build):
            raise RuntimeError("hkey接口未返回有效 build")
        return {"hkey": hkey, "version": version, "build": build, "time": now}

    def build_signed_query(self, path: str, hkey_result: Dict[str, str], extra_query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if hkey_result.get("version"):
            self.runtime["version"] = hkey_result["version"]
        if hkey_result.get("build"):
            self.runtime["build"] = hkey_result["build"]
        query = {
            "heybox_id": self.account.heybox_id,
            "imei": self.account.imei,
            "device_info": self.account.device_info,
            "nonce": make_nonce(),
            "hkey": hkey_result.get("hkey"),
            "os_type": APP_PROFILE["os_type"],
            "x_os_type": APP_PROFILE["x_os_type"],
            "x_client_type": APP_PROFILE["x_client_type"],
            "os_version": APP_PROFILE["os_version"],
            "version": self.runtime["version"],
            "build": self.runtime["build"],
            "_time": hkey_result.get("time"),
            "dw": APP_PROFILE["dw"],
            "channel": APP_PROFILE["channel"],
            "x_app": APP_PROFILE["x_app"],
            "time_zone": APP_PROFILE["time_zone"],
        }
        if extra_query:
            query.update(extra_query)
        return query

    def get_json(self, path: str, extra_query: Optional[Dict[str, Any]] = None, base_url: str = API_BASE) -> Dict[str, Any]:
        time_sec = int(time.time())
        hkey = self.request_hkey(path, time_sec)
        query = build_query_string(self.build_signed_query(path, hkey, extra_query))
        return self.request_json("GET", f"{base_url}{path}?{query}", headers=self.app_headers())

    def post_encrypted_form(
        self,
        path: str,
        text_payload: str,
        extra_query: Optional[Dict[str, Any]] = None,
        base_url: str = DATA_BASE,
    ) -> Dict[str, Any]:
        time_sec = str(int(time.time()))
        hkey_payload = self.request_json(
            "POST",
            HKEY_API,
            headers={"Content-Type": "application/json"},
            json_body={
                "mode": "report",
                "path": path,
                "text": text_payload,
                "time": time_sec,
                "imei": self.account.imei,
                "heybox_id": self.account.heybox_id,
            },
        )
        result = hkey_payload.get("result") if isinstance(hkey_payload.get("result"), dict) else {}
        if result.get("version"):
            self.runtime["version"] = to_text(result.get("version"))
        if result.get("build"):
            self.runtime["build"] = to_text(result.get("build"))
        if not all(result.get(key) for key in ("hkey", "data", "key", "sid", "time")):
            raise RuntimeError(f"hkey report 未返回完整加密参数：{json.dumps(hkey_payload, ensure_ascii=False)[:300]}")

        query = self.build_signed_query(
            path,
            {
                "hkey": to_text(result.get("hkey")),
                "version": self.runtime["version"],
                "build": self.runtime["build"],
                "time": to_text(result.get("time")),
            },
            {"time_": result.get("time"), **(extra_query or {})},
        )
        body = build_query_string({"data": result.get("data"), "key": result.get("key"), "sid": result.get("sid")})
        return self.request_json(
            "POST",
            f"{base_url}{path}?{build_query_string(query)}",
            headers=self.app_headers({"Content-Type": "application/x-www-form-urlencoded"}),
            data=body,
        )


class HeyboxSignin(_PluginBase):
    plugin_name = "小黑盒每日任务"
    plugin_desc = "根据小黑盒 App 接口执行每日签到和支持的每日任务。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.0.0"
    plugin_author = "你能少吃点吗"
    author_url = "https://github.com/bingbinghj/MoviePilot-Plugins"
    plugin_config_prefix = "heyboxsignin_"
    plugin_order = 53
    auth_level = 1

    MAX_ACCOUNT_COUNT = 20

    _enabled = False
    _onlyonce = False
    _notify = True
    _cron = "10 9 * * *"
    _timeout = 20
    _retry_count = 1
    _retry_interval = 3
    _share_tasks = True
    _account_count = 1
    _account_configs: List[Dict[str, Any]] = []
    _last_result: Dict[str, Any] = {}

    def init_plugin(self, config: dict = None):
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._notify = bool(config.get("notify", True))
        self._cron = config.get("cron") or self._cron
        self._timeout = max(5, self.__to_int(config.get("timeout"), 20))
        self._retry_count = max(0, self.__to_int(config.get("retry_count"), 1))
        self._retry_interval = max(0, self.__to_int(config.get("retry_interval"), 3))
        self._share_tasks = bool(config.get("share_tasks", True))
        self._account_configs = self.__load_account_configs(config)
        default_account_count = max([
            index for index, account in enumerate(self._account_configs, start=1)
            if account.get("name") or account.get("cookie")
        ] or [1])
        self._account_count = max(1, min(self.MAX_ACCOUNT_COUNT, self.__to_int(config.get("account_count"), default_account_count)))

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
        return [{
            "cmd": "/heybox_signin",
            "event": EventType.PluginAction,
            "desc": "立即执行小黑盒每日任务",
            "category": "插件命令",
            "data": {"action": "heybox_signin"},
        }]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self.get_state():
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except Exception as err:
            logger.error(f"{self.plugin_name} Cron 表达式无效：{err}")
            return []
        return [{
            "id": f"{self.__class__.__name__}.signin",
            "name": self.plugin_name,
            "trigger": trigger,
            "func": self.signin,
            "kwargs": {},
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/signin",
            "endpoint": self.api_signin,
            "methods": ["POST"],
            "auth": "bear",
            "summary": "立即执行小黑盒每日任务",
        }]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        model = {
            "enabled": False,
            "onlyonce": False,
            "notify": True,
            "cron": "10 9 * * *",
            "timeout": 20,
            "retry_count": 1,
            "retry_interval": 3,
            "share_tasks": True,
            "account_count": 1,
        }
        for index in range(1, self.MAX_ACCOUNT_COUNT + 1):
            model.update({
                f"account_{index}_enabled": index == 1,
                f"account_{index}_name": "",
                f"account_{index}_cookie": "",
            })

        return [{
            "component": "VForm",
            "content": [
                {
                    "component": "VRow",
                    "content": [
                        self.__col_switch("enabled", "启用插件", 3),
                        self.__col_switch("onlyonce", "仅运行一次", 3),
                        self.__col_switch("notify", "发送通知", 3),
                        self.__col_switch("share_tasks", "执行分享任务", 3),
                    ],
                },
                {
                    "component": "VRow",
                    "content": [
                        self.__col_text("cron", "Cron 表达式", "10 9 * * *", 4),
                        self.__col_text("timeout", "请求超时秒数", "20", 3, "number"),
                        self.__col_text("retry_count", "失败重试次数", "1", 2, "number"),
                        self.__col_text("retry_interval", "重试间隔秒数", "3", 3, "number"),
                    ],
                },
                *[self.__account_config_card(index) for index in range(1, self.MAX_ACCOUNT_COUNT + 1)],
                {
                    "component": "VRow",
                    "content": [{
                        "component": "VCol",
                        "props": {"cols": 12},
                        "content": [{
                            "component": "VBtn",
                            "props": {
                                "color": "primary",
                                "variant": "tonal",
                                "prepend-icon": "mdi-plus",
                                "disabled": "{{ account_count >= 20 }}",
                                "onClick": (
                                    "function(event) { "
                                    "const next = Math.min(20, Number(account_count || 1) + 1); "
                                    "model['account_' + next + '_enabled'] = true; "
                                    "account_count = next; "
                                    "}"
                                ),
                            },
                            "text": "新增账号",
                        }],
                    }],
                },
            ],
        }], model

    def get_page(self) -> List[dict]:
        if not self._last_result:
            return [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "暂无执行记录"}}]

        rows = []
        for item in self._last_result.get("items", []):
            rows.append({
                "component": "tr",
                "content": [
                    {"component": "td", "text": item.get("name") or "-"},
                    {"component": "td", "text": item.get("heybox_id") or "-"},
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
                        "content": [{
                            "component": "tr",
                            "content": [
                                {"component": "th", "text": "账号"},
                                {"component": "th", "text": "黑盒ID"},
                                {"component": "th", "text": "状态"},
                                {"component": "th", "text": "结果"},
                                {"component": "th", "text": "详情"},
                            ],
                        }],
                    },
                    {"component": "tbody", "content": rows},
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
        if event_data.get("action") == "heybox_signin":
            self.signin(manual=True)

    def signin(self, manual: bool = False) -> Dict[str, Any]:
        accounts = [
            account for account in self._account_configs
            if account.get("enabled") and self.__clean(account.get("cookie"))
        ]
        if not accounts:
            return self.__finish(False, "配置不完整", "请至少配置一个小黑盒 Cookie", [])

        logger.info(f"{self.plugin_name} 开始执行，账号数：{len(accounts)}")
        items = []
        for index, account_config in enumerate(accounts, start=1):
            name = account_config.get("name") or f"小黑盒账号 {index}"
            try:
                account = HeyboxAccount(name, account_config.get("cookie") or "")
                client = HeyboxClient(account, self._timeout, self._retry_count, self._retry_interval)
                item = self.__run_account(account, client)
                items.append(item)
            except Exception as err:
                logger.exception(f"{self.plugin_name} [{name}] 执行失败：{err}")
                items.append(self.__item(False, name, "", f"执行失败：{err}", ""))

        success_count = sum(1 for item in items if item.get("success"))
        success = success_count == len(items)
        title = "全部完成" if success else "部分失败"
        message = f"成功 {success_count}/{len(items)}"
        return self.__finish(success, title, message, items)

    def __run_account(self, account: HeyboxAccount, client: HeyboxClient) -> Dict[str, Any]:
        logs = ["开始每日任务"]
        snapshot = self.__fetch_snapshot(client)
        logs.append(f"账号={snapshot.get('nickname') or account.heybox_id} 黑盒ID={account.heybox_id} IMEI={account.imei}")

        done = set()
        unsupported = set()
        failures = []
        daily_tasks = [task for task in snapshot.get("tasks", []) if self.__is_daily_task(task)]

        for task in daily_tasks:
            if task.get("state") == FINISH_STATE:
                done.add(task.get("title") or self.__task_key(task))
                award = f" ({task.get('awardText')})" if task.get("awardText") else ""
                logs.append(f"{task.get('title')}: 已完成{award}")

        for task in [item for item in daily_tasks if item.get("state") == WAITING_STATE]:
            key = self.__task_key(task)
            snapshot = self.__fetch_snapshot(client)
            latest_task = self.__find_task_by_key(snapshot, key)
            if not latest_task or latest_task.get("state") != WAITING_STATE:
                continue

            if not self._share_tasks and not self.__is_sign_task(latest_task):
                unsupported.add(latest_task.get("title") or key)
                logs.append(f"{latest_task.get('title')}: 已跳过，分享任务未启用")
                continue

            result = self.__execute_task(latest_task, client)
            if result.get("unsupported"):
                unsupported.add(latest_task.get("title") or key)
                logs.append(f"{latest_task.get('title')}: 未支持，{result.get('message')}")
                continue

            snapshot = result.get("snapshot") or self.__fetch_snapshot(client)
            after = self.__find_task_by_key(snapshot, key)
            if after and after.get("state") == FINISH_STATE:
                done.add(after.get("title") or key)
                award = f" 奖励: {latest_task.get('awardText')}" if latest_task.get("awardText") else ""
                extra = f" ({result.get('message')})" if result.get("message") else ""
                logs.append(f"{after.get('title')}: 已完成{award}{extra}")
            else:
                msg = result.get("message") or "未完成"
                failures.append(f"{latest_task.get('title')}: {msg}")
                logs.append(f"{latest_task.get('title')}: 未完成，{msg}")

        snapshot = self.__fetch_snapshot(client)
        coin = snapshot.get("coin") or "未知"
        logs.append(f"当前总H币: {coin}")
        if unsupported:
            logs.append(f"未支持或已跳过任务: {' | '.join(sorted(unsupported))}")

        remaining = [
            task for task in snapshot.get("tasks", [])
            if self.__is_daily_task(task) and task.get("state") == WAITING_STATE
        ]
        if not self._share_tasks:
            remaining = [task for task in remaining if self.__is_sign_task(task)]

        ok = not failures and not remaining
        message = f"完成 {len(done)} 个任务，当前总H币 {coin}"
        if failures:
            message = f"{message}，失败 {len(failures)} 个"
        if remaining:
            message = f"{message}，仍有待完成 {len(remaining)} 个"
        return self.__item(ok, account.name, account.heybox_id, message, "\n".join(logs))

    def __fetch_snapshot(self, client: HeyboxClient) -> Dict[str, Any]:
        return self.__extract_task_list(client.get_json(PATH_LIST))

    def __execute_task(self, task: Dict[str, Any], client: HeyboxClient) -> Dict[str, Any]:
        if not self.__is_daily_task(task):
            return {"ok": False, "unsupported": True, "message": "不是脚本处理的每日任务"}
        try:
            if self.__is_sign_task(task):
                return self.__execute_sign(client)
            task_id = task.get("taskId")
            if task_id == "1":
                return self.__execute_share_post(task, client)
            if task_id == "19":
                return self.__execute_share_game_detail(task, client)
            if task_id == "31":
                return self.__execute_share_game_comment(task, client)
            return {"ok": False, "unsupported": True, "message": f"未支持任务 task_id={task_id}"}
        except Exception as err:
            return {"ok": False, "message": f"{task.get('title')} 请求异常 {err}"}

    def __execute_sign(self, client: HeyboxClient) -> Dict[str, Any]:
        sign_resp = client.get_json(PATH_SIGN)
        first_state = to_text((sign_resp.get("result") or {}).get("state"))
        if first_state == "ignore":
            return {"ok": True, "message": "今日已签到"}

        time.sleep(0.8)
        final_payload = client.get_json(PATH_STATE)
        result = final_payload.get("result") or {}
        status = to_text(final_payload.get("status"))
        state = to_text(result.get("state"))
        if (status == OK_STATE and state == OK_STATE) or state == "ignore":
            parts = []
            if result.get("sign_in_coin"):
                parts.append(f"+{result.get('sign_in_coin')}H币")
            if result.get("sign_in_exp"):
                parts.append(f"+{result.get('sign_in_exp')}经验")
            if result.get("sign_in_streak"):
                parts.append(f"连签{result.get('sign_in_streak')}天")
            return {"ok": True, "message": " ".join(parts) if parts else "签到完成"}
        return {"ok": False, "message": to_text(final_payload.get("msg")) or state or "签到失败"}

    def __execute_share_post(self, task: Dict[str, Any], client: HeyboxClient) -> Dict[str, Any]:
        payload = client.get_json(PATH_FEEDS, FEEDS_QUERY_BASE)
        if not self.__is_ok_payload(payload):
            return {"ok": False, "message": f"{task.get('title')} 拉取帖子流失败"}
        posts = self.__extract_feed_candidates(payload)
        if not posts:
            return {"ok": False, "message": f"{task.get('title')} 没有可用帖子"}
        post = posts[0]

        time.sleep(1)
        view_payload = json.dumps({
            "duration": [{
                "id": int(post["linkId"]),
                "duration": POST_SHARE_VIEW_SECONDS,
                "duration_ms": POST_SHARE_VIEW_MILLISECONDS,
                "type": "link",
                "time": int(time.time()),
                "h_src": post["hSrc"],
            }],
            "shows": [],
            "disappear": [],
        }, ensure_ascii=False, separators=(",", ":"))
        view_resp = client.post_encrypted_form(PATH_VIEW_TIME, view_payload, {}, DATA_BASE)
        if not self.__is_ok_payload(view_resp):
            return {"ok": False, "message": f"{task.get('title')} view_time 上报失败"}

        self.__send_share_events(client, "link", {"link_id": post["linkId"], "h_src": post["hSrc"]})
        return self.__settle_share_task(task, client, f"link_id={post['linkId']}")

    def __execute_share_game_detail(self, task: Dict[str, Any], client: HeyboxClient) -> Dict[str, Any]:
        payload = client.get_json(PATH_GAME_RECOMMEND, GAME_RECOMMEND_QUERY_BASE)
        if not self.__is_ok_payload(payload):
            return {"ok": False, "message": f"{task.get('title')} 拉取游戏列表失败"}
        games = self.__extract_recommend_game_candidates(payload)
        if not games:
            return {"ok": False, "message": f"{task.get('title')} 没有可用游戏"}
        game = games[0]
        time.sleep(1)
        self.__send_share_events(client, "game_detail", {"app_id": game["appid"], "h_src": game["hSrc"]})
        return self.__settle_share_task(task, client, f"appid={game['appid']}")

    def __execute_share_game_comment(self, task: Dict[str, Any], client: HeyboxClient) -> Dict[str, Any]:
        recommend_payload = client.get_json(PATH_GAME_RECOMMEND, GAME_RECOMMEND_QUERY_BASE)
        if not self.__is_ok_payload(recommend_payload):
            return {"ok": False, "message": f"{task.get('title')} 拉取游戏列表失败"}
        games = self.__extract_recommend_game_candidates(recommend_payload)
        if not games:
            return {"ok": False, "message": f"{task.get('title')} 没有可用游戏"}
        game = games[0]
        comments_payload = client.get_json(PATH_GAME_COMMENTS, {**GAME_COMMENTS_QUERY_BASE, "appid": game["appid"]})
        if not self.__is_ok_payload(comments_payload):
            return {"ok": False, "message": f"{task.get('title')} 拉取游戏评论失败"}
        comment = self.__extract_game_comment_candidate(comments_payload)
        if not comment:
            return {"ok": False, "message": f"{task.get('title')} 评论列表缺少关键字段"}
        self.__send_share_events(client, "game_comment", {"link_id": comment["linkId"]})
        return self.__settle_share_task(task, client, f"appid={game['appid']}")

    def __settle_share_task(self, task: Dict[str, Any], client: HeyboxClient, detail: str = "") -> Dict[str, Any]:
        time.sleep(SHARE_TASK_SETTLE_SECONDS)
        snapshot = self.__fetch_snapshot(client)
        after = self.__find_task_by_key(snapshot, self.__task_key(task))
        if after and after.get("state") == FINISH_STATE:
            return {"ok": True, "message": f"{task.get('title')} 完成 {detail}".strip(), "snapshot": snapshot}
        return {"ok": False, "message": f"{task.get('title')} 未完成"}

    def __send_share_events(self, client: HeyboxClient, source: str, extra: Dict[str, Any]):
        session_id = str(uuid.uuid4())
        for action in ("tap", "success"):
            payload = json.dumps({
                "events": [{
                    "type": "4" if action == "tap" else "3",
                    "path": "/share/behavior/tap" if action == "tap" else "/share/behavior/success",
                    "time": str(int(time.time())),
                    "addition": {**extra, "src": source, "plat": "WechatSession"},
                }],
            }, ensure_ascii=False, separators=(",", ":"))
            resp = client.post_encrypted_form(
                PATH_DATA_REPORT,
                payload,
                {"type": "104", "session_id": session_id},
                DATA_BASE,
            )
            if not self.__is_ok_payload(resp):
                raise RuntimeError(f"分享 {action} 上报失败 status={to_text(resp.get('status'))} msg={to_text(resp.get('msg'))}")
            if action == "tap":
                time.sleep(2)

    @staticmethod
    def __extract_task_list(payload: Dict[str, Any]) -> Dict[str, Any]:
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        user = result.get("user") if isinstance(result.get("user"), dict) else {}
        level_info = user.get("level_info") if isinstance(user.get("level_info"), dict) else {}
        groups = result.get("task_list") if isinstance(result.get("task_list"), list) else []

        tasks = []
        for group in groups:
            group_title = to_text(group.get("title"))
            task_list = group.get("tasks") if isinstance(group.get("tasks"), list) else []
            for item in task_list:
                report_extra = item.get("report_extra") if isinstance(item.get("report_extra"), dict) else {}
                awards = item.get("award_desc_v2") if isinstance(item.get("award_desc_v2"), list) else []
                award_texts = []
                for award in awards:
                    desc = to_text(award.get("desc"))
                    icon = to_text(award.get("icon"))
                    if "b9aca51c" in icon:
                        award_texts.append(f"{desc}H币")
                    elif "c10d89ae" in icon:
                        award_texts.append(f"{desc}经验")
                    elif "e63b192a" in icon:
                        award_texts.append(f"{desc}盒电")
                    elif desc:
                        award_texts.append(desc)
                tasks.append({
                    "groupTitle": group_title,
                    "title": to_text(item.get("title")),
                    "state": to_text(item.get("state")),
                    "stateDesc": to_text(item.get("state_desc")),
                    "taskId": to_text(report_extra.get("task_id")),
                    "taskType": to_text(item.get("type")),
                    "reportTaskType": to_text(report_extra.get("task_type")),
                    "awardText": " ".join(filter(None, award_texts)),
                })

        return {
            "nickname": to_text(user.get("username")),
            "coin": to_text(level_info.get("coin")),
            "tasks": tasks,
        }

    @staticmethod
    def __collect_objects(root: Any, matcher, limit: int = 20) -> List[Dict[str, Any]]:
        out = []
        stack = [root]
        while stack:
            node = stack.pop()
            if not isinstance(node, (dict, list)):
                continue
            if isinstance(node, dict) and matcher(node):
                out.append(node)
                if len(out) >= limit:
                    break
            values = node if isinstance(node, list) else list(node.values())
            stack.extend(reversed(values))
        return out

    @staticmethod
    def __extract_feed_candidates(payload: Dict[str, Any]) -> List[Dict[str, str]]:
        links = ((payload.get("result") or {}).get("links") or [])
        if not isinstance(links, list):
            return []
        seen = set()
        out = []
        for item in links:
            link_id = to_text(item.get("link_id"))
            h_src = to_text(item.get("h_src"))
            if not re.match(r"^\d+$", link_id) or not h_src:
                continue
            key = f"{link_id}|{h_src}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"linkId": link_id, "hSrc": h_src})
        return out

    def __extract_recommend_game_candidates(self, payload: Dict[str, Any]) -> List[Dict[str, str]]:
        objects = self.__collect_objects(
            (payload.get("result") or {}),
            lambda node: "appid" in node and "h_src" in node,
            40,
        )
        seen = set()
        out = []
        for obj in objects:
            appid = to_text(obj.get("appid"))
            h_src = to_text(obj.get("h_src"))
            if not re.match(r"^\d+$", appid) or not h_src:
                continue
            key = f"{appid}|{h_src}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"appid": appid, "hSrc": h_src})
        return out

    @staticmethod
    def __extract_game_comment_candidate(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
        links = ((payload.get("result") or {}).get("links") or [])
        if not isinstance(links, list):
            return None
        for item in links:
            link_id = to_text(item.get("linkid") or item.get("link_id"))
            h_src = to_text(item.get("h_src"))
            user_id = to_text(item.get("userid"))
            if re.match(r"^\d+$", link_id) and re.match(r"^\d+$", user_id) and h_src:
                return {"linkId": link_id, "hSrc": h_src, "userId": user_id}
        return None

    @staticmethod
    def __is_ok_payload(payload: Dict[str, Any]) -> bool:
        return to_text((payload or {}).get("status")) == OK_STATE

    @staticmethod
    def __task_key(task: Dict[str, Any]) -> str:
        return f"{task.get('taskId')}|{task.get('title')}"

    def __find_task_by_key(self, snapshot: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
        for task in snapshot.get("tasks", []):
            if self.__task_key(task) == key:
                return task
        return None

    @staticmethod
    def __is_sign_task(task: Dict[str, Any]) -> bool:
        return task.get("taskType") == "sign"

    def __is_daily_task(self, task: Dict[str, Any]) -> bool:
        return self.__is_sign_task(task) or task.get("reportTaskType") == "daily"

    def __load_account_configs(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        accounts = []
        for index in range(1, self.MAX_ACCOUNT_COUNT + 1):
            accounts.append({
                "enabled": bool(config.get(f"account_{index}_enabled", index == 1)),
                "name": self.__clean(config.get(f"account_{index}_name")),
                "cookie": self.__clean(config.get(f"account_{index}_cookie")),
            })
        return accounts

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
            "share_tasks": self._share_tasks,
            "account_count": self._account_count,
        }
        for index, account in enumerate(self._account_configs[:self.MAX_ACCOUNT_COUNT], start=1):
            config.update({
                f"account_{index}_enabled": bool(account.get("enabled")),
                f"account_{index}_name": account.get("name") or "",
                f"account_{index}_cookie": account.get("cookie") or "",
            })
        self.update_config(config)

    @staticmethod
    def __item(success: bool, name: str, heybox_id: str, message: str, detail: str = "") -> Dict[str, Any]:
        return {
            "success": success,
            "name": name,
            "heybox_id": heybox_id,
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
    def __account_config_card(index: int) -> dict:
        show_props = {"show": f"{{{{ account_count >= {index} }}}}"} if index > 1 else {}
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "class": "mb-3", **show_props},
            "content": [
                {"component": "VCardTitle", "props": {"class": "text-subtitle-1"}, "text": f"账号 {index}"},
                {
                    "component": "VCardText",
                    "content": [
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 3},
                                    "content": [{"component": "VSwitch", "props": {"model": f"account_{index}_enabled", "label": "启用"}}],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 9},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": f"account_{index}_name",
                                            "label": "账号名称",
                                            "placeholder": "可选",
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12},
                                    "content": [{
                                        "component": "VTextarea",
                                        "props": {
                                            "model": f"account_{index}_cookie",
                                            "label": "Cookie",
                                            "placeholder": "pkey=xxx;x_xhh_tokenid=xxx;",
                                            "rows": 3,
                                            "auto-grow": True,
                                        },
                                    }],
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
