"""Runtime health checks, process heartbeats, and opt-in sudo alerts."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic, time
from uuid import uuid4


@dataclass(slots=True)
class ComponentHealth:
    name: str
    status: str = "unknown"
    detail: str = "Not checked yet"
    failures: int = 0
    successes: int = 0
    changed_at: float = 0.0
    reminded_at: float = 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except ValueError:
        return default
    return max(value, minimum)


class HealthMonitor:
    CHECK_INTERVAL = 60
    HEARTBEAT_INTERVAL = 30
    FAILURE_THRESHOLD = 3
    RECOVERY_THRESHOLD = 2
    REMINDER_INTERVAL = 3600
    PROBE_TIMEOUT = 5

    def __init__(
        self,
        *,
        app,
        db,
        userbot,
        calls,
        language,
        supervisor,
        logger,
        watchdog_restart: bool = False,
        watchdog_stall_seconds: int = 21600,
    ) -> None:
        self.app = app
        self.db = db
        self.userbot = userbot
        self.calls = calls
        self.language = language
        self.supervisor = supervisor
        self.logger = logger
        self.run_id = uuid4().hex
        self.started_at = int(time())
        self.last_heartbeat = self.started_at
        self.last_update_at = self.started_at
        self.last_update_kind = "startup"
        self.last_handler_started_at = self.started_at
        self.last_handler_finished_at = self.started_at
        self.last_handler_failed_at = 0
        self.last_handler_name = "startup"
        self.active_handlers: dict[str, dict[str, object]] = {}
        self._handler_sequence = 0
        self.telegram_probe_at = self.started_at
        self.telegram_probe_status = "startup"
        self.telegram_probe_detail = "Not checked yet"
        self.assistant_probe_at = self.started_at
        self.assistant_probe_status = "startup"
        self.assistant_probe_detail = "Not checked yet"
        self.assistant_probe_failures = 0
        self._assistant_probe_last_sent = 0
        self.watchdog_restart = watchdog_restart
        self.watchdog_stall_seconds = max(int(watchdog_stall_seconds), 300)
        self.previous_run: dict | None = None
        self.components = {
            name: ComponentHealth(name)
            for name in (
                "event loop", "Telegram", "database", "assistants",
                "voice", "application",
            )
        }
        self._pending: dict[str, str] = {}
        self._pending_alerts: list[tuple[str, tuple]] = []
        self._recovery_attempted: dict[str, float] = {}
        self._last_tick = monotonic()

    async def begin_run(self) -> dict | None:
        self.previous_run = await self.db.start_process_run(self.run_id)
        await self.db.set_runtime_health_values({
            "run_id": self.run_id,
            "started_at": self.started_at,
            "heartbeat_at": self.last_heartbeat,
            "last_update_at": self.last_update_at,
            "last_update_kind": self.last_update_kind,
            "last_handler_started_at": self.last_handler_started_at,
            "last_handler_finished_at": self.last_handler_finished_at,
            "last_handler_failed_at": self.last_handler_failed_at,
            "last_handler_name": self.last_handler_name,
            "active_handler_count": self._active_handler_summary()[0],
            "oldest_active_handler_at": self._active_handler_summary()[1],
            "oldest_active_handler": self._active_handler_summary()[2],
            "telegram_probe_at": self.telegram_probe_at,
            "telegram_probe_status": self.telegram_probe_status,
            "telegram_probe_detail": self.telegram_probe_detail,
            "assistant_probe_at": self.assistant_probe_at,
            "assistant_probe_status": self.assistant_probe_status,
            "assistant_probe_detail": self.assistant_probe_detail,
            "assistant_probe_failures": self.assistant_probe_failures,
            "last_shutdown_reason": "running",
        })
        if self.previous_run and self.previous_run["stopped_at"] is None:
            heartbeat = datetime.fromtimestamp(
                self.previous_run["heartbeat_at"], timezone.utc
            ).strftime("%d %b %H:%M UTC")
            self.logger.warning(
                "Previous bot run ended unexpectedly; last heartbeat was %s", heartbeat
            )
            self._pending["previous run"] = (
                f"The previous bot run ended unexpectedly. Last heartbeat: {heartbeat}."
            )
        return self.previous_run

    def start(self) -> asyncio.Task:
        return self.supervisor.spawn("health-monitor", self.run, restart=True)

    def mark_update(self, update=None) -> None:
        self.last_update_at = int(time())
        self.last_update_kind = type(update).__name__ if update is not None else "update"

    def _active_handler_summary(self) -> tuple[int, int, str]:
        if not self.active_handlers:
            return 0, 0, ""
        oldest_token, oldest = min(
            self.active_handlers.items(),
            key=lambda item: int(item[1].get("started_at", 0)),
        )
        return (
            len(self.active_handlers),
            int(oldest.get("started_at", 0)),
            str(oldest.get("name") or oldest_token),
        )

    async def handler_started(self, update=None, name: str = "handler") -> str:
        now = int(time())
        self.mark_update(update)
        self._handler_sequence += 1
        token = f"{now}:{self._handler_sequence}:{name}"
        chat = getattr(update, "chat", None) or getattr(
            getattr(update, "message", None), "chat", None
        )
        user = getattr(update, "from_user", None) or getattr(
            getattr(update, "message", None), "from_user", None
        )
        self.active_handlers[token] = {
            "name": name,
            "started_at": now,
            "update": type(update).__name__ if update is not None else "update",
            "chat": getattr(chat, "id", ""),
            "user": getattr(user, "id", ""),
        }
        self.last_handler_started_at = now
        self.last_handler_name = name
        count, oldest_at, oldest_name = self._active_handler_summary()
        if hasattr(self.db, "set_runtime_health_values"):
            try:
                await self.db.set_runtime_health_values({
                    "last_update_at": self.last_update_at,
                    "last_update_kind": self.last_update_kind,
                    "last_handler_started_at": self.last_handler_started_at,
                    "last_handler_finished_at": self.last_handler_finished_at,
                    "last_handler_failed_at": self.last_handler_failed_at,
                    "last_handler_name": self.last_handler_name,
                    "active_handler_count": self._active_handler_summary()[0],
                    "oldest_active_handler_at": self._active_handler_summary()[1],
                    "oldest_active_handler": self._active_handler_summary()[2],
                    "last_handler_started_at": self.last_handler_started_at,
                    "last_handler_name": self.last_handler_name,
                    "active_handler_count": count,
                    "oldest_active_handler_at": oldest_at,
                    "oldest_active_handler": oldest_name,
                })
            except Exception:
                self.logger.debug("Could not persist handler start", exc_info=True)
        return token

    async def handler_finished(
        self, token: str | None, *, success: bool = True, detail: str = "ok"
    ) -> None:
        if token is None:
            return
        self.active_handlers.pop(token, None)
        now = int(time())
        self.last_handler_finished_at = now
        if not success:
            self.last_handler_failed_at = now
        count, oldest_at, oldest_name = self._active_handler_summary()
        if hasattr(self.db, "set_runtime_health_values"):
            try:
                await self.db.set_runtime_health_values({
                    "last_handler_finished_at": self.last_handler_finished_at,
                    "last_handler_failed_at": self.last_handler_failed_at,
                    "last_handler_result": "ok" if success else "failed",
                    "last_handler_detail": detail[:200],
                    "active_handler_count": count,
                    "oldest_active_handler_at": oldest_at,
                    "oldest_active_handler": oldest_name,
                })
            except Exception:
                self.logger.debug("Could not persist handler finish", exc_info=True)


    async def finish(self, reason: str) -> None:
        await self.db.set_runtime_health_values({
            "last_shutdown_reason": reason[:200],
        })
        await self.db.finish_process_run(self.run_id, reason)

    async def _with_timeout(self, awaitable) -> object:
        return await asyncio.wait_for(awaitable, timeout=self.PROBE_TIMEOUT)

    async def _probe_telegram(self) -> str:
        if not getattr(self.app, "is_connected", False):
            raise RuntimeError("Bot client is disconnected")
        await self._with_timeout(self.app.get_me())
        return "Connected"

    async def _probe_database(self) -> str:
        if not await self._with_timeout(self.db.ping()):
            raise RuntimeError("Database did not answer")
        return "Connected"

    async def _probe_assistants(self) -> str:
        sessions = await self._with_timeout(self.db.get_assistant_sessions())
        expected = {row["slot"] for row in sessions if row["enabled"]}
        active = set(self.userbot.accepting_slots)
        missing = expected - active
        disconnected = [
            slot
            for slot, client in self.userbot.clients.items()
            if slot in active
            if not getattr(client, "is_connected", False)
        ]
        if missing or disconnected:
            details = []
            if missing:
                details.append("missing " + ", ".join(map(str, sorted(missing))))
            if disconnected:
                details.append(
                    "disconnected " + ", ".join(map(str, sorted(disconnected)))
                )
            raise RuntimeError("Assistant sessions: " + "; ".join(details))
        if not expected:
            return "Not configured"
        return f"{len(active)}/{len(expected)} connected"

    async def _probe_voice(self) -> str:
        expected = set(self.userbot.clients)
        active = set(self.calls.clients)
        missing = expected - active
        dead = {
            slot
            for slot, client in self.calls.clients.items()
            if not getattr(client, "is_alive", True)
        }
        if missing or dead:
            unavailable = sorted(missing | dead)
            raise RuntimeError(
                "Voice workers unavailable for assistants "
                + ", ".join(map(str, unavailable))
            )
        if not active:
            return "Not configured"
        results = await asyncio.gather(
            *(
                self.calls.clients[slot].measure_ping()
                for slot in sorted(active)
            ),
            return_exceptions=True,
        )
        failed = [
            slot
            for slot, result in zip(sorted(active), results)
            if isinstance(result, BaseException)
        ]
        if failed:
            raise RuntimeError(
                "Voice workers did not answer for assistants "
                + ", ".join(map(str, failed))
            )
        return f"{len(active)} isolated worker(s) ready"

    async def _probe_application(self) -> str:
        if not _env_bool("WATCHDOG_ASSISTANT_PROBE", True):
            return "Skip: disabled"

        now = int(time())
        idle_seconds = _env_int("WATCHDOG_ASSISTANT_PROBE_IDLE_SECONDS", 300, 120)
        interval = _env_int("WATCHDOG_ASSISTANT_PROBE_INTERVAL_SECONDS", 300, 60)
        idle_for = now - self.last_update_at
        if idle_for < idle_seconds:
            return f"Skip: recent activity {idle_for}s ago"
        if now - self._assistant_probe_last_sent < interval:
            return f"Skip: waiting {now - self._assistant_probe_last_sent}s since last probe"

        assistants = [
            (slot, client)
            for slot, client in sorted(self.userbot.clients.items())
            if getattr(client, "is_connected", False)
        ]
        if not assistants:
            return "Skip: no connected assistant"

        slot, client = assistants[0]
        username = getattr(self.app, "username", None)
        if not username:
            raise RuntimeError("Bot username is unknown")

        nonce = uuid4().hex
        timeout = _env_int("WATCHDOG_ASSISTANT_PROBE_TIMEOUT_SECONDS", 20, 5)
        self._assistant_probe_last_sent = now
        await self._with_timeout(client.send_message(username, f"/__watchdog_probe {nonce}"))

        deadline = monotonic() + timeout
        while monotonic() < deadline:
            values = await self._with_timeout(self.db.get_runtime_health())
            seen = values.get("assistant_probe_seen_nonce", {}).get("value")
            if seen == nonce:
                return f"Assistant {slot} reached bot"
            await asyncio.sleep(1)
        raise RuntimeError(f"Assistant {slot} probe was not handled in {timeout}s")

    async def _check(self, name: str, probe) -> None:
        try:
            detail = await probe()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._record(name, False, f"{type(exc).__name__}: {exc}")
        else:
            if name == "application" and str(detail).startswith("Skip: "):
                self.components[name].detail = str(detail)[6:]
                return
            await self._record(name, True, detail)

    async def _record(self, name: str, success: bool, detail: str) -> None:
        state = self.components[name]
        now = monotonic()
        state.detail = detail
        if name == "Telegram":
            self.telegram_probe_at = int(time())
            self.telegram_probe_status = "ok" if success else "failed"
            self.telegram_probe_detail = detail[:200]
            if hasattr(self.db, "set_runtime_health_values"):
                try:
                    await self.db.set_runtime_health_values({
                        "telegram_probe_at": self.telegram_probe_at,
                        "telegram_probe_status": self.telegram_probe_status,
                        "telegram_probe_detail": self.telegram_probe_detail,
                        "telegram_probe_failures": state.failures + (0 if success else 1),
                    })
                except Exception:
                    self.logger.warning(
                        "Could not persist Telegram probe health", exc_info=True
                    )
        if name == "application":
            self.assistant_probe_at = int(time())
            self.assistant_probe_status = "ok" if success else "failed"
            self.assistant_probe_detail = detail[:200]
            self.assistant_probe_failures = state.failures + (0 if success else 1)
            if hasattr(self.db, "set_runtime_health_values"):
                try:
                    await self.db.set_runtime_health_values({
                        "assistant_probe_at": self.assistant_probe_at,
                        "assistant_probe_status": self.assistant_probe_status,
                        "assistant_probe_detail": self.assistant_probe_detail,
                        "assistant_probe_failures": self.assistant_probe_failures,
                    })
                except Exception:
                    self.logger.warning(
                        "Could not persist assistant probe health", exc_info=True
                    )
        if success:
            state.failures = 0
            state.successes += 1
            if state.status == "unknown":
                state.status = "healthy"
                state.changed_at = now
            elif state.status == "unhealthy" and state.successes >= self.RECOVERY_THRESHOLD:
                state.status = "healthy"
                state.changed_at = now
                self.logger.info("Health recovered: %s (%s)", name, detail)
                await self._alert(name, recovered=True, detail=detail)
            return

        state.successes = 0
        state.failures += 1
        if state.status != "unhealthy" and state.failures >= self.FAILURE_THRESHOLD:
            state.status = "unhealthy"
            state.changed_at = now
            state.reminded_at = now
            self.logger.error("Health check failed: %s (%s)", name, detail)
            await self._alert(name, recovered=False, detail=detail)
            await self._attempt_recovery(name)
        elif state.status == "unhealthy" and now - state.reminded_at >= self.REMINDER_INTERVAL:
            state.reminded_at = now
            self.logger.error("Health check still failing: %s (%s)", name, detail)
            await self._alert(name, recovered=False, detail=detail, reminder=True)

    async def _attempt_recovery(self, component: str) -> None:
        now = monotonic()
        previous = self._recovery_attempted.get(component)
        if previous is not None and now - previous < self.REMINDER_INTERVAL:
            return
        self._recovery_attempted[component] = now
        acted = False
        try:
            if component == "Telegram" and not getattr(self.app, "is_connected", False):
                await self._with_timeout(self.app.start())
                acted = True
            elif component == "assistants":
                sessions = await self._with_timeout(self.db.get_assistant_sessions())
                for session in sessions:
                    if session["enabled"] and session["slot"] not in self.userbot.clients:
                        await self._with_timeout(
                            self.userbot.enable_session(session["slot"])
                        )
                        acted = True
                for client in self.userbot.clients.values():
                    if not getattr(client, "is_connected", False):
                        await self._with_timeout(client.start())
                        acted = True
            elif component == "voice":
                for slot, client in self.userbot.clients.items():
                    if not self.userbot.is_accepting(slot):
                        continue
                    worker = self.calls.clients.get(slot)
                    if worker is None or not getattr(worker, "is_alive", True):
                        await self._with_timeout(self.calls.add_client(slot, client))
                        acted = True
            else:
                return
            if acted:
                self.logger.info("Local health recovery attempted for %s", component)
        except Exception:
            self.logger.warning(
                "Local health recovery failed for %s", component, exc_info=True
            )

    async def _alert(
        self,
        component: str,
        *,
        recovered: bool,
        detail: str,
        reminder: bool = False,
    ) -> None:
        if component == "Telegram" and not recovered:
            self._pending[component] = detail
            return
        stamp = datetime.now(timezone.utc).strftime("%d %b · %H:%M UTC")
        if recovered:
            previous = self._pending.pop(component, None)
            context = f"\nPrevious issue: {previous}" if previous else ""
            key = "health_alert_recovered"
            values = (component, detail, context, stamp)
        else:
            label = "still unavailable" if reminder else "needs attention"
            key = "health_alert_failed"
            values = (component, label, detail, stamp)
        await self._deliver(key, *values)
        if component == "Telegram" and recovered:
            await self._flush_pending_alerts()

    async def _deliver(self, key: str, *values) -> None:
        if not getattr(self.app, "is_connected", False):
            self._pending_alerts.append((key, values))
            return
        try:
            subscribers = await self.db.get_health_alert_subscribers()
        except Exception:
            self.logger.exception("Could not load health alert subscribers")
            return
        for user_id in subscribers:
            if user_id not in self.app.sudoers:
                continue
            try:
                locale = await self.language.get_lang(user_id)
                localized = list(values)
                if key in {"health_alert_recovered", "health_alert_failed"}:
                    component_key = "health_component_" + str(values[0]).replace(" ", "_")
                    localized[0] = locale.get(component_key, values[0])
                text = locale.get(key, self.language.languages["en"][key]).format(
                    *localized
                )
                await self._with_timeout(
                    self.app.send_message(
                        user_id, text, disable_notification=True
                    )
                )
            except Exception:
                self.logger.warning(
                    "Could not deliver health alert to sudo user %s",
                    user_id,
                    exc_info=True,
                )

    async def _flush_pending_alerts(self) -> None:
        pending, self._pending_alerts = self._pending_alerts, []
        for key, values in pending:
            await self._deliver(key, *values)

    async def _flush_startup_alert(self) -> None:
        previous = self._pending.pop("previous run", None)
        if previous:
            await self._deliver("health_alert_restart", previous)

    async def run(self) -> None:
        await self._flush_startup_alert()
        next_check = monotonic()
        while True:
            before_sleep = monotonic()
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            now = monotonic()
            lag = max(now - before_sleep - self.HEARTBEAT_INTERVAL, 0)
            await self._record(
                "event loop",
                lag < 10,
                f"Delay {lag:.1f}s" if lag >= 10 else "Responsive",
            )
            try:
                await self.db.heartbeat_process_run(self.run_id)
                self.last_heartbeat = int(time())
                await self.db.set_runtime_health_values({
                    "run_id": self.run_id,
                    "heartbeat_at": self.last_heartbeat,
                    "last_update_at": self.last_update_at,
                    "last_update_kind": self.last_update_kind,
                    "last_handler_started_at": self.last_handler_started_at,
                    "last_handler_finished_at": self.last_handler_finished_at,
                    "last_handler_failed_at": self.last_handler_failed_at,
                    "last_handler_name": self.last_handler_name,
                    "active_handler_count": self._active_handler_summary()[0],
                    "oldest_active_handler_at": self._active_handler_summary()[1],
                    "oldest_active_handler": self._active_handler_summary()[2],
                    "telegram_probe_at": self.telegram_probe_at,
                    "telegram_probe_status": self.telegram_probe_status,
                    "telegram_probe_detail": self.telegram_probe_detail,
                    "assistant_probe_at": self.assistant_probe_at,
                    "assistant_probe_status": self.assistant_probe_status,
                    "assistant_probe_detail": self.assistant_probe_detail,
                    "assistant_probe_failures": self.assistant_probe_failures,
                })
            except Exception as exc:
                await self._record(
                    "database", False, f"Heartbeat failed: {type(exc).__name__}: {exc}"
                )
            if now < next_check:
                continue
            next_check = now + self.CHECK_INTERVAL
            await self._check("Telegram", self._probe_telegram)
            await self._check("database", self._probe_database)
            await self._check("assistants", self._probe_assistants)
            await self._check("voice", self._probe_voice)
            await self._check("application", self._probe_application)
            await self._watchdog_stale_updates()

    async def _watchdog_stale_updates(self) -> None:
        if not self.watchdog_restart:
            return
        idle_for = int(time()) - self.last_update_at
        if idle_for < self.watchdog_stall_seconds:
            return
        reason = (
            f"watchdog: no Telegram updates processed for {idle_for}s "
            f"(last={self.last_update_kind})"
        )
        self.logger.critical(
            "Watchdog restart requested: %s. The external supervisor should restart the process.",
            reason,
        )
        try:
            await self.finish(reason)
        except Exception:
            self.logger.exception("Could not persist watchdog shutdown reason")
        logging.shutdown()
        os._exit(75)

    def snapshot(self) -> dict:
        supervisor = self.supervisor.snapshot()
        components = {
            name: {"status": state.status, "detail": state.detail}
            for name, state in self.components.items()
        }
        unhealthy = [
            name for name, state in self.components.items()
            if state.status == "unhealthy"
        ]
        previous = self.previous_run
        if not previous:
            previous_result = "No previous run"
        elif previous["stopped_at"] is None:
            previous_result = "Unexpected exit"
        else:
            previous_result = previous["stop_reason"] or "Clean shutdown"
        return {
            "healthy": not unhealthy and supervisor["healthy"],
            "components": components,
            "unhealthy": unhealthy,
            "workers": supervisor,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "last_heartbeat": self.last_heartbeat,
            "last_update_at": self.last_update_at,
            "last_update_kind": self.last_update_kind,
            "last_handler_started_at": self.last_handler_started_at,
            "last_handler_finished_at": self.last_handler_finished_at,
            "last_handler_failed_at": self.last_handler_failed_at,
            "last_handler_name": self.last_handler_name,
            "active_handler_count": self._active_handler_summary()[0],
            "oldest_active_handler_at": self._active_handler_summary()[1],
            "oldest_active_handler": self._active_handler_summary()[2],
            "telegram_probe_at": self.telegram_probe_at,
            "telegram_probe_status": self.telegram_probe_status,
            "telegram_probe_detail": self.telegram_probe_detail,
            "assistant_probe_at": self.assistant_probe_at,
            "assistant_probe_status": self.assistant_probe_status,
            "assistant_probe_detail": self.assistant_probe_detail,
            "assistant_probe_failures": self.assistant_probe_failures,
            "watchdog_enabled": self.watchdog_restart,
            "watchdog_stall_seconds": self.watchdog_stall_seconds,
            "previous_result": previous_result,
        }
