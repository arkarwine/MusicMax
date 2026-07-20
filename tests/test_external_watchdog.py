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

    def run_check(self, health, *, now=1_000, status="online"):
        watchdog.write_runtime_health(self.db_path, health)
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["pm2", "jlist"]:
                return self.pm2_result(now=now, status=status)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch.dict(watchdog.os.environ, self.env(), clear=False), \
             patch.object(watchdog.time, "time", return_value=now), \
             patch.object(watchdog.subprocess, "run", side_effect=fake_run):
            watchdog.check_once()
        return calls

    def test_fresh_health_does_not_restart(self):
        calls = self.run_check({
            "heartbeat_at": 950,
            "last_update_at": 900,
            "last_update_kind": "Message",
        })
        self.assertEqual(calls, [["pm2", "jlist"]])

    def test_stale_heartbeat_restarts_pm2_app(self):
        calls = self.run_check({
            "heartbeat_at": 700,
            "last_update_at": 990,
            "last_update_kind": "Message",
        })
        self.assertEqual(calls[-1], ["pm2", "restart", "GPH", "--update-env"])
        values = watchdog.read_runtime_health(self.db_path)
        self.assertIn("heartbeat stale", values["watchdog_last_reason"])

    def test_stale_update_restarts_after_real_update(self):
        calls = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 50,
            "last_update_kind": "CallbackQuery",
        })
        self.assertEqual(calls[-1], ["pm2", "restart", "GPH", "--update-env"])
        values = watchdog.read_runtime_health(self.db_path)
        self.assertIn("Telegram updates stale", values["watchdog_last_reason"])

    def test_startup_update_marker_does_not_restart_on_quiet_bot(self):
        calls = self.run_check({
            "heartbeat_at": 990,
            "last_update_at": 50,
            "last_update_kind": "startup",
        })
        self.assertEqual(calls, [["pm2", "jlist"]])

    def test_restart_cooldown_prevents_loop(self):
        calls = self.run_check({
            "heartbeat_at": 700,
            "last_update_at": 50,
            "last_update_kind": "Message",
            "watchdog_last_restart_at": 950,
        })
        self.assertEqual(calls, [["pm2", "jlist"]])

    def test_missing_database_does_not_restart(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            return self.pm2_result()

        with patch.dict(watchdog.os.environ, self.env(), clear=False), \
             patch.object(watchdog.time, "time", return_value=1_000), \
             patch.object(watchdog.subprocess, "run", side_effect=fake_run):
            watchdog.check_once()
        self.assertEqual(calls, [["pm2", "jlist"]])


if __name__ == "__main__":
    unittest.main()
