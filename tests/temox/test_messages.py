"""Verify actual Discuz login wording and one-per-day rewards without using account credentials."""

import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("MOVIEPILOT_BACKEND", "/app"))
from app.testing import bootstrap
getattr(bootstrap, "prepare_" + os.environ.get("TEMOX_TEST_GENERATION", "v3") + "_backend")(ROOT)
module = importlib.import_module("app.plugins.temoxsignin")
messages = importlib.import_module("app.plugins.temoxsignin.messages")

# Structure and label units taken from the site's login response; IDs are synthetic.
PAGE = """<script>
var discuz_uid = '123', cookiepre = 'probe_2132_',
creditnotice = '1|经验|P,2|人气|点,3|特萌币|円,4|存款|,5|分享度|¤,6|SAN值|♂,7|特摄魂|℃,8|人品|P';
</script>"""
WELCOME = """<div id="messagetext" class="alert_right"><p>
<script>if($('succeedmessage')) {$('succeedmessage').innerHTML = '';}</script>
<script>setTimeout("window.location.href ='forum.php';", 3000);
$('succeedlocation').innerHTML = '欢迎您回来，祖国花朵 测试用户，现在将转入登录前页面';</script>
</p><p><a href="forum.php">如果您的浏览器没有自动跳转，请点击此链接</a></p></div>"""
COOKIES = {"probe_2132_creditnotice": "0D2D3D0D0D4D0D0D5D123",
           "probe_2132_creditrule": "%E6%AF%8F%E5%A4%A9%E7%99%BB%E5%BD%95"}


class DiscuzMessageTests(unittest.TestCase):
    def test_real_script_shape_returns_only_welcome_string(self):
        self.assertEqual(messages.login_prompt(WELCOME),
                         "欢迎您回来，祖国花朵 测试用户，现在将转入登录前页面")

    def test_escaped_script_literal_is_decoded_without_execution(self):
        text = r'''<script>$('succeedlocation').innerHTML = '欢迎您回来，O\'Brien\n\u6d4b\u8bd5';</script>'''
        # The fixture contains literal backslash escapes from a JavaScript string.
        text = text.replace("\\\\", "\\")
        self.assertEqual(messages.login_prompt(text), "欢迎您回来，O'Brien 测试")

    def test_nested_rendered_success_message_preserves_actual_words(self):
        text = '<p class="succeedmessage">欢迎您回来，<b>用户</b><br>已登录 &amp; 验证</p>'
        self.assertEqual(messages.login_prompt(text), "欢迎您回来，用户 已登录 & 验证")

    def test_reward_uses_actual_values_names_and_units(self):
        self.assertEqual(messages.credit_prompt(PAGE, COOKIES), "每天登录 经验+2P 人气+3点 分享度+4¤ 人品+5P")

    def test_reward_can_change_names_units_and_amounts(self):
        page = PAGE.replace("1|经验|P", "1|贡献|枚")
        cookies = {**COOKIES, "probe_2132_creditnotice": "0D12D0D0D0D0D0D0D0D123"}
        self.assertEqual(messages.credit_prompt(page, cookies), "每天登录 贡献+12枚")

    def test_no_cookie_or_only_credit_rule_never_invents_a_reward(self):
        for cookies in ({}, {"probe_2132_creditrule": COOKIES["probe_2132_creditrule"]}):
            self.assertIsNone(messages.credit_prompt(PAGE, cookies))
        text = PAGE + '<p>每天登录 经验+99P 人气+99点 分享度+99 人品+99P</p>'
        self.assertIsNone(messages.credit_prompt(text, {}))

    def test_stale_other_user_or_other_site_cookie_is_ignored(self):
        for cookies in ({**COOKIES, "probe_2132_creditnotice": "0D2D3D0D0D4D0D0D5D999"},
                        {"other_creditnotice": COOKIES["probe_2132_creditnotice"]},
                        {**COOKIES, "probe_2132_creditnotice": "broken"}):
            self.assertIsNone(messages.credit_prompt(PAGE, cookies))
        self.assertIsNone(messages.credit_prompt(PAGE.replace("'123'", "'0'"), COOKIES))

    def test_zero_changes_do_not_report_reward(self):
        cookies = {**COOKIES, "probe_2132_creditnotice": "0D0D0D0D0D0D0D0D0D123"}
        self.assertIsNone(messages.credit_prompt(PAGE, cookies))

    def test_signed_changes_are_not_assumed_positive(self):
        cookies = {**COOKIES, "probe_2132_creditnotice": "0D-2D0D0D0D0D0D0D0D123"}
        self.assertEqual(messages.credit_prompt(PAGE, cookies), "每天登录 经验-2P")

    def test_rendered_credit_popup_is_used_as_returned(self):
        text = '<div id="creditpromptdiv"><i>每天登录</i> <span>经验<em>+7</em>P</span></div>'
        self.assertEqual(messages.credit_prompt(text, {}), "每天登录 经验+7P")

    def test_first_login_captures_cookie_before_followup_clears_it_and_second_does_not_reuse(self):
        plugin = object.__new__(module.TemoxSignin)
        plugin._username = "test-user"
        plugin._password = "test-password"
        plugin._site_url = "http://example.invalid"
        plugin._timeout = 5
        plugin._questionid = "0"
        plugin._notify = False
        plugin.save_data = Mock()
        for first in (True, False):
            session = Mock()
            session.cookies = requests.cookies.RequestsCookieJar()

            def posted(*args, **kwargs):
                if first:
                    session.cookies.update(COOKIES)
                return Mock(text=PAGE + WELCOME)

            calls = []

            def fetched(*args):
                calls.append(True)
                if len(calls) > 1:
                    session.cookies.clear()
                return Mock(text=PAGE, url="http://example.invalid/login")

            session.post.side_effect = posted
            with patch.object(module.requests, "Session", return_value=session), \
                 patch.object(plugin, "_TemoxSignin__get_with_gate", side_effect=fetched), \
                 patch.object(plugin, "_TemoxSignin__response_text", side_effect=lambda response: response.text), \
                 patch.object(plugin, "_TemoxSignin__extract_login_form",
                              return_value=("/login", {"formhash": "test"})), \
                 patch.object(plugin, "_TemoxSignin__is_logged_in", return_value=True):
                result = plugin.signin()
            self.assertTrue(result["success"])
            self.assertNotIn("';", result["message"])
            self.assertEqual("每天登录" in result["message"], first)
            if first:
                self.assertIn("经验+2P", result["message"])
            session.close.assert_called_once()
        self.assertNotIn("每天登录", plugin._last_result["message"])

    def test_no_reward_keeps_login_result_and_existing_reward_not_duplicated(self):
        plugin = object.__new__(module.TemoxSignin)
        message = "欢迎您回来，用户"
        self.assertEqual(plugin._TemoxSignin__success_message(message), message)
        rewarded = message + "。每天登录 经验+7P"
        self.assertEqual(plugin._TemoxSignin__success_message(rewarded, "每天登录 经验+7P"), rewarded)


if __name__ == "__main__":
    unittest.main()
