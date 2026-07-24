import asyncio
import importlib.util
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


supervisor_module = load_module(
    "supervisor_under_test", ROOT / "anony/core/supervisor.py"
)
health_module = load_module("health_under_test", ROOT / "anony/core/health.py")


class RuntimeSupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_recurring_worker_is_restarted_and_failure_is_observable(self):
        logger = logging.getLogger("test-supervisor-restart")
        supervisor = supervisor_module.RuntimeSupervisor(
            logger, backoff=(0, 0, 0), stable_after=60
        )
        attempts = 0
        running = asyncio.Event()

        async def worker():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("planned failure")
            running.set()
            await asyncio.Event().wait()

        supervisor.spawn("worker", worker, restart=True)
        await asyncio.wait_for(running.wait(), timeout=1)
        snapshot = supervisor.snapshot()
        self.assertEqual(attempts, 3)
        self.assertEqual(snapshot["workers"]["worker"]["failures"], 2)
        self.assertEqual(snapshot["workers"]["worker"]["restarts"], 2)
        await supervisor.close()
        self.assertEqual(supervisor.workers["worker"].state, "stopped")

    async def test_one_time_failure_is_retrieved_and_not_restarted(self):
        logger = logging.getLogger("test-supervisor-once")
        supervisor = supervisor_module.RuntimeSupervisor(logger, backoff=(0,))

        async def fail():
            raise ValueError("visible")

        task = supervisor.spawn_once("once", fail())
        await task
        await asyncio.sleep(0)
        state = supervisor.workers["once"]
        self.assertEqual(state.failures, 1)
        self.assertEqual(state.restarts, 0)
        self.assertIn("ValueError", state.last_error)
        await supervisor.close()

    async def test_cancelled_worker_is_never_restarted(self):
        supervisor = supervisor_module.RuntimeSupervisor(
            logging.getLogger("test-supervisor-cancel"), backoff=(0,)
        )
        started = asyncio.Event()

        async def worker():
            started.set()
            await asyncio.Event().wait()

        supervisor.spawn("worker", worker)
        await started.wait()
        await supervisor.close()
        self.assertEqual(supervisor.workers["worker"].restarts, 0)


class HealthTransitionTests(unittest.IsolatedAsyncioTestCase):
    def make_monitor(self):
        app = types.SimpleNamespace(sudoers={1}, is_connected=True)
        db = types.SimpleNamespace()
        userbot = types.SimpleNamespace(clients={})
        calls = types.SimpleNamespace(clients={})
        language = types.SimpleNamespace(languages={"en": {}})
        supervisor = types.SimpleNamespace(
            snapshot=lambda: {"healthy": True, "running": 1, "failed": [], "workers": {}},
        )
        return health_module.HealthMonitor(
            app=app,
            db=db,
            userbot=userbot,
            calls=calls,
            language=language,
            supervisor=supervisor,
            logger=logging.getLogger("test-health"),
        )

    async def test_failure_and_recovery_thresholds_emit_once(self):
        monitor = self.make_monitor()
        monitor._alert = AsyncMock()
        for _ in range(2):
            await monitor._record("database", False, "offline")
        self.assertEqual(monitor.components["database"].status, "unknown")
        monitor._alert.assert_not_awaited()

        await monitor._record("database", False, "offline")
        self.assertEqual(monitor.components["database"].status, "unhealthy")
        self.assertEqual(monitor._alert.await_count, 1)

        await monitor._record("database", True, "Connected")
        self.assertEqual(monitor.components["database"].status, "unhealthy")
        await monitor._record("database", True, "Connected")
        self.assertEqual(monitor.components["database"].status, "healthy")
        self.assertEqual(monitor._alert.await_count, 2)

    async def test_initial_success_does_not_send_recovery_alert(self):
        monitor = self.make_monitor()
        monitor._alert = AsyncMock()
        await monitor._record("Telegram", True, "Connected")
        self.assertEqual(monitor.components["Telegram"].status, "healthy")
        monitor._alert.assert_not_awaited()

    async def test_watchdog_exits_when_update_activity_is_stale(self):
        monitor = self.make_monitor()
        monitor.watchdog_restart = True
        monitor.watchdog_stall_seconds = 300
        monitor.last_update_at = int(health_module.time()) - 301
        monitor.finish = AsyncMock()
        with patch.object(health_module.logging, "shutdown") as shutdown, \
             patch.object(
                 health_module.os,
                 "_exit",
                 side_effect=RuntimeError("exit requested"),
             ) as exit_call:
            with self.assertRaises(RuntimeError):
                await monitor._watchdog_stale_updates()
        monitor.finish.assert_awaited_once()
        self.assertIn("watchdog:", monitor.finish.await_args.args[0])
        shutdown.assert_called_once()
        exit_call.assert_called_once_with(75)


class HealthAlertDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def make_monitor(self, *, connected=True):
        english = {
            "health_alert_restart": "Restart: {0}",
            "health_alert_failed": "{0} {1} {2} {3}",
            "health_alert_recovered": "{0} {1} {2} {3}",
        }
        app = types.SimpleNamespace(
            sudoers={1},
            is_connected=connected,
            send_message=AsyncMock(),
        )
        db = types.SimpleNamespace(
            get_health_alert_subscribers=AsyncMock(return_value=[1, 2])
        )
        language = types.SimpleNamespace(
            languages={"en": english},
            get_lang=AsyncMock(return_value=english),
        )
        supervisor = types.SimpleNamespace(
            snapshot=lambda: {
                "healthy": True,
                "running": 1,
                "failed": [],
                "workers": {},
            },
        )
        monitor = health_module.HealthMonitor(
            app=app,
            db=db,
            userbot=types.SimpleNamespace(clients={}),
            calls=types.SimpleNamespace(clients={}),
            language=language,
            supervisor=supervisor,
            logger=logging.getLogger("test-health-delivery"),
        )
        return monitor

    async def test_alert_goes_only_to_current_opted_in_sudo(self):
        monitor = self.make_monitor()
        await monitor._deliver("health_alert_restart", "details")
        monitor.app.send_message.assert_awaited_once()
        self.assertEqual(monitor.app.send_message.await_args.args[0], 1)

    async def test_delivery_failure_does_not_escape_monitor(self):
        monitor = self.make_monitor()
        monitor.app.send_message.side_effect = RuntimeError("DM blocked")
        await monitor._deliver("health_alert_restart", "details")

    async def test_alert_is_queued_while_telegram_is_disconnected(self):
        monitor = self.make_monitor(connected=False)
        await monitor._deliver("health_alert_restart", "details")
        self.assertEqual(
            monitor._pending_alerts,
            [("health_alert_restart", ("details",))],
        )
        monitor.app.send_message.assert_not_awaited()


class ReliabilityDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        fake_anony = types.ModuleType("anony")
        fake_anony.config = types.SimpleNamespace(
            DATABASE_PATH=str(Path(self.temp.name) / "test.db")
        )
        fake_anony.logger = logging.getLogger("test-reliability-db")
        fake_anony.userbot = types.SimpleNamespace(clients={})
        fake_core = types.ModuleType("anony.core")
        fake_core.__path__ = []
        self.previous_modules = {
            key: sys.modules.get(key)
            for key in ("anony", "anony.core")
        }
        sys.modules.update({
            "anony": fake_anony,
            "anony.core": fake_core,
        })
        module = load_module(
            "database_reliability_under_test", ROOT / "anony/core/database.py"
        )
        self.db = module.SQLiteDB()
        await self.db.connect()

    async def asyncTearDown(self):
        await self.db.close()
        self.temp.cleanup()
        for key, value in self.previous_modules.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value

    async def test_runtime_health_values_persist(self):
        await self.db.set_runtime_health_values({
            "heartbeat_at": 123,
            "last_update_kind": "Message",
        })
        values = await self.db.get_runtime_health()
        self.assertEqual(values["heartbeat_at"]["value"], "123")
        self.assertEqual(values["last_update_kind"]["value"], "Message")
        self.assertIsInstance(values["heartbeat_at"]["updated_at"], int)

    async def test_process_run_detects_unfinished_previous_run(self):
        self.assertIsNone(await self.db.start_process_run("first"))
        await self.db.heartbeat_process_run("first")
        previous = await self.db.start_process_run("second")
        self.assertEqual(previous["run_id"], "first")
        self.assertIsNone(previous["stopped_at"])
        await self.db.finish_process_run("second", "signal:SIGTERM")

    async def test_alert_subscription_defaults_off_and_persists(self):
        self.assertFalse(await self.db.health_alerts_enabled(42))
        await self.db.set_health_alerts(42, True)
        self.assertTrue(await self.db.health_alerts_enabled(42))
        self.assertEqual(await self.db.get_health_alert_subscribers(), [42])
        await self.db.set_health_alerts(42, False)
        self.assertFalse(await self.db.health_alerts_enabled(42))
