# PM2 reliability on Ubuntu

Run the bot from its virtual environment and repository directory so relative
paths, SQLite, cookies, downloads, and logs always resolve consistently.

```bash
cd /home/ubuntu/MelodyFetch

pm2 delete melodyfetch 2>/dev/null || true
pm2 start /home/ubuntu/MelodyFetch/.venv/bin/python \
  --name melodyfetch \
  --cwd /home/ubuntu/MelodyFetch \
  --interpreter none \
  --time \
  --restart-delay 3000 \
  --kill-timeout 30000 \
  -- \
  -m anony

pm2 save
pm2 startup systemd -u ubuntu --hp /home/ubuntu
```

Run the final command printed by `pm2 startup`, then run `pm2 save` again.
PM2 restarts the process only when it actually exits. The bot's normal health
monitor reports degraded components without requesting a PM2 restart. For the
rare case where Python stays online but Telegram update handling goes stale, an
optional hard watchdog can deliberately exit with code 75 so PM2 restarts it.
No arbitrary memory restart limit is configured.

## Routine checks

```bash
pm2 describe melodyfetch
pm2 logs melodyfetch --lines 300 --nostream
pm2 monit
free -h
df -h
```

In `pm2 describe`, check the restart count, last exit code, exit signal,
unstable restarts, uptime, and current memory. A clean PM2 stop produces a
`signal:SIGTERM` shutdown reason in the bot log.

## Silent process exits

Python cannot write a final message after `SIGKILL`, an out-of-memory kill, or
some native crashes. Inspect the Ubuntu kernel and PM2 service logs:

```bash
sudo journalctl -k --since "24 hours ago" \
  | grep -Ei 'oom|out of memory|killed process|segfault'

sudo journalctl -u pm2-ubuntu --since "24 hours ago"
```

The next successful bot start also checks SQLite process history. An unfinished
previous run is logged as an unexpected exit with its last recorded heartbeat.

## Optional stale-update watchdog

Enable the internal watchdog only for production bots that have shown the "online
but not responding" failure mode.

```bash
WATCHDOG_RESTART_ON_STALL=true
WATCHDOG_STALL_SECONDS=21600
```

The value is seconds. The default example is six hours, with a minimum of five
minutes. When triggered, the bot records a `watchdog:` shutdown reason in
SQLite, flushes logs, exits non-zero, and lets PM2 restart the process.

## External watchdog

For stronger recovery, run a separate watchdog process that watches persisted SQLite
health signals from outside the bot process. The default setup is intentionally
small: enable it and keep the standard process matcher. All timings already
have production-safe defaults.

Minimal `.env`:

```bash
EXTERNAL_WATCHDOG=true
WATCHDOG_PROCESS_MATCH=-m anony
```

Default behavior:

```text
check every 30s
restart if heartbeat is stale for 180s
restart if Telegram self-check is stale for 180s
restart if real updates are stale for 300s
restart if external Bot API check fails 3 times
wait 300s after fresh startup
wait 600s between watchdog restarts
terminate with SIGTERM, then SIGKILL after 15s
log state changes and one healthy summary every 300s
```

Optional overrides:

```bash
WATCHDOG_HEARTBEAT_STALE_SECONDS=180
WATCHDOG_UPDATE_STALE_SECONDS=300
WATCHDOG_INTERNAL_PROBE_STALE_SECONDS=180
WATCHDOG_INTERNAL_PROBE_FAILURES=3
WATCHDOG_BOT_API_PROBE=true
WATCHDOG_BOT_API_FAILURES=3
WATCHDOG_PROBE_TIMEOUT_SECONDS=5
WATCHDOG_MIN_UPTIME_SECONDS=300
WATCHDOG_RESTART_COOLDOWN_SECONDS=600
WATCHDOG_KILL_GRACE_SECONDS=15
WATCHDOG_CHECK_INTERVAL=30
WATCHDOG_LOG_INTERVAL_SECONDS=300
WATCHDOG_LOG_CHECKS=false
```

The watchdog does **not** call `pm2 jlist`, `pm2 restart`, Docker, systemd, or
any other supervisor API. It finds the bot process by working directory and
`WATCHDOG_PROCESS_MATCH`, sends `SIGTERM`, then sends `SIGKILL` after the grace
period. Your external supervisor's normal autorestart starts the bot again.

Use a stricter matcher if more than one `-m anony` process runs from the same
repository directory:

```bash
WATCHDOG_PROCESS_MATCH=/home/ubuntu/MelodyFetch/.venv/bin/python -m anony
```

Start the watchdog with PM2:

```bash
pm2 delete melodyfetch-watchdog 2>/dev/null || true
pm2 start /home/ubuntu/MelodyFetch/.venv/bin/python \
  --name melodyfetch-watchdog \
  --cwd /home/ubuntu/MelodyFetch \
  --interpreter none \
  --time \
  --restart-delay 3000 \
  -- \
  scripts/watchdog.py

pm2 save
```

`/status` shows the internal watchdog, external watchdog configuration, last
processed update, and the last external watchdog restart reason.
## Private health alerts

Each sudo user chooses independently in the bot's private chat:

```text
/healthalerts on
/healthalerts off
```

Alerts are off by default. They report health state changes and recovery without
stopping the process. `/status` shows the current supervisor state, workers,
heartbeat freshness, previous shutdown result, and personal alert preference.
