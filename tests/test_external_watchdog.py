import importlib.util
import sqlite3
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
            "EXTERNAL_WATCHDOG": "true",
            "WATCHDOG_APP_NAME": "GPH",
            "WATCHDOG_HEARTBEAT_STALE_SECONDS": "180",
            "WATCHDOG_UPDATE_STALE_SECONDS": "900",
            "WATCHDOG_MIN_UPTIME_SECONDS": "0",
            "WATCHDOG_RESTART_COOLDOWN_SECONDS": "600",
            "DATABASE_PATH": str(self.db_path),
        }

    def run_check(self, health, *, now=1_000, env=None, bot_api=(True, "ok")):
        health = {
            "telegram_probe_at": now - 20,
            "telegram_probe_status": "ok",
            "telegram_probe_detail": "Connected",
            "telegram_probe_failures": "0",
            **health,
        }
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
             patch.object(watchdog, "bot_api_get_me", return_value=bot_api), \
             patch.object(watchdog, "terminate_bot_processes", side_effect=fake_terminate):
            watchdog.check_once()
        return terminations

    def test_fresh_health_does_not_restart(self):
        terminations = self.run_check({
            "heartbeat_at": 950,
            "last_update_at": 900,
            "last_update_kind": "Message",
        })
        self.assertEqual(terminations, [])

    def test_stale_heartbeat_terminates_bot_process(self):
        terminations = self.run_check({
            "heartbeat_at": 700,
            "last_update_at": 990,
            "last_update_kind": "Message",
        })
        self.assertEqual(len(terminations), 1)
        self.assertIn("heartbeat stale", terminations[0])
        values = watchdog.read_runtime_health(self.db_path)
        self.assertIn("heartbeat stale", values["watchdog_last_reason"])

    def test_stale_update_restarts_after_real_update(self):
        terminations = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 50,
            "last_update_kind": "CallbackQuery",
        })
        self.assertEqual(len(terminations), 1)
        self.assertIn("Telegram updates stale", terminations[0])
        values = watchdog.read_runtime_health(self.db_path)
        self.assertIn("Telegram updates stale", values["watchdog_last_reason"])

    def test_startup_update_marker_does_not_restart_on_quiet_bot(self):
        terminations = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 50,
            "last_update_kind": "startup",
        })
        self.assertEqual(terminations, [])

    def test_restart_cooldown_prevents_loop(self):
        terminations = self.run_check({
            "heartbeat_at": 700,
            "last_update_at": 50,
            "last_update_kind": "Message",
            "watchdog_last_restart_at": 950,
        })
        self.assertEqual(terminations, [])

    def test_missing_database_does_not_restart(self):
        terminations = []

        def fake_terminate(reason):
            terminations.append(reason)
            return True

        with patch.dict(watchdog.os.environ, self.env(), clear=False), \
             patch.object(watchdog.time, "time", return_value=1_000), \
             patch.object(watchdog, "bot_api_get_me", return_value=(True, "ok")), \
             patch.object(watchdog, "terminate_bot_processes", side_effect=fake_terminate):
            watchdog.check_once()
        self.assertEqual(terminations, [])

    def test_check_logging_is_periodic_by_default(self):
        watchdog._last_check_log_at = 0
        watchdog._last_check_state = ""
        messages = []
        health = {
            "heartbeat_at": 990,
            "last_update_at": 900,
            "last_update_kind": "Message",
        }
        watchdog.write_runtime_health(self.db_path, health)
        env = self.env()
        env["WATCHDOG_LOG_INTERVAL_SECONDS"] = "300"

        with patch.dict(watchdog.os.environ, env, clear=False), \
             patch.object(watchdog, "bot_api_get_me", return_value=(True, "ok")), \
             patch.object(watchdog, "log", side_effect=messages.append):
            with patch.object(watchdog.time, "time", return_value=1_000):
                watchdog.check_once()
            watchdog.write_runtime_health(self.db_path, {
                "heartbeat_at": 1090,
                "last_update_at": 1000,
                "last_update_kind": "Message",
            })
            with patch.object(watchdog.time, "time", return_value=1_100):
                watchdog.check_once()
            watchdog.write_runtime_health(self.db_path, {
                "heartbeat_at": 1291,
                "last_update_at": 1201,
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
        health = {
            "heartbeat_at": 990,
            "last_update_at": 900,
            "last_update_kind": "Message",
        }
        watchdog.write_runtime_health(self.db_path, health)
        env = self.env()
        env["WATCHDOG_LOG_CHECKS"] = "true"

        with patch.dict(watchdog.os.environ, env, clear=False), \
             patch.object(watchdog, "bot_api_get_me", return_value=(True, "ok")), \
             patch.object(watchdog, "log", side_effect=messages.append):
            with patch.object(watchdog.time, "time", return_value=1_000):
                watchdog.check_once()
            with patch.object(watchdog.time, "time", return_value=1_010):
                watchdog.check_once()

        self.assertEqual(len(messages), 2)
        self.assertTrue(all("state=healthy" in message for message in messages))

    def test_failed_internal_telegram_probe_restarts(self):
        terminations = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 990,
            "last_update_kind": "Message",
            "telegram_probe_at": 980,
            "telegram_probe_status": "failed",
            "telegram_probe_detail": "TimeoutError",
            "telegram_probe_failures": "3",
        })
        self.assertEqual(len(terminations), 1)
        self.assertIn("internal Telegram probe failed", terminations[0])

    def test_stale_internal_telegram_probe_restarts(self):
        terminations = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 990,
            "last_update_kind": "Message",
            "telegram_probe_at": 700,
            "telegram_probe_status": "ok",
            "telegram_probe_detail": "Connected",
            "telegram_probe_failures": "0",
        })
        self.assertEqual(len(terminations), 1)
        self.assertIn("internal Telegram probe stale", terminations[0])

    def test_repeated_external_bot_api_failures_restart(self):
        watchdog._bot_api_failures = 2
        terminations = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 990,
            "last_update_kind": "Message",
        }, bot_api=(False, "TimeoutError"))
        self.assertEqual(len(terminations), 1)
        self.assertIn("external Bot API probe failed", terminations[0])
        values = watchdog.read_runtime_health(self.db_path)
        self.assertEqual(values["external_bot_api_probe_status"], "failed")


if __name__ == "__main__":
    unittest.main()