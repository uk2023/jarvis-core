import os
import tempfile
import unittest
from unittest.mock import patch

from core.orchestration.llm_bridge import HybridLLMBridge
from core.runtime.runtime_monitor import RuntimeMonitor


class RuntimeSafetyTests(unittest.TestCase):
    def test_local_fallback_is_disabled_by_default(self):
        bridge = HybridLLMBridge(force_mode="online")
        with patch.object(bridge, "_is_online", return_value=True), \
             patch.object(bridge, "_get_groq", side_effect=RuntimeError("simulated groq failure")), \
             patch.object(bridge, "_get_local", side_effect=AssertionError("local model must not load")), \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=False):
            result = bridge.generate_response("system", "hello", max_tokens=32)
        self.assertIn("local fallback is disabled", result)
        self.assertEqual(bridge.last_backend, "groq_error")

    def test_local_fallback_requires_explicit_opt_in(self):
        bridge = HybridLLMBridge(force_mode="online")
        with patch.object(bridge, "_is_online", return_value=True), \
             patch.object(bridge, "_get_groq", side_effect=RuntimeError("simulated groq failure")), \
             patch.object(bridge, "_get_local") as local_factory, \
             patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "JARVIS_ALLOW_LOCAL_FALLBACK": "true", "JARVIS_ENABLE_HEAVY_LOCAL_MODEL": "true"}, clear=False):
            local_factory.return_value.generate.return_value = "local response"
            result = bridge.generate_response("system", "hello", max_tokens=32)
        self.assertEqual(result, "local response")
        self.assertEqual(bridge.last_backend, "local")

    def test_runtime_monitor_writes_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = RuntimeMonitor(os.path.join(directory, "health.json"))
            snapshot = monitor.write_snapshot(organs={})
            self.assertEqual(snapshot["version"], "1.0")
            loaded = monitor.read_snapshot()
            self.assertEqual(loaded["pid"], snapshot["pid"])
            self.assertIn("process", loaded)


if __name__ == "__main__":
    unittest.main()
