"""Read Discuz login messages and its one-per-day credit popup without running JavaScript."""

import html
from html.parser import HTMLParser
import re
import time
from urllib.parse import unquote, urlsplit


JS_STRING = r'''(?P<quote>["'])(?P<value>(?:\x5c.|(?!(?P=quote)).)*)(?P=quote)'''
JS_ARGUMENT = r'''(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")'''


def clean_text(value: str) -> str:
    """Remove markup and script content while keeping the server's wording."""
    value = re.sub(r"<script\b.*?</script>", "", value, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def js_string(value: str) -> str:
    """Decode string-literal escapes without interpreting JavaScript expressions."""
    def decode(match):
        escaped = match.group(1)
        if escaped.startswith(("u", "x")):
            return chr(int(escaped[1:], 16))
        return {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(escaped, escaped)

    return re.sub(r"\\(u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", decode, value, flags=re.S)


def variable(text: str, name: str) -> str:
    """Read a literal variable value used by the site's credit popup."""
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*" + JS_STRING, text, re.S)
    return js_string(match.group("value")) if match else ""


class MessageHTML(HTMLParser):
    """Collect rendered message elements, including nested spans and line breaks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.targets = []
        self.messages = []
        self.script_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        target = attrs.get("id", "")
        if not target and "succeedmessage" in attrs.get("class", "").split():
            target = "succeedmessage"
        if tag == "br":
            self.handle_data(" ")
            return
        if tag in {"img", "input", "meta", "link", "hr"}:
            return
        self.stack.append(tag)
        if tag == "script":
            self.script_depth += 1
        if target in {"succeedmessage", "succeedlocation", "creditpromptdiv", "messagetext"}:
            self.targets.append((len(self.stack), target, []))

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        depth = len(self.stack) - self.stack[::-1].index(tag)
        while self.targets and self.targets[-1][0] >= depth:
            _, target, chunks = self.targets.pop()
            self.messages.append((target, re.sub(r"\s+", " ", "".join(chunks)).strip()))
        if tag == "script":
            self.script_depth = max(0, self.script_depth - 1)
        self.stack = self.stack[:depth - 1]

    def handle_data(self, data):
        if not self.script_depth:
            for _, _, chunks in self.targets:
                chunks.append(data)


def rendered_messages(text: str) -> list:
    """Read a page's explicit message elements, excluding JavaScript source."""
    parser = MessageHTML()
    parser.feed(text)
    return parser.messages


def login_prompt(text: str):
    """Read the actual welcome message, including Discuz's succeedlocation assignment."""
    messages = rendered_messages(text)
    for target in ("succeedlocation", "succeedmessage"):
        pattern = (r'''\$\(\s*["']''' + target + r'''["']\s*\)\.innerHTML\s*=\s*'''
                   + JS_STRING + r"\s*(?:;|$)")
        for match in re.finditer(pattern, text, re.S):
            prompt = clean_text(js_string(match.group("value")))
            if prompt:
                return prompt
        for name, prompt in messages:
            if name == target and prompt:
                return prompt
    # Official AJAX responses can carry the welcome only in a callback or dialog.
    patterns = (
        r"\bsucceedhandle_\w*\s*\(\s*" + JS_ARGUMENT + r"\s*,\s*" + JS_STRING + r"\s*,",
        r"\bshowDialog\s*\(\s*" + JS_STRING + r'''\s*,\s*["']right["']\s*[,)]''',
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.S):
            prompt = clean_text(js_string(match.group("value")))
            if "欢迎您回来" in prompt:
                return prompt
    for name, prompt in messages:
        if name == "messagetext" and "欢迎您回来" in prompt:
            return prompt
    # Some Discuz AJAX responses put their welcome string directly in a literal.
    match = re.search(r'''欢迎您回来[^<\r\n"';]*''', re.sub(r"<script\b.*?</script>", "", text, flags=re.I | re.S))
    return clean_text(match.group(0)) if match else None


def credit_prompt(text: str, cookies: dict):
    """Reproduce the site's credit popup only when it belongs to the logged-in user."""
    for target, prompt in rendered_messages(text):
        if target == "creditpromptdiv" and prompt:
            return prompt
    prefix = variable(text, "cookiepre")
    uid = variable(text, "discuz_uid")
    if not prefix or not re.fullmatch(r"[1-9]\d*", uid):
        return None
    notice = unquote(cookies.get(prefix + "creditnotice", "")).split("D")
    if len(notice) < 10 or notice[9] != uid:
        return None
    labels = {}
    for item in variable(text, "creditnotice").split(","):
        parts = item.split("|")
        if len(parts) == 3 and parts[0].isdigit():
            labels[int(parts[0])] = (parts[1], parts[2])
    parts = []
    for index in range(1, 9):
        value = notice[index]
        if index not in labels or not re.fullmatch(r"[+-]?\d+", value) or int(value) == 0:
            continue
        name, unit = labels[index]
        amount = int(value)
        parts.append(f"{name}{amount:+d}{unit}")
    if not parts:
        return None
    rule = clean_text(unquote(cookies.get(prefix + "creditrule", "")))
    return " ".join(([rule] if rule else []) + parts)


def origin(url: str):
    """Compare actual origins, including the port used by this Discuz site."""
    try:
        parsed = urlsplit(url)
        return parsed.scheme.lower(), parsed.hostname, parsed.port or {"http": 80, "https": 443}.get(parsed.scheme)
    except (TypeError, ValueError):
        return None


def cookies_for_url(cookies, url: str, timestamp=None) -> dict:
    """Keep Cookie domain, path and Secure scope instead of flattening the whole jar."""
    parsed = urlsplit(url)
    host, path = parsed.hostname or "", parsed.path or "/"
    values = {}
    timestamp = time.time() if timestamp is None else timestamp
    for cookie in sorted(cookies, key=lambda item: len(item.path or "/")):
        if cookie.is_expired(timestamp):
            continue
        domain = cookie.domain.lstrip(".").lower()
        if not domain or not (host == domain or (cookie.domain_specified and host.endswith("." + domain))):
            continue
        cookie_path = cookie.path or "/"
        if path != cookie_path and not (path.startswith(cookie_path) and
                                        (cookie_path.endswith("/") or path[len(cookie_path):].startswith("/"))):
            continue
        if cookie.secure and parsed.scheme != "https":
            continue
        values[cookie.name] = cookie.value
    return values


class LoginMessages:
    """Keep this login's response evidence until its authenticated page supplies labels."""

    def __init__(self, site_url: str):
        self._origin = origin(site_url)
        self._cookies = {}
        self._snapshots = []
        self._pages = []
        self._identity = ("", "")
        self._rendered = []
        self._welcomes = []

    def same_origin(self, url: str) -> bool:
        return self._origin is not None and origin(url) == self._origin

    def observe(self, url: str, text: str, cookies, status: int = 200) -> None:
        if not self.same_origin(url):
            return
        if not 200 <= status < 400:
            return
        # Start empty: pre-login or earlier sessions' credit Cookies are not evidence.
        for cookie in cookies:
            if cookie.name.endswith(("creditnotice", "creditrule", "creditbase")):
                self._cookies[(cookie.name, cookie.domain, cookie.path)] = cookie
        if self._cookies:
            self._snapshots.append((tuple(self._cookies.values()), time.time()))
        if not 200 <= status < 300:
            return
        prefix, uid = variable(text, "cookiepre"), variable(text, "discuz_uid")
        if re.fullmatch(r"\d+", uid):
            self._identity = (uid, prefix)
        welcome = login_prompt(text)
        if welcome:
            self._welcomes.append((uid, welcome))
        if prefix and re.fullmatch(r"[1-9]\d*", uid) and variable(text, "creditnotice"):
            self._pages.append((uid, prefix, url, text))
        rendered = credit_prompt(text, {})
        if rendered:
            self._rendered.append((uid, prefix, rendered))

    @property
    def anonymous(self):
        return self._identity[0] == "0"

    @property
    def welcome(self):
        uid = self._identity[0]
        if uid == "0":
            return None
        prompts = [prompt for owner, prompt in self._welcomes if not owner or owner == uid]
        return next((prompt for prompt in reversed(prompts) if "欢迎您回来" in prompt),
                    prompts[-1] if prompts else None)

    @property
    def reward(self):
        uid, prefix = self._identity
        if not uid or uid == "0":
            return None
        # A later deletion must not erase the notification returned by an earlier hop.
        for owner, page_prefix, prompt in reversed(self._rendered):
            if owner == uid and page_prefix == prefix:
                return prompt
        for owner, page_prefix, page_url, page in reversed(self._pages):
            if owner != uid or page_prefix != prefix:
                continue
            for snapshot, timestamp in self._snapshots:
                reward = credit_prompt(page, cookies_for_url(snapshot, page_url, timestamp))
                if reward:
                    return reward
        return None
