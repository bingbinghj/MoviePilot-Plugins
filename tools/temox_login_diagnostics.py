"""Record one Temox login and its follow-up states, without persisting credentials."""

import argparse
import ast
from datetime import datetime
import getpass
import hashlib
import html
import importlib.util
import json
from pathlib import Path
import re
import time
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests


ROOT = Path(__file__).resolve().parents[1]
CREDIT_COOKIES = ("creditnotice", "creditrule", "creditbase")
PRIVATE_FIELDS = {"username", "password", "formhash", "answer", "auth", "token", "sid", "salt", "uid"}


class Recorder:
    """Keep a timeline of HTTP responses and sanitized request, page and Cookie data."""

    def __init__(self, directory: Path, username: str, password: str):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.private = {username, password}
        self.events = []
        self.previous_cookies = {}
        self.phase = "login_page"

    def redact(self, value: str) -> str:
        """Remove credentials, auth Cookie values and common embedded security tokens."""
        for secret in sorted(self.private, key=len, reverse=True):
            if not secret:
                continue
            for encoded in {secret, quote(secret, safe=""), html.escape(secret, quote=True)}:
                value = value.replace(encoded, "[redacted]")
        value = re.sub(r'''(?i)(\b(?:formhash|auth|token|sid|salt|discuz_uid)\s*[=:]\s*)(["'])(.*?)\2''',
                       r'\1\2[redacted]\2', value)
        value = re.sub(r'''(?i)(name\s*=\s*["'](?:formhash|password|username|answer)["'][^>]*value\s*=\s*)(["'])(.*?)\2''',
                       r'\1\2[redacted]\2', value)
        value = re.sub(r'''(?i)([?&](?:formhash|auth|token|sid|salt|uid)=)[^&\s"'<>]+''', r'\1[redacted]', value)
        # The last creditnotice field is a user ID; preserve credit amounts, not that identifier.
        value = re.sub(r'((?:[+-]?\d+D){9})\d+', r'\1[user]', value)
        return value

    def safe_url(self, url: str) -> str:
        """Keep paths and routing arguments while removing security fields."""
        parts = urlsplit(url)
        query = [(key, "[redacted]" if key.lower() in PRIVATE_FIELDS else value)
                 for key, value in parse_qsl(parts.query, keep_blank_values=True)]
        return self.redact(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)))

    def cookie_rows(self, cookies) -> list:
        """Preserve reward Cookie content and track opaque auth Cookies by digest."""
        rows = []
        for cookie in cookies:
            is_credit = cookie.name.endswith(CREDIT_COOKIES)
            if not is_credit:
                self.private.add(cookie.value)
            rows.append({"name": cookie.name, "domain": cookie.domain, "path": cookie.path,
                         "expires": cookie.expires, "secure": cookie.secure,
                         "value": self.redact(cookie.value) if is_credit else "[redacted]",
                         "decoded_value": self.redact(unquote(cookie.value)) if is_credit else "[redacted]",
                         "value_sha256": hashlib.sha256(cookie.value.encode()).hexdigest(),
                         "is_reward_cookie": is_credit})
        return rows

    def capture(self, response, session, probe, **kwargs):
        """Record every response, including redirects before the next request changes Cookies."""
        response_rows = self.cookie_rows(response.cookies)
        jar = requests.cookies.RequestsCookieJar()
        jar.update(session.cookies)
        jar.update(response.cookies)
        rows = self.cookie_rows(jar)
        current = {f"{row['domain']}|{row['path']}|{row['name']}": row["value_sha256"] for row in rows}
        delta = {"added": sorted(set(current) - set(self.previous_cookies)),
                 "removed": sorted(set(self.previous_cookies) - set(current)),
                 "changed": sorted(key for key in current if key in self.previous_cookies
                                   and current[key] != self.previous_cookies[key])}
        self.previous_cookies = current
        page = probe._TemoxSignin__response_text(response)
        reward = credit_prompt(page, jar.get_dict())
        number = len(self.events) + 1
        filename = f"{number:03d}-{self.phase}.html"
        (self.directory / filename).write_text(self.redact(page), encoding="utf-8")
        body = response.request.body or ""
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        fields = [(key, "[redacted]" if key.lower() in PRIVATE_FIELDS else self.redact(value))
                  for key, value in parse_qsl(body, keep_blank_values=True)]
        safe_headers = {}
        for key, value in response.request.headers.items():
            safe_headers[key] = "[redacted]" if key.lower() in {"cookie", "authorization"} else self.redact(value)
        event = {"time": datetime.now().astimezone().isoformat(), "phase": self.phase,
                 "request": {"method": response.request.method, "url": self.safe_url(response.request.url),
                             "headers": safe_headers, "form": fields},
                 "response": {"status": response.status_code, "url": self.safe_url(response.url),
                              "elapsed_seconds": response.elapsed.total_seconds(),
                              "headers": {key: self.redact(value) for key, value in response.headers.items()
                                          if key.lower() not in {"set-cookie", "authorization"}},
                              "body_bytes": len(response.content), "page": filename,
                              "cookies": response_rows},
                 "session_cookies": rows, "cookie_changes": delta,
                 "logged_in": probe._TemoxSignin__is_logged_in(page),
                 "login_prompt": self.redact(login_prompt(page) or ""),
                 "reward_prompt": self.redact(reward or ""),
                 "credit_labels": self.redact(message_module.variable(page, "creditnotice")),
                 "rendered_messages": [(name, self.redact(value)) for name, value in message_module.rendered_messages(page)],
                 "reward_trigger_present": "showCreditPrompt" in page}
        self.events.append(event)
        self.save()

    def save(self, error=None):
        """Persist a partial timeline after each response so failures retain their evidence."""
        report = {"captured_at": datetime.now().astimezone().isoformat(), "events": self.events,
                  "error": self.redact(str(error)) if error else None,
                  "limits": "HTTP state capture; JavaScript is not executed. Reward popup data is parsed from the server response and Cookies."}
        (self.directory / "timeline.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def load_probe():
    """Reuse the plugin's page decoding, arithmetic gate and login-form logic without a host."""
    global message_module, credit_prompt, login_prompt
    source_path = ROOT / "plugins.v3/temoxsignin/__init__.py"
    spec = importlib.util.spec_from_file_location("temox_diagnostic_messages", source_path.with_name("messages.py"))
    message_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(message_module)
    credit_prompt = message_module.credit_prompt
    login_prompt = message_module.login_prompt
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "TemoxSignin")
    methods = {"__get_with_gate", "__response_text", "__is_reload_page", "__extract_math_answer",
               "__extract_login_form", "__get_attr", "__is_logged_in", "__clean_text"}
    node.bases = []
    node.body = [item for item in node.body if isinstance(item, ast.FunctionDef) and item.name in methods]
    logger = MockLogger()
    namespace = {**globals(), "logger": logger}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "<temox-probe>", "exec"), namespace)
    probe = namespace["TemoxSignin"]()
    probe.plugin_name = "Temox diagnostics"
    probe._timeout = 30
    return probe


