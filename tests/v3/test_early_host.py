"""Smoke-test the minimum supported V3 release using its real public SDK and storage."""

import importlib
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
from app.sdk.events import Event
from app.schemas.types import EventType

try:
    from app.sdk.plugin import _PluginBase
    CHAIN_PATH = "app.sdk.plugin.base.PluginChain"
except ModuleNotFoundError:
    from app.plugins import _PluginBase
    CHAIN_PATH = "app.plugins.PluginChian"


class MinimumHostTests(unittest.TestCase):
    def test_three_plugins_load_persist_and_expose_typed_apis(self):
        with patch(CHAIN_PATH, return_value=Mock()):
            for name in ("TemoxSignin", "RedisAutoRestart", "HeyboxSignin"):
                with self.subTest(plugin=name):
                    module = importlib.import_module(f"app.plugins.{name.lower()}")
                    cls = getattr(module, name)
                    plugin = cls()
                    self.assertIsInstance(plugin, _PluginBase)
                    plugin.update_config({"enabled": True, "notify": False, "direct_check": False})
                    plugin.init_plugin(plugin.get_config())
                    self.assertTrue(plugin.get_state())
                    self.assertIsInstance(plugin.get_form()[0], list)
                    self.assertEqual(str(plugin.get_service()[0]["trigger"].timezone), settings.TZ)
                    plugin.save_data("minimum_host_test", {"plugin": name})
                    self.assertEqual(plugin.get_data("minimum_host_test"), {"plugin": name})
                    api = plugin.get_api()[0]
                    payload = api["endpoint"]()
                    self.assertIsInstance(payload, api["response_model"])
                    self.assertFalse(payload.success)
                    action = "check" if name == "RedisAutoRestart" else "signin"
                    remote = getattr(plugin, "remote_check" if action == "check" else "remote_signin")
                    with patch.object(plugin, action) as execute:
                        remote(Event(EventType.PluginAction, plugin.get_command()[0]["data"]))
                        execute.assert_called_once_with(manual=True)
                        plugin.init_plugin({"onlyonce": True, "notify": False})
                        self.assertFalse(plugin.get_config()["onlyonce"])
                        self.assertEqual(execute.call_count, 2)
                    plugin.stop_service()
                    self.assertFalse(plugin.get_state())
                    plugin.stop_service()


if __name__ == "__main__":
    unittest.main()
