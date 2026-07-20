#!/usr/bin/env python3
"""External PM2 watchdog for an online-but-stale bot process."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path


DEFAULT_DB = "data/anonxmusic.db"


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


def db_path() -> Path:
    return Path(os.getenv("DATABASE_PATH") or DEFAULT_DB).expanduser()


def read_runtime_health(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        cursor = connection.execute(
            "SELECT key, value FROM runtime_health"
        )
        return {str(key): str(value) for key, value in cursor.fetchall()}
    except sqlite3.Error as exc:
        if "no such table" not in str(exc).lower():
            log(f"could not read runtime health: {type(exc).__name__}: {exc}")
        return {}
    finally:
        connection.close()


def write_runtime_health(path: Path, values: dict[str, object]) -> None:
    if not values:
        return
    connection = sqlite3.connect(path, timeout=5)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS runtime_health ("
            "key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL, "
            "updated_at INTEGER NOT NULL DEFAULT (unixepoch())"
            ")"
        )
        connection.executemany(
            "INSERT INTO runtime_health (key, value, updated_at) "
            "VALUES (?, ?, unixepoch()) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = unixepoch()",
            [(key, str(value)) for key, value in values.items()],
        )
        connection.commit()
    finally:
        connection.close()


def pm2_app(name: str) -> dict | None:
    result = subprocess.run(
        ["pm2", "jlist"],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        log(f"pm2 jlist failed: {result.stderr.strip() or result.stdout.strip()}")
        return None
    try:
        apps = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log(f"pm2 jlist returned invalid JSON: {exc}")
        return None
    for app in apps:
        if app.get("name") == name:
            return app
    log(f"PM2 app not found: {name}")
    return None


def app_uptime_seconds(app: dict, now: int) -> int:
    pm_uptime = ((app.get("pm2_env") or {}).get("pm_uptime")) or 0
    try:
        return max(now - int(pm_uptime / 1000), 0)
    except (TypeError, ValueError):
        return 0


def int_value(values: dict[str, str], key: str) -> int | None:
    try:
        return int(values[key])
    except (KeyError, TypeError, ValueError):
        return None


def restart(app_name: str, reason: str, path: Path, now: int) -> None:
    write_runtime_health(
        path,
        {
            "watchdog_last_restart_at": now,
            "watchdog_last_reason": reason,
        },
    )
    log(f"restarting {app_name}: {reason}")
    result = subprocess.run(
        ["pm2", "restart", app_name, "--update-env"],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        log(f"pm2 restart failed: {result.stderr.strip() or result.stdout.strip()}")


def check_once() -> None:
    if not env_bool("EXTERNAL_WATCHDOG", False):
        return

    app_name = os.getenv("WATCHDOG_PM2_APP", "GPH").strip() or "GPH"
    heartbeat_stale = env_int("WATCHDOG_HEARTBEAT_STALE_SECONDS", 180, minimum=60)
    update_stale = env_int("WATCHDOG_UPDATE_STALE_SECONDS", 900, minimum=300)
    min_uptime = env_int("WATCHDOG_MIN_UPTIME_SECONDS", 300, minimum=0)
    cooldown = env_int("WATCHDOG_RESTART_COOLDOWN_SECONDS", 600, minimum=60)
    path = db_path()
    now = int(time.time())

    app = pm2_app(app_name)
    if not app:
        return
    status = (app.get("pm2_env") or {}).get("status")
    if status != "online":
        log(f"{app_name} is {status or 'unknown'}; PM2 owns this state")
        return
    uptime = app_uptime_seconds(app, now)
    if uptime < min_uptime:
        return

    values = read_runtime_health(path)
    if not values:
        log("runtime health is unavailable; waiting for bot heartbeat")
        return

    last_restart = int_value(values, "watchdog_last_restart_at")
    if last_restart is not None and now - last_restart < cooldown:
        return

    heartbeat = int_value(values, "heartbeat_at")
    if heartbeat is not None and now - heartbeat > heartbeat_stale:
        restart(
            app_name,
            f"heartbeat stale for {now - heartbeat}s",
            path,
            now,
        )
        return

    kind = values.get("last_update_kind", "unknown")
    last_update = int_value(values, "last_update_at")
    if (
        last_update is not None
        and kind != "startup"
        and now - last_update > update_stale
    ):
        restart(
            app_name,
            f"Telegram updates stale for {now - last_update}s (last={kind})",
            path,
            now,
        )


def main() -> None:
    load_env()
    interval = env_int("WATCHDOG_CHECK_INTERVAL", 30, minimum=10)
    log(
        "started "
        f"(enabled={env_bool('EXTERNAL_WATCHDOG', False)}, "
        f"app={os.getenv('WATCHDOG_PM2_APP', 'GPH')})"
    )
    while True:
        try:
            check_once()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log(f"check failed: {type(exc).__name__}: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
