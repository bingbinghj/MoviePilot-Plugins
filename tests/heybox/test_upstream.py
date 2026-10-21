"""Test upstream behavior in each host namespace, with no account requests or real posts."""

import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, quote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("MOVIEPILOT_BACKEND", "/app"))
from app.testing import bootstrap

GENERATION = os.environ.get("HEYBOX_TEST_GENERATION", "v3")
getattr(bootstrap, f"prepare_{GENERATION}_backend")(ROOT)
module = importlib.import_module("app.plugins.heyboxsignin")


def make_task(task_id="33", params=None):
    return {"taskId": task_id, "title": "test", "state": "waiting", "reportTaskType": "time_limit",
            "maxjia": "heybox://" + quote(json.dumps(params or {"params": {"topic_id": "123"}}))}


class UpstreamBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.plugin = object.__new__(module.HeyboxSignin)
        self.plugin.get_data = Mock(return_value={})
        self.plugin.update_config = Mock()
        self.plugin.save_data = Mock()
        self.plugin.init_plugin({"notify": False, "time_limit_tasks": True, "game_review_tasks": True,
                                 "post_title": "my title", "post_content": "my content",
                                 "review_content": "my review", "review_score": 3})
        self.addCleanup(self.plugin.stop_service)
        self.client = Mock()
        self.client.account = Mock(heybox_id="12345", web_cookie="pkey=test;x_pkey=test")

    def execute(self, task):
        return self.plugin._HeyboxSignin__execute_task(task, self.client)

    def test_web_signature_matches_upstream_node_vectors(self):
        expected = {"/bbs/app/api/link/post": "DPWZI89", "/bbs/app/link/delete": "DPWZI89",
                    "//task//list_v2/": "WSUZS93"}
        for path, hkey in expected.items():
            result = module.make_web_signature(path, "999.0.4", 1792581234,
                                               "0123456789ABCDEF0123456789ABCDEF12")
            self.assertEqual(result["hkey"], hkey)
            self.assertEqual(result["_time"], "1792581234")

    def test_maxjia_handles_both_topic_locations_and_invalid_inputs(self):
        for data in [{"params": {"topic_id": "123"}}, {"topic_id": "123"},
                     {"app_id": "456", "protocol_type": "openGameDetail"}]:
            for raw in [json.dumps(data), "heybox://" + json.dumps(data),
                        "heybox://" + quote(json.dumps(data))]:
                self.assertEqual(module.parse_maxjia(raw), data)
        for raw in [None, "broken", "heybox://%", "[]", "null"]:
            self.assertIsNone(module.parse_maxjia(raw))

    def test_award_mapping_and_maxjia_metadata(self):
        payload = {"result": {"task_list": [{"tasks": [{"title": "task", "maxjia": "heybox://test",
                   "report_extra": {"task_id": 33, "task_type": "time_limit"},
                   "award_desc_v2": [{"icon": "b9aca51c", "desc": "20"},
                                     {"icon": "c10d89ae", "desc": "30"},
                                     {"icon": "e63b192a", "desc": "1"}]}]}]}}
        task = self.plugin._HeyboxSignin__extract_task_list(payload)["tasks"][0]
        self.assertEqual(task["awardText"], "20经验 30H币 1盒电")
        self.assertEqual(task["maxjia"], "heybox://test")
        self.assertEqual(task["taskId"], "33")

    def test_existing_configs_leave_both_public_write_tasks_disabled(self):
        self.plugin.init_plugin({"enabled": True, "share_tasks": True, "notify": False})
        for task_id in ["33", "24"]:
            self.assertTrue(self.execute(make_task(task_id))["unsupported"])
        self.client.post_json.assert_not_called()
        self.client.get_json.assert_not_called()
        defaults = self.plugin.get_form()[1]
        self.assertFalse(defaults["time_limit_tasks"])
        self.assertFalse(defaults["game_review_tasks"])
        self.assertEqual(self.plugin._review_score, 5)

    def test_new_config_persists_when_run_once_resets(self):
        config = {"notify": False, "onlyonce": True, "time_limit_tasks": True, "game_review_tasks": True,
                  "post_title": "my title", "post_content": "my content", "review_content": "my review",
                  "review_score": 3}
        with patch.object(self.plugin, "_schedule_run_once"):
            self.plugin.init_plugin(config)
        saved = self.plugin.update_config.call_args.args[0]
        for key, value in config.items():
            self.assertEqual(saved[key], False if key == "onlyonce" else value)

    def test_time_limit_post_checks_state_and_deletes_only_its_new_id(self):
        for params in [{"params": {"topic_id": "123"}}, {"topic_id": "123"}]:
            task = make_task(params=params)
            self.client.post_json.reset_mock()
            self.client.post_json.side_effect = [{"status": "ok", "result": {"link_id": 987}}, {"status": "ok"}]
            snapshot = {"tasks": [{**task, "state": "finish"}]}
            with patch.object(module.time, "sleep"), \
                 patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot", return_value=snapshot):
                result = self.execute(task)
            self.assertTrue(result["ok"])
            create = self.client.post_json.call_args_list[0]
            self.assertEqual(create.args[0], module.PATH_BBS_POST)
            self.assertEqual(create.args[1]["topic_ids"], "123")
            self.assertEqual(create.args[1]["link_tag"], "27")
            self.assertEqual(create.args[1]["title"], "my title")
            self.assertEqual(json.loads(create.args[1]["text"])[0]["text"], "my content")
            self.assertEqual(self.client.post_json.call_args_list[1].args,
                             (module.PATH_BBS_DELETE, {"link_id": "987"}))

    def test_poll_failure_still_deletes_post(self):
        self.client.post_json.side_effect = [{"status": "ok", "result": {"link_id": "987"}}, {"status": "ok"}]
        with patch.object(module.time, "sleep"), \
             patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot", side_effect=RuntimeError("poll failed")):
            result = self.execute(make_task())
        self.assertFalse(result["ok"])
        self.assertIn("poll failed", result["message"])
        self.assertEqual(self.client.post_json.call_count, 2)

    def test_failed_cleanup_never_reports_complete_success(self):
        task = make_task()
        self.client.post_json.side_effect = [{"status": "ok", "result": {"link_id": "987"}},
                                            {"status": "fail", "msg": "delete failed"}]
        with patch.object(module.time, "sleep"), \
             patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot",
                          return_value={"tasks": [{**task, "state": "finish"}]}):
            result = self.execute(task)
        self.assertFalse(result["ok"])
        self.assertTrue(result["cleanup_failed"])
        self.assertIn("link_id=987", result["message"])

    def test_invalid_post_id_is_never_used_for_delete(self):
        for response in [{"status": "fail"}, {"status": "ok", "result": {"link_id": "invalid"}}]:
            self.client.post_json.reset_mock()
            self.client.post_json.side_effect = None
            self.client.post_json.return_value = response
            result = self.execute(make_task())
            self.assertFalse(result["ok"])
            self.assertEqual(self.client.post_json.call_count, 1)

    def test_game_review_uses_web_request_and_cleans_up_after_settlement(self):
        task = make_task("24", {"app_id": "456"})
        self.client.get_json.return_value = {"status": "ok", "result": {"links": [{"topics": [{"topic_id": 123}]}]}}
        self.client.post_json.return_value = {"status": "ok"}
        with patch.object(module, "HeyboxWebClient") as web, patch.object(module.time, "sleep"), \
             patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot",
                          side_effect=[{"tasks": [task]}, {"tasks": [{**task, "state": "finish"}]}]):
            web.return_value.post_json.return_value = {"status": "ok", "link_id": "765"}
            result = self.execute(task)
            self.assertTrue(result["ok"])
            body = web.return_value.post_json.call_args.args[1]
            self.assertEqual(body["appid"], "456")
            self.assertEqual(body["score"], "3")
            self.assertEqual(body["link_tag"], "3")
            self.assertEqual(body["desc"], "my review")
            web.return_value.session.close.assert_called_once()
        self.client.post_json.assert_called_once_with(module.PATH_BBS_DELETE, {"link_id": "765"})

    def test_game_review_timeout_does_not_claim_success_but_deletes_post(self):
        task = make_task("24", {"app_id": "456"})
        self.client.get_json.return_value = {"status": "ok", "result": {"links": [{"topics": [{"topic_id": 123}]}]}}
        self.client.post_json.return_value = {"status": "ok"}
        with patch.object(module, "HeyboxWebClient") as web, patch.object(module.time, "sleep"), \
             patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot", return_value={"tasks": [task]}) as poll:
            web.return_value.post_json.return_value = {"status": "ok", "link_id": "765"}
            result = self.execute(task)
            self.assertFalse(result["ok"])
            self.assertEqual(poll.call_count, 7)
            web.return_value.session.close.assert_called_once()
        self.client.post_json.assert_called_once_with(module.PATH_BBS_DELETE, {"link_id": "765"})

    def test_post_writes_are_not_retried_on_uncertain_response(self):
        client = module.HeyboxClient(self.client.account, 5, 3, 0)
        with patch.object(client, "request_hkey", return_value={"hkey": "hk", "time": "1"}), \
             patch.object(client.session, "request", side_effect=module.requests.Timeout("uncertain")) as request:
            with self.assertRaises(RuntimeError):
                client.post_json(module.PATH_BBS_POST, {"title": "test"})
            request.assert_called_once()
        client.session.close()

    def test_web_cookie_and_request_shape(self):
        cookie = "pkey=abc;x_xhh_tokenid=t;extra=keep"
        self.assertIn("x_pkey=abc", module.build_web_cookie(cookie, "12345"))
        self.assertIn("x_heybox_id=12345", module.build_web_cookie(cookie, "12345"))
        self.assertIn("x_pkey=existing", module.build_web_cookie(cookie + ";x_pkey=existing", "12345"))
        client = module.HeyboxWebClient(self.client.account, 5, 2, 0)
        with patch.object(client, "request_json", return_value={"status": "ok"}) as request:
            client.post_json(module.PATH_BBS_POST, {"appid": "456", "score": "3"})
            args, kwargs = request.call_args
            query = parse_qs(urlsplit(args[1]).query)
            self.assertEqual(query["os_type"], ["web"])
            self.assertEqual(query["heybox_id"], ["12345"])
            self.assertEqual(kwargs["headers"]["Cookie"], self.client.account.web_cookie)
            self.assertEqual(parse_qs(kwargs["data"])["appid"], ["456"])
            self.assertEqual(kwargs["retries"], 0)
        client.session.close()

    def test_task_list_errors_never_become_an_empty_success(self):
        for payload in [{"status": "fail", "msg": "login expired"}, {"status": "ok", "result": {}}]:
            self.client.get_json.return_value = payload
            with self.assertRaises(RuntimeError):
                self.plugin._HeyboxSignin__fetch_snapshot(self.client)

    def test_stopped_instance_does_not_publish_content(self):
        self.plugin.stop_service()
        result = self.execute(make_task())
        self.assertFalse(result["ok"])
        self.client.post_json.assert_not_called()

    def test_account_reports_failed_cleanup_even_when_server_task_finished(self):
        task = make_task()
        initial = {"tasks": [task], "coin": "10"}
        completed = {"tasks": [{**task, "state": "finish"}], "coin": "20"}
        self.client.post_json.side_effect = [{"status": "ok", "result": {"link_id": "987"}},
                                            {"status": "fail", "msg": "delete failed"}]
        with patch.object(module.time, "sleep"), \
             patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot",
                          side_effect=[initial, initial, completed, completed]):
            result = self.plugin._HeyboxSignin__run_account(Mock(name="test", heybox_id="12345"), self.client)
        self.assertFalse(result["success"])
        self.assertIn("link_id=987", result["detail"])

    def test_enabled_time_limit_task_is_included_in_final_pending_count(self):
        task = make_task()
        snapshot = {"tasks": [task], "coin": "10"}
        with patch.object(self.plugin, "_HeyboxSignin__fetch_snapshot", return_value=snapshot), \
             patch.object(self.plugin, "_HeyboxSignin__execute_task", return_value={"ok": False, "message": "pending"}):
            result = self.plugin._HeyboxSignin__run_account(Mock(name="test", heybox_id="12345"), self.client)
        self.assertFalse(result["success"])
        self.assertIn("仍有待完成 1 个", result["message"])


if __name__ == "__main__":
    unittest.main()
