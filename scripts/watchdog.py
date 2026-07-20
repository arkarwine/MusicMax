#!/usr/bin/env python3
"""External watchdog for an online-but-stale bot process.

The watchdog deliberately avoids supervisor-specific APIs. It only checks
persisted health signals and terminates stale bot processes. Any external
supervisor can then restart the bot.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_DB = "data/anonxmusic.db"
_last_check_log_at = 0
_last_check_state = ""
_bot_api_failures = 0


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


def bot_api_get_me(token: str, timeout: int = 5) -> tuple[bool, str]:
    if not token:
        return False, "BOT_TOKEN is missing"
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if '"ok":true' not in body.replace(" ", "").lower():
        return False, "Bot API returned ok=false"
    return True, "ok"


def check_bot_api_probe(path: Path, now: int) -> tuple[bool, str, int]:
    global _bot_api_failures
    if not env_bool("WATCHDOG_BOT_API_PROBE", True):
        return True, "disabled", _bot_api_failures
    token = os.getenv("BOT_TOKEN", "").strip()
    timeout = env_int("WATCHDOG_PROBE_TIMEOUT_SECONDS", 5, minimum=1)
    ok, detail = bot_api_get_me(token, timeout=timeout)
    _bot_api_failures = 0 if ok else _bot_api_failures + 1
    write_runtime_health(
        path,
        {
            "external_bot_api_probe_at": now,
            "external_bot_api_probe_status": "ok" if ok else "failed",
            "external_bot_api_probe_detail": detail[:200],
            "external_bot_api_probe_failures": _bot_api_failures,
        },
    )
    return ok, detail, _bot_api_failures


def int_value(values: dict[str, str], key: str) -> int | None:
    try:
        return int(values[key])
    except (KeyError, TypeError, ValueError):
        return None


def should_log_check(now: int, state: str) -> bool:
    global _last_check_log_at, _last_check_state
    if env_bool("WATCHDOG_LOG_CHECKS", False):
        _last_check_log_at = now
        _last_check_state = state
        return True
    interval = env_int("WATCHDOG_LOG_INTERVAL_SECONDS", 300, minimum=30)
    if state != _last_check_state or now - _last_check_log_at >= interval:
        _last_check_log_at = now
        _last_check_state = state
        return True
    return False


def log_check(now: int, state: str, **details: object) -> None:
    if not should_log_check(now, state):
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


def find_bot_pids() -> list[int]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    self_pid = os.getpid()
    expected_cwd = Path.cwd().resolve()
    match = os.getenv("WATCHDOG_PROCESS_MATCH", "-m anony").strip()
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
        cwd = proc_cwd(pid)
        if cwd != expected_cwd:
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
    pids = find_bot_pids()
    if not pids:
        log(
            "no matching bot process found "
            f"(WATCHDOG_PROCESS_MATCH={os.getenv('WATCHDOG_PROCESS_MATCH', '-m anony')!r})"
        )
        return False

    grace = env_int("WATCHDOG_KILL_GRACE_SECONDS", 15, minimum=1)
    log(f"terminating stale bot process(es) {pids}: {reason}")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            log(f"could not SIGTERM {pid}: {type(exc).__name__}: {exc}")

    deadline = time.time() + grace
    while time.time() < deadline:
        if not any(process_alive(pid) for pid in pids):
            return True
        time.sleep(0.5)

    alive = [pid for pid in pids if process_alive(pid)]
    if alive:
        log(f"forcing stale bot process(es) {alive} after {grace}s")
        for pid in alive:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError as exc:
                log(f"could not SIGKILL {pid}: {type(exc).__name__}: {exc}")
    return True


def restart(reason: str, path: Path, now: int) -> None:
    write_runtime_health(
        path,
        {
            "watchdog_last_restart_at": now,
            "watchdog_last_reason": reason,
        },
    )
    terminate_bot_processes(reason)


def check_once() -> None:
    if not env_bool("EXTERNAL_WATCHDOG", False):
        return

    heartbeat_stale = env_int("WATCHDOG_HEARTBEAT_STALE_SECONDS", 180, minimum=60)
    update_stale = env_int("WATCHDOG_UPDATE_STALE_SECONDS", 300, minimum=120)
    internal_probe_stale = env_int(
        "WATCHDOG_INTERNAL_PROBE_STALE_SECONDS", 180, minimum=60
    )
    internal_probe_failures_limit = env_int(
        "WATCHDOG_INTERNAL_PROBE_FAILURES", 3, minimum=1
    )
    bot_api_failures_limit = env_int(
        "WATCHDOG_BOT_API_FAILURES", 3, minimum=1
    )
    min_uptime = env_int("WATCHDOG_MIN_UPTIME_SECONDS", 300, minimum=0)
    cooldown = env_int("WATCHDOG_RESTART_COOLDOWN_SECONDS", 600, minimum=60)
    path = db_path()
    now = int(time.time())

    values = read_runtime_health(path)
    if not values:
        log_check(now, "waiting", reason="no-runtime-health", db=path)
        return

    started_at = int_value(values, "started_at")
    uptime = now - started_at if started_at is not None else None
    if started_at is not None and uptime < min_uptime:
        log_check(
            now,
            "warming-up",
            uptime=f"{uptime}s",
            min_uptime=f"{min_uptime}s",
        )
        return

    last_restart = int_value(values, "watchdog_last_restart_at")
    cooldown_left = None
    if last_restart is not None:
        cooldown_left = cooldown - (now - last_restart)
    if cooldown_left is not None and cooldown_left > 0:
        log_check(now, "cooldown", remaining=f"{cooldown_left}s")
        return

    heartbeat = int_value(values, "heartbeat_at")
    heartbeat_age = now - heartbeat if heartbeat is not None else None
    if heartbeat_age is not None and heartbeat_age > heartbeat_stale:
        log_check(
            now,
            "stale-heartbeat",
            heartbeat_age=f"{heartbeat_age}s",
            limit=f"{heartbeat_stale}s",
        )
        restart(
            f"heartbeat stale for {heartbeat_age}s",
            path,
            now,
        )
        return

    internal_probe_at = int_value(values, "telegram_probe_at")
    internal_probe_age = now - internal_probe_at if internal_probe_at is not None else None
    internal_probe_status = values.get("telegram_probe_status", "unknown")
    internal_probe_failures = int_value(values, "telegram_probe_failures") or 0
    if internal_probe_age is not None and internal_probe_age > internal_probe_stale:
        log_check(
            now,
            "stale-internal-telegram-probe",
            probe_age=f"{internal_probe_age}s",
            limit=f"{internal_probe_stale}s",
            status=internal_probe_status,
        )
        restart(
            f"internal Telegram probe stale for {internal_probe_age}s "
            f"(status={internal_probe_status})",
            path,
            now,
        )
        return
    if (
        internal_probe_status == "failed"
        and internal_probe_failures >= internal_probe_failures_limit
    ):
        log_check(
            now,
            "internal-telegram-probe-failed",
            failures=internal_probe_failures,
            limit=internal_probe_failures_limit,
            detail=values.get("telegram_probe_detail", ""),
        )
        restart(
            "internal Telegram probe failed "
            f"{internal_probe_failures} time(s): "
            f"{values.get('telegram_probe_detail', '')}",
            path,
            now,
        )
        return

    bot_api_ok, bot_api_detail, bot_api_failures = check_bot_api_probe(path, now)
    if not bot_api_ok and bot_api_failures >= bot_api_failures_limit:
        log_check(
            now,
            "external-bot-api-probe-failed",
            failures=bot_api_failures,
            limit=bot_api_failures_limit,
            detail=bot_api_detail,
        )
        restart(
            f"external Bot API probe failed {bot_api_failures} time(s): "
            f"{bot_api_detail}",
            path,
            now,
        )
        return

    kind = values.get("last_update_kind", "unknown")
    last_update = int_value(values, "last_update_at")
    update_age = now - last_update if last_update is not None else None
    if (
        update_age is not None
        and kind != "startup"
        and update_age > update_stale
    ):
        log_check(
            now,
            "stale-updates",
            update_age=f"{update_age}s",
            limit=f"{update_stale}s",
            last=kind,
        )
        restart(
            f"Telegram updates stale for {update_age}s (last={kind})",
            path,
            now,
        )
        return

    log_check(
        now,
        "healthy",
        heartbeat_age=f"{heartbeat_age}s" if heartbeat_age is not None else "unknown",
        update_age=f"{update_age}s" if update_age is not None else "unknown",
        last=kind,
        internal_probe=(
            f"{internal_probe_status}/{internal_probe_age}s"
            if internal_probe_age is not None else internal_probe_status
        ),
        bot_api=("ok" if bot_api_ok else f"failed/{bot_api_failures}"),
    )


def main() -> None:
    load_env()
    interval = env_int("WATCHDOG_CHECK_INTERVAL", 30, minimum=10)
    log(
        "started "
        f"(enabled={env_bool('EXTERNAL_WATCHDOG', False)}, "
        f"app={os.getenv('WATCHDOG_APP_NAME', 'anony')}, "
        f"bot_api_probe={env_bool('WATCHDOG_BOT_API_PROBE', True)}, "
        f"log_checks={env_bool('WATCHDOG_LOG_CHECKS', False)}, "
        f"log_interval={env_int('WATCHDOG_LOG_INTERVAL_SECONDS', 300, minimum=30)}s)"
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