class MockLogger:
    """Keep login secrets and site output out of terminal logs."""

    def info(self, *args, **kwargs):
        pass


def main():
    """Login once, then capture the immediate page and later states through 15 seconds."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="http://bt.temox.com:8080")
    parser.add_argument("--output-root", type=Path, default=ROOT / ".diagnostics/temox")
    args = parser.parse_args()
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    directory = args.output_root / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    recorder = Recorder(directory, username, password)
    probe = load_probe()
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 Chrome/126.0 Safari/537.36",
                            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    session.hooks["response"].append(lambda response, **kwargs: recorder.capture(response, session, probe, **kwargs))
    try:
        url = urljoin(args.site.rstrip("/") + "/", "member.php?mod=logging&action=login")
        response = probe._TemoxSignin__get_with_gate(session, url)
        form = probe._TemoxSignin__extract_login_form(probe._TemoxSignin__response_text(response))
        if not form:
            raise RuntimeError("Login form not found; inspect the recorded page")
        action, fields = form
        fields.update(username=username, password=password, questionid="0", cookietime="2592000", loginsubmit="true")
        fields.pop("answer", None)
        recorder.phase = "login_submit"
        session.post(urljoin(response.url, action), data=fields, headers={"Referer": url}, timeout=30)
        # The site's welcome script redirects to forum.php. Capture before and after that delay.
        started = time.monotonic()
        for seconds in (0, 3, 8, 15):
            time.sleep(max(0, started + seconds - time.monotonic()))
            recorder.phase = f"after_login_{seconds}s"
            probe._TemoxSignin__get_with_gate(session, urljoin(args.site.rstrip("/") + "/", "forum.php"))
        recorder.save()
        print(f"Recorded {len(recorder.events)} HTTP responses: {directory}")
        print("Reward observed:", any(event["reward_prompt"] for event in recorder.events))
    except Exception as error:
        recorder.save(error)
        print(f"Capture stopped; partial record retained: {directory}")
        raise SystemExit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
