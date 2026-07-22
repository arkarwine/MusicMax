import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "watchdog_under_test", ROOT / "scripts/watchdog.py"
)
watchdog = importlib.util.module_from_spec(SPEC)
sys.modules["watchdog_under_test"] = watchdog
SPEC.loader.exec_module(watchdog)


class ExternalWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "health.db"

    def tearDown(self):
        self.temp.cleanup()

    def env(self):
        return {
            "WATCHDOG_ENABLED": "true",
            "WATCHDOG_MODE": "standard",
            "WATCHDOG_UPDATE_STALE_SECONDS": "180",
            "WATCHDOG_ASSISTANT_PROBE_STALE_SECONDS": "300",
            "WATCHDOG_MIN_UPTIME_SECONDS": "0",
            "WATCHDOG_RESTART_COOLDOWN_SECONDS": "300",
            "DATABASE_PATH": str(self.db_path),
        }

    def run_check(self, health, *, now=1_000, env=None):
        watchdog.write_runtime_health(self.db_path, health)
        terminations = []
        merged_env = self.env()
        if env:
            merged_env.update(env)

        def fake_terminate(reason):
            terminations.append(reason)
            return True

        with patch.dict(watchdog.os.environ, merged_env, clear=False), \
             patch.object(watchdog.time, "time", return_value=now), \
             patch.object(watchdog, "terminate_bot_processes", side_effect=fake_terminate):
            watchdog.check_once()
        return terminations

    def test_fresh_update_does_not_restart(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "950",
            "last_update_kind": "Message",
        })
        self.assertEqual(terminations, [])

    def test_startup_marker_does_not_restart(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "100",
            "last_update_kind": "startup",
        })
        self.assertEqual(terminations, [])

    def test_stale_update_restarts_without_reachable_assistant_probe(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "700",
            "last_update_kind": "Message",
            "assistant_probe_at": "600",
            "assistant_probe_status": "failed",
        })
        self.assertEqual(len(terminations), 1)
        self.assertIn("Telegram updates stale", terminations[0])
        values = watchdog.read_runtime_health(self.db_path)
        self.assertIn("Telegram updates stale", values["watchdog_last_reason"])

    def test_stale_update_is_allowed_when_assistant_probe_passes(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "700",
            "last_update_kind": "Message",
            "assistant_probe_at": "950",
            "assistant_probe_status": "ok",
        })
        self.assertEqual(terminations, [])

    def test_stale_update_waits_for_initial_assistant_probe_window(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "700",
            "last_update_kind": "Message",
            "assistant_probe_at": "950",
            "assistant_probe_status": "startup",
        })
        self.assertEqual(terminations, [])

    def test_stale_update_restarts_when_assistant_probe_is_too_old(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "700",
            "last_update_kind": "Message",
            "assistant_probe_at": "650",
            "assistant_probe_status": "ok",
        })
        self.assertEqual(len(terminations), 1)
        self.assertIn("assistant probe ok/350s", terminations[0])

    def test_restart_cooldown_prevents_loop(self):
        terminations = self.run_check({
            "started_at": "900",
            "last_update_at": "700",
            "last_update_kind": "Message",
            "watchdog_last_restart_at": "950",
        })
        self.assertEqual(terminations, [])

    def test_missing_database_does_not_restart(self):
        terminations = []

        def fake_terminate(reason):
            terminations.append(reason)
            return True

        with patch.dict(watchdog.os.environ, self.env(), clear=False), \
             patch.object(watchdog.time, "time", return_value=1_000), \
             patch.object(watchdog, "terminate_bot_processes", side_effect=fake_terminate):
            watchdog.check_once()
        self.assertEqual(terminations, [])

    def test_check_logging_is_periodic_by_default(self):
        watchdog._last_check_log_at = 0
        watchdog._last_check_state = ""
        messages = []
        watchdog.write_runtime_health(self.db_path, {
            "started_at": "900",
            "last_update_at": "950",
            "last_update_kind": "Message",
        })
        env = self.env()
        env["WATCHDOG_LOG_INTERVAL_SECONDS"] = "300"

        with patch.dict(watchdog.os.environ, env, clear=False), \
             patch.object(watchdog, "log", side_effect=messages.append):
            with patch.object(watchdog.time, "time", return_value=1_000):
                watchdog.check_once()
            watchdog.write_runtime_health(self.db_path, {
                "started_at": "900",
                "last_update_at": "1050",
                "last_update_kind": "Message",
            })
            with patch.object(watchdog.time, "time", return_value=1_100):
                watchdog.check_once()
            watchdog.write_runtime_health(self.db_path, {
                "started_at": "900",
                "last_update_at": "1250",
                "last_update_kind": "Message",
            })
            with patch.object(watchdog.time, "time", return_value=1_301):
                watchdog.check_once()

        self.assertEqual(len(messages), 2)
        self.assertIn("state=healthy", messages[0])
        self.assertIn("state=healthy", messages[1])

    def test_check_logging_can_log_every_check(self):
        watchdog._last_check_log_at = 0
        watchdog._last_check_state = ""
        messages = []
        watchdog.write_runtime_health(self.db_path, {
            "started_at": "900",
            "last_update_at": "950",
            "last_update_kind": "Message",
        })
        env = self.env()
        env["WATCHDOG_LOG_CHECKS"] = "true"

        with patch.dict(watchdog.os.environ, env, clear=False), \
             patch.object(watchdog, "log", side_effect=messages.append):
            with patch.object(watchdog.time, "time", return_value=1_000):
                watchdog.check_once()
            with patch.object(watchdog.time, "time", return_value=1_010):
                watchdog.check_once()

        self.assertEqual(len(messages), 2)
        self.assertTrue(all("state=healthy" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
