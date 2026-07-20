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

## External PM2 watchdog

For stronger recovery, run a second PM2 process that watches persisted SQLite
health signals from outside the bot process. This can restart the bot even if the
bot's own health monitor stops running.

Add these values to `.env`:

```bash
EXTERNAL_WATCHDOG=true
WATCHDOG_PM2_APP=melodyfetch
WATCHDOG_HEARTBEAT_STALE_SECONDS=180
WATCHDOG_UPDATE_STALE_SECONDS=900
WATCHDOG_MIN_UPTIME_SECONDS=300
WATCHDOG_RESTART_COOLDOWN_SECONDS=600
WATCHDOG_CHECK_INTERVAL=30
```

Start the watchdog:

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

The external watchdog does not restart during fresh startup, PM2 downtime, recent
watchdog restarts, missing databases, or before the bot has processed at least
one real Telegram update. It restarts only the configured `WATCHDOG_PM2_APP`.

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
