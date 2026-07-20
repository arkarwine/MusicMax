import importlib.util
import json
import sqlite3
import subprocess
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
            "WATCHDOG_PM2_APP": "GPH",
            "WATCHDOG_RESTART_METHOD": "kill",
            "WATCHDOG_HEARTBEAT_STALE_SECONDS": "180",
            "WATCHDOG_UPDATE_STALE_SECONDS": "900",
            "WATCHDOG_MIN_UPTIME_SECONDS": "0",
            "WATCHDOG_RESTART_COOLDOWN_SECONDS": "600",
            "DATABASE_PATH": str(self.db_path),
        }

    def pm2_result(self, now=1_000, status="online"):
        payload = [{
            "name": "GPH",
            "pm2_env": {
                "status": status,
                "pm_uptime": (now - 1_000) * 1_000,
            },
        }]
        return subprocess.CompletedProcess(
            ["pm2", "jlist"], 0, stdout=json.dumps(payload), stderr=""
        )

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
             patch.object(watchdog, "terminate_bot_processes", side_effect=fake_terminate):
            watchdog.check_once()
        self.assertEqual(terminations, [])

    def test_optional_pm2_restart_method_is_still_supported(self):
        watchdog.write_runtime_health(self.db_path, {
            "heartbeat_at": 700,
            "last_update_at": 990,
            "last_update_kind": "Message",
        })
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        env = self.env()
        env["WATCHDOG_RESTART_METHOD"] = "pm2"
        with patch.dict(watchdog.os.environ, env, clear=False), \
             patch.object(watchdog.time, "time", return_value=1_000), \
             patch.object(watchdog.subprocess, "run", side_effect=fake_run):
            watchdog.check_once()

        self.assertEqual(calls, [["pm2", "restart", "GPH", "--update-env"]])


if __name__ == "__main__":
    unittest.main()