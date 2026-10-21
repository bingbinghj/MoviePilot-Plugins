"""Load real V3 SDK and isolated database; replace external accounts and process exits."""

import importlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, os.environ.get("MOVIEPILOT_BACKEND", "/app"))
from app.testing.bootstrap import prepare_v3_backend
prepare_v3_backend(REPO)
from app.sdk.config import settings
from app.sdk.events import Event, eventmanager
from app.sdk.plugin import _PluginBase
from app.schemas.types import EventType

NAMES = ["TemoxSignin", "RedisAutoRestart", "HeyboxSignin"]
MODULES = {name: importlib.import_module(f"app.plugins.{name.lower()}") for name in NAMES}
CLASSES = {name: getattr(module, name) for name, module in MODULES.items()}
ACTIONS = {name: "check" if name == "RedisAutoRestart" else "signin" for name in NAMES}
CHAIN_PATCH = patch("app.sdk.plugin.base.PluginChain", return_value=Mock())


def setUpModule():
    CHAIN_PATCH.start()


def tearDownModule():
    CHAIN_PATCH.stop()


class HostContracts(unittest.TestCase):
    def test_market_and_retired_plugins(self):
        from app.adapters.external.plugin.client import PluginMarketTransport
        with patch("app.adapters.external.plugin.client.get_runtime_setting", return_value="v3"):
            for filename, tree, generation in [("package.json", "plugins", ""),
                                               ("package.v2.json", "plugins.v2", "v2"),
                                               ("package.v3.json", "plugins.v3", "v3")]:
                manifest = json.loads((REPO / filename).read_text(encoding="utf-8"))
                self.assertEqual(set(manifest), set(NAMES))
                for retired in ("newapicheckin", "etkscrapewebhook"):
                    self.assertFalse((REPO / tree / retired).exists())
                for name, entry in manifest.items():
                    self.assertEqual(PluginMarketTransport.is_package_plugin_compatible(entry, generation),
                                     generation == "v3")
                    if generation == "v3":
                        self.assertTrue(issubclass(CLASSES[name], _PluginBase))
                        self.assertEqual(entry["version"], CLASSES[name].plugin_version)
                        self.assertEqual(entry["system_version"], ">=3.0.0")
                        self.assertEqual(next(iter(entry["history"])), f"v{entry['version']}")

    def test_persistence_forms_and_stop(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                form, defaults = plugin.get_form()
                plugin.update_config({**defaults, "enabled": True, "notify": False})
                plugin.save_data("v3_test", {"name": name})
                reloaded = CLASSES[name]()
                reloaded.init_plugin(reloaded.get_config())
                self.assertTrue(reloaded.get_state())
                self.assertIsInstance(form, list)
                self.assertIsInstance(reloaded.get_page(), list)
                self.assertEqual(reloaded.get_data("v3_test"), {"name": name})
                reloaded.stop_service()
                reloaded.stop_service()
                self.assertFalse(reloaded.get_state())

    def test_cron_timezone_and_repeat_initialization(self):
        for name in NAMES:
            with self.subTest(plugin=name), patch.object(settings, "TZ", "Europe/London"):
                plugin = CLASSES[name]()
                plugin.init_plugin({"enabled": True, "notify": False, "cron": "1 2 * * *"})
                service = plugin.get_service()[0]
                self.assertEqual(str(service["trigger"].timezone), "Europe/London")
                self.assertTrue(callable(service["func"]))
                plugin.init_plugin({"enabled": True, "notify": False})
                self.assertEqual(plugin._cron, plugin.get_form()[1]["cron"])
                plugin.init_plugin({"enabled": True, "notify": False, "cron": "invalid"})
                self.assertEqual(plugin.get_service(), [])
                plugin.stop_service()
                self.assertEqual(plugin.get_service(), [])

    def test_command_dispatch_and_late_events(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                plugin.init_plugin({"notify": False})
                remote = getattr(plugin, "remote_check" if name == "RedisAutoRestart" else "remote_signin")
                data = plugin.get_command()[0]["data"]
                with patch.object(plugin, ACTIONS[name]) as execute:
                    remote(Event(EventType.PluginAction, data))
                    execute.assert_called_once_with(manual=True)
                    remote(Event(EventType.PluginAction, {"action": "unrelated"}))
                    plugin.stop_service()
                    remote(Event(EventType.PluginAction, data))
                    self.assertEqual(execute.call_count, 1)

    def test_run_once_reset_before_failure_on_early_hosts(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                with patch.object(MODULES[name].scheduler_sdk, "add_plugin_once_job", None), \
                     patch.object(plugin, ACTIONS[name], side_effect=RuntimeError("test failure")) as execute:
                    with self.assertRaisesRegex(RuntimeError, "test failure"):
                        plugin.init_plugin({"onlyonce": True, "notify": False})
                    execute.assert_called_once_with(manual=True)
                self.assertFalse(plugin.get_config()["onlyonce"])

    def test_queued_run_once_cancelled_on_stop_and_reinit(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                plugin = CLASSES[name]()
                with patch.object(MODULES[name].scheduler_sdk, "add_plugin_once_job", return_value=True) as add, \
                     patch.object(MODULES[name].scheduler_sdk, "remove_plugin_once_job") as remove, \
                     patch.object(plugin, ACTIONS[name]) as execute:
                    plugin.init_plugin({"enabled": True, "onlyonce": True, "notify": False})
                    execute.assert_not_called()
                    self.assertFalse(plugin.get_config()["onlyonce"])
                    self.assertEqual(add.call_args.args[:2], (name, "run_once"))
                    callback = add.call_args.args[2]
                    callback()
                    execute.assert_called_once_with(manual=True)
                    plugin.stop_service()
                    callback()
                    self.assertEqual(execute.call_count, 1)
                    remove.assert_any_call(name, "run_once")
                    plugin.init_plugin({"notify": False})
                    self.assertFalse(plugin.get_state())

    def test_real_dynamic_api_registration_response_and_reload(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.adapters.web.plugin.routes import FastAPIDynamicRouteRegistry
        instances = {name: CLASSES[name]() for name in NAMES}
        for plugin in instances.values():
            plugin.init_plugin({"notify": False, "direct_check": False})

        def apis(name):
            return [{**api, "path": f"/{name}{api['path']}"} for api in instances[name].get_api()]

        app, log = FastAPI(), Mock()
        registry = FastAPIDynamicRouteRegistry(
            app, lambda: NAMES, apis, lambda: None, lambda: None, "/api/v1/plugin", log)
        registry.update(None, "add")
        registry.update(None, "add")
        log.error.assert_not_called()
        with TestClient(app) as client:
            for name in NAMES:
                api = instances[name].get_api()[0]
                url = f"/api/v1/plugin/{name}{api['path']}"
                response = client.post(url)
                self.assertEqual(response.status_code, 200, response.text)
                result = api["response_model"].model_validate(response.json())
                self.assertFalse(result.success)
                self.assertNotIn("data", response.json())
                schema = app.openapi()["paths"][url]["post"]["responses"]["200"]
                self.assertIn("$ref", schema["content"]["application/json"]["schema"])
                self.assertEqual(sum(getattr(route, "path", None) == url for route in app.routes), 1)
        for name in NAMES:
            registry.update(name, "remove")
            instances[name].stop_service()

    def test_event_registration_unique_after_module_reload(self):
        for name in NAMES:
            importlib.reload(MODULES[name])
            rows = [row for row in eventmanager.visualize_handlers() if f".{name.lower()}." in str(row)]
            self.assertEqual(len(rows), 1, rows)


class RedisAndResources(unittest.TestCase):
    def test_redis_backend_and_manual_override(self):
        plugin = CLASSES["RedisAutoRestart"]()
        with patch.object(settings, "CACHE_BACKEND_TYPE", "redis"), \
             patch.object(settings, "CACHE_BACKEND_URL", "rediss://cache.example:6380/2"):
            self.assertEqual(plugin._RedisAutoRestart__settings_redis_url(), "rediss://cache.example:6380/2")
        with patch.object(settings, "CACHE_BACKEND_TYPE", "cachetools"), patch("redis.Redis.from_url") as connect:
            self.assertFalse(plugin._RedisAutoRestart__check_redis()["failed"])
            connect.assert_not_called()
            plugin._redis_url = "redis://manual.example/1"
            plugin._RedisAutoRestart__check_redis()
            self.assertEqual(connect.call_args.args[0], plugin._redis_url)

    def test_redis_client_closed_on_success_and_failure(self):
        plugin = CLASSES["RedisAutoRestart"]()
        plugin._redis_url = "redis://test.invalid/0"
        for fail in (False, True):
            with self.subTest(fail=fail), patch("redis.Redis.from_url") as connect:
                client = connect.return_value
                client.ping.side_effect = RuntimeError("ping failed") if fail else None
                client.ping.return_value = True
                self.assertEqual(plugin._RedisAutoRestart__check_redis()["failed"], fail)
                client.close.assert_called_once()

    def test_notify_and_missing_command_do_not_claim_restart(self):
        for mode in ("notify", "command"):
            plugin = CLASSES["RedisAutoRestart"]()
            plugin.init_plugin({"enabled": True, "notify": False, "restart_mode": mode, "failure_threshold": 1})
            plugin.del_data("runtime_state")
            with patch.object(plugin, "_RedisAutoRestart__check_redis",
                              return_value={"failed": True, "message": "test failure"}):
                self.assertFalse(plugin.check()["restart_triggered"])
            self.assertNotIn("last_restart_at", plugin.get_data("runtime_state"))
            plugin.stop_service()

    def test_pending_exit_cancelled_on_both_modern_and_early_hosts(self):
        plugin = CLASSES["RedisAutoRestart"]()
        module = MODULES["RedisAutoRestart"]
        plugin.init_plugin({"enabled": True, "notify": False, "restart_delay": 30})
        with patch.object(module.scheduler_sdk, "add_plugin_once_job", return_value=True) as add, \
             patch.object(module.scheduler_sdk, "remove_plugin_once_job") as remove, \
             patch.object(module.os, "_exit") as exit_process:
            self.assertTrue(plugin._RedisAutoRestart__trigger_restart("test")[0])
            callback = add.call_args.args[2]
            self.assertEqual(add.call_args.args[:2], ("RedisAutoRestart", "restart_exit"))
            plugin.stop_service()
            callback()
            exit_process.assert_not_called()
            remove.assert_any_call("RedisAutoRestart", "restart_exit")
        plugin.init_plugin({"enabled": True, "notify": False, "restart_delay": 30})
        with patch.object(module.scheduler_sdk, "add_plugin_once_job", None), \
             patch.object(module.os, "_exit") as exit_process:
            plugin._RedisAutoRestart__trigger_restart("test")
            thread = plugin._restart_thread
            self.assertTrue(thread.is_alive())
            plugin.stop_service()
            self.assertFalse(thread.is_alive())
            exit_process.assert_not_called()

    def test_temox_session_closed_on_success_and_failure(self):
        plugin = CLASSES["TemoxSignin"]()
        plugin.init_plugin({"username": "test", "password": "test", "notify": False})
        for fail in (False, True):
            with patch.object(MODULES["TemoxSignin"].requests, "Session") as session, \
                 patch.object(plugin, "_TemoxSignin__get_with_gate") as get, \
                 patch.object(plugin, "_TemoxSignin__response_text", return_value="welcome"), \
                 patch.object(plugin, "_TemoxSignin__extract_login_form", return_value=None), \
                 patch.object(plugin, "_TemoxSignin__is_logged_in", return_value=True):
                get.side_effect = RuntimeError("test error") if fail else None
                self.assertEqual(plugin.signin()["success"], not fail)
                session.return_value.close.assert_called_once()

    def test_heybox_session_closed_on_success_and_failure(self):
        plugin = CLASSES["HeyboxSignin"]()
        plugin.init_plugin({"account_1_cookie": "test", "notify": False})
        item = {"success": True, "name": "test", "heybox_id": "12345", "message": "done", "detail": ""}
        for fail in (False, True):
            with patch.object(MODULES["HeyboxSignin"], "HeyboxAccount"), \
                 patch.object(MODULES["HeyboxSignin"], "HeyboxClient") as client, \
                 patch.object(plugin, "_HeyboxSignin__run_account", return_value=item) as run:
                run.side_effect = RuntimeError("test error") if fail else None
                self.assertEqual(plugin.signin()["success"], not fail)
                client.return_value.session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
