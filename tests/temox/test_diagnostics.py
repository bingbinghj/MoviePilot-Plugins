"""Check that the diagnostic timeline preserves reward evidence without leaking login secrets."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

import requests

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("temox_diagnostics", ROOT / "tools/temox_login_diagnostics.py")
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class DiagnosticTests(unittest.TestCase):
    def test_response_records_reward_cookie_and_redacts_login_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder = diagnostics.Recorder(Path(temp) / "capture", "test-account", "test-secret")
            probe = diagnostics.load_probe()
            response = requests.Response()
            response.status_code = 200
            response.url = "http://example.invalid/forum.php?formhash=private-formhash"
            response.request = requests.Request("POST", "http://example.invalid/login",
                                                data={"username": "test-account", "password": "test-secret",
                                                      "formhash": "private-formhash", "questionid": "0"},
                                                headers={"Cookie": "auth=private-auth"}).prepare()
            response.cookies.set("probe_auth", "private-auth", domain="example.invalid", path="/")
            response.cookies.set("probe_creditnotice", "0D2D0D0D0D0D0D0D0D123", domain="example.invalid", path="/")
            response.cookies.set("probe_creditrule", "%E6%AF%8F%E5%A4%A9%E7%99%BB%E5%BD%95",
                                 domain="example.invalid", path="/")
            response.encoding = "utf-8"
            response._content = ("<script>var discuz_uid='123', cookiepre='probe_', creditnotice='1|经验|P';"
                                 "var formhash='private-formhash';"
                                 "$('succeedlocation').innerHTML='欢迎您回来，test-account';</script>"
                                 "<p>test-secret private-auth</p>").encode()
            session = requests.Session()
            recorder.capture(response, session, probe)
            report = json.loads((recorder.directory / "timeline.json").read_text(encoding="utf-8"))
            serialized = (recorder.directory / "timeline.json").read_text(encoding="utf-8")
            page = next(recorder.directory.glob("*.html")).read_text(encoding="utf-8")
            for secret in ("test-account", "test-secret", "private-auth", "private-formhash"):
                self.assertNotIn(secret, serialized + page)
            event = report["events"][0]
            self.assertTrue(event["logged_in"])
            self.assertEqual(event["reward_prompt"], "每天登录 经验+2P")
            self.assertEqual(len(event["response"]["cookies"]), 3)
            self.assertEqual(len(event["cookie_changes"]["added"]), 3)
            reward = next(row for row in event["response"]["cookies"] if row["name"].endswith("creditnotice"))
            self.assertEqual(reward["value"], "0D2D0D0D0D0D0D0D0D[user]")
            session.close()

    def test_partial_timeline_remains_when_later_phase_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder = diagnostics.Recorder(Path(temp) / "capture", "account", "password")
            recorder.events.append({"phase": "login_submit", "response": {"status": 200}})
            recorder.save(RuntimeError("password request failed"))
            report = json.loads((recorder.directory / "timeline.json").read_text(encoding="utf-8"))
            self.assertEqual(report["events"][0]["phase"], "login_submit")
            self.assertEqual(report["error"], "[redacted] request failed")

    def test_cookie_change_tracks_opaque_values_without_saving_them(self):
        with tempfile.TemporaryDirectory() as temp:
            recorder = diagnostics.Recorder(Path(temp) / "capture", "account", "password")
            jar = requests.cookies.RequestsCookieJar()
            jar.set("probe_auth", "first-auth")
            first = recorder.cookie_rows(jar)[0]
            jar.set("probe_auth", "second-auth")
            second = recorder.cookie_rows(jar)[0]
            self.assertEqual(first["value"], "[redacted]")
            self.assertEqual(second["value"], "[redacted]")
            self.assertNotEqual(first["value_sha256"], second["value_sha256"])


if __name__ == "__main__":
    unittest.main()
