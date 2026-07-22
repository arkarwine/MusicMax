#!/usr/bin/env python3
"""Compact external watchdog for an online-but-unresponsive bot.

Single decision rule:
- if Telegram updates are stale, ask whether the assistant probe proves the bot is
  still reachable;
- if not, terminate the bot process and let the external supervisor restart it.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB = "data/anonxmusic.db"
_last_check_log_at = 0
_last_check_state = ""


@dataclass(frozen=True)
class WatchdogSettings:
    enabled: bool
    mode: str
    interval: int
    update_stale: int
    assistant_stale: int
    min_uptime: int
    cooldown: int
    kill_grace: int
    log_checks: bool
    log_interval: int
    process_match: str


PRESETS = {
    "standard": {"updates": 180, "assistant": 300, "min_uptime": 120, "cooldown": 300},
    "strict": {"updates": 120, "assistant": 240, "min_uptime": 90, "cooldown": 240},
    "relaxed": {"updates": 300, "assistant": 480, "min_uptime": 180, "cooldown": 420},
}


def log(message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    print(f"[{stamp}] watchdog: {message}", flush=True)


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int((os.getenv(name) or "").strip())
    except ValueError:
        return default
    return max(value, minimum)


def env_mode() -> str:
    mode = (os.getenv("WATCHDOG_MODE") or "standard").strip().lower()
    if mode in {"off", "disabled", "false", "0"}:
        return "off"
    if mode not in PRESETS:
        log(f"unknown WATCHDOG_MODE={mode!r}; using standard")
        return "standard"
    return mode


def settings() -> WatchdogSettings:
    mode = env_mode()
    preset = PRESETS.get(mode, PRESETS["standard"])
    enabled = False if mode == "off" else env_bool(
        "WATCHDOG_ENABLED", env_bool("EXTERNAL_WATCHDOG", False)
    )
    return WatchdogSettings(
        enabled=enabled,
        mode=mode,
        interval=env_int("WATCHDOG_CHECK_INTERVAL", 30, minimum=10),
        update_stale=env_int("WATCHDOG_UPDATE_STALE_SECONDS", preset["updates"], minimum=60),
        assistant_stale=env_int("WATCHDOG_ASSISTANT_PROBE_STALE_SECONDS", preset["assistant"], minimum=120),
        min_uptime=env_int("WATCHDOG_MIN_UPTIME_SECONDS", preset["min_uptime"], minimum=0),
        cooldown=env_int("WATCHDOG_RESTART_COOLDOWN_SECONDS", preset["cooldown"], minimum=60),
        kill_grace=env_int("WATCHDOG_KILL_GRACE_SECONDS", 15, minimum=1),
        log_checks=env_bool("WATCHDOG_LOG_CHECKS", False),
        log_interval=env_int("WATCHDOG_LOG_INTERVAL_SECONDS", 300, minimum=30),
        process_match=os.getenv("WATCHDOG_PROCESS_MATCH", "-m anony").strip(),
    )


def db_path() -> Path:
    return Path(os.getenv("DATABASE_PATH") or DEFAULT_DB).expanduser()


def read_runtime_health(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        cursor = connection.execute("SELECT key, value FROM runtime_health")
        return {str(key): str(value) for key, value in cursor.fetchall()}
    except sqlite3.Error as exc:
        if "no such table" not in str(exc).lower():
            log(f"health read failed: {type(exc).__name__}: {exc}")
        return {}
    finally:
        connection.close()


def write_runtime_health(path: Path, values: dict[str, object]) -> None:
    if not values:
        return
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS runtime_health (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT (unixepoch()))")
        connection.executemany(
            "INSERT INTO runtime_health (key, value, updated_at) VALUES (?, ?, unixepoch()) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = unixepoch()",
            [(key, str(value)) for key, value in values.items()],
        )
        connection.commit()
    finally:
        connection.close()


def int_value(values: dict[str, str], key: str) -> int | None:
    try:
        return int(values[key])
    except (KeyError, TypeError, ValueError):
        return None


def age(now: int, timestamp: int | None) -> int | None:
    return now - timestamp if timestamp is not None else None


def should_log_check(now: int, state: str, cfg: WatchdogSettings) -> bool:
    global _last_check_log_at, _last_check_state
    if cfg.log_checks:
        _last_check_log_at = now
        _last_check_state = state
        return True
    if state != _last_check_state or now - _last_check_log_at >= cfg.log_interval:
        _last_check_log_at = now
        _last_check_state = state
        return True
    return False


def log_check(now: int, state: str, cfg: WatchdogSettings, **details: object) -> None:
    if not should_log_check(now, state, cfg):
        return
    parts = [f"state={state}"]
    for key, value in details.items():
        if value is not None:
            parts.append(f"{key}={value}")
    log("check " + " ".join(parts))


def proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "ignore").strip()


def proc_cwd(pid: int) -> Path | None:
    try:
        return Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return None


def find_bot_pids(match: str) -> list[int]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    expected_cwd = Path.cwd().resolve()
    self_pid = os.getpid()
    pids: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == self_pid:
            continue
        command = proc_cmdline(pid)
        if not command or "scripts/watchdog.py" in command:
            continue
        if match and match not in command:
            continue
        if proc_cwd(pid) != expected_cwd:
            continue
        pids.append(pid)
    return sorted(pids)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_bot_processes(reason: str) -> bool:
    cfg = settings()
    pids = find_bot_pids(cfg.process_match)
    if not pids:
        log(f"restart skipped: no matching bot process ({cfg.process_match!r})")
        return False
    log(f"restart requested: {reason}; pids={pids}")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            log(f"SIGTERM failed pid={pid}: {type(exc).__name__}: {exc}")
    deadline = time.time() + cfg.kill_grace
    while time.time() < deadline:
        if not any(process_alive(pid) for pid in pids):
            return True
        time.sleep(0.5)
    alive = [pid for pid in pids if process_alive(pid)]
    if alive:
        log(f"force killing pids={alive} after {cfg.kill_grace}s")
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError as exc:
                log(f"SIGKILL failed pid={pid}: {type(exc).__name__}: {exc}")
    return True


def restart(reason: str, path: Path, now: int) -> None:
    write_runtime_health(path, {
        "watchdog_last_restart_at": now,
        "watchdog_last_reason": reason,
    })
    terminate_bot_processes(reason)


def assistant_proves_reachable(values: dict[str, str], now: int, cfg: WatchdogSettings) -> bool:
    probe_at = int_value(values, "assistant_probe_at")
    probe_age = age(now, probe_at)
    return (
        values.get("assistant_probe_status") == "ok"
        and probe_age is not None
        and probe_age <= cfg.assistant_stale
    )


def assistant_probe_pending(values: dict[str, str], now: int, cfg: WatchdogSettings) -> bool:
    probe_at = int_value(values, "assistant_probe_at")
    probe_age = age(now, probe_at)
    status = values.get("assistant_probe_status", "unknown")
    return status in {"startup", "unknown"} and probe_age is not None and probe_age <= cfg.assistant_stale


def check_once() -> None:
    cfg = settings()
    if not cfg.enabled:
        return
    path = db_path()
    now = int(time.time())
    values = read_runtime_health(path)
    if not values:
        log_check(now, "waiting", cfg, reason="no-health", db=path)
        return

    started_at = int_value(values, "started_at")
    uptime = age(now, started_at)
    if uptime is not None and uptime < cfg.min_uptime:
        log_check(now, "warming-up", cfg, uptime=f"{uptime}s", ready_after=f"{cfg.min_uptime}s")
        return

    last_restart = int_value(values, "watchdog_last_restart_at")
    restart_age = age(now, last_restart)
    cooldown_left = cfg.cooldown - restart_age if restart_age is not None else None
    if cooldown_left is not None and cooldown_left > 0:
        log_check(now, "cooldown", cfg, remaining=f"{cooldown_left}s")
        return

    kind = values.get("last_update_kind", "unknown")
    update_age = age(now, int_value(values, "last_update_at"))
    assistant_at = int_value(values, "assistant_probe_at")
    assistant_age = age(now, assistant_at)
    assistant_status = values.get("assistant_probe_status", "unknown")

    if update_age is None or kind == "startup" or update_age <= cfg.update_stale:
        log_check(
            now,
            "healthy",
            cfg,
            updates=f"{update_age}s" if update_age is not None else "unknown",
            assistant=f"{assistant_status}/{assistant_age}s" if assistant_age is not None else assistant_status,
        )
        return

    if assistant_proves_reachable(values, now, cfg):
        log_check(now, "quiet-but-reachable", cfg, updates=f"{update_age}s", assistant=f"ok/{assistant_age}s")
        return

    if assistant_probe_pending(values, now, cfg):
        log_check(now, "probing", cfg, updates=f"{update_age}s", assistant=f"{assistant_status}/{assistant_age}s")
        return

    reason = f"Telegram updates stale for {update_age}s; assistant probe {assistant_status}/{assistant_age}s"
    log_check(now, "restart", cfg, reason=reason, limit=f"{cfg.update_stale}s")
    restart(reason, path, now)


def main() -> None:
    load_env()
    cfg = settings()
    log(
        "started "
        f"mode={cfg.mode} enabled={cfg.enabled} interval={cfg.interval}s "
        f"updates={cfg.update_stale}s assistant={cfg.assistant_stale}s"
    )
    while True:
        try:
            check_once()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log(f"check failed: {type(exc).__name__}: {exc}")
        time.sleep(settings().interval)


if __name__ == "__main__":
    main()
