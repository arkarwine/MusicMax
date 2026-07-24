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

## External watchdog

Use the external watchdog for production. It is deliberately small: it reads the
bot's SQLite health state and restarts the bot only when Telegram updates are
stale and the assistant probe cannot prove the bot is still reachable.

Recommended `.env`:

```env
WATCHDOG_ENABLED=true
WATCHDOG_MODE=standard
WATCHDOG_PROCESS_MATCH=-m anony
```

Modes:

- `standard` — restart after 180s of stale updates unless the assistant probe passes.
- `strict` — restart after 120s.
- `relaxed` — restart after 300s.
- `off` — disable the watchdog.

Optional overrides:

```env
WATCHDOG_CHECK_INTERVAL=30
WATCHDOG_UPDATE_STALE_SECONDS=180
WATCHDOG_ASSISTANT_PROBE_STALE_SECONDS=300
WATCHDOG_RESTART_COOLDOWN_SECONDS=300
WATCHDOG_LOG_CHECKS=false
```

Decision rule:

```text
last Telegram update is fresh       -> healthy
last update is stale + probe passes -> quiet but reachable
last update is stale + no proof     -> restart
```

This intentionally ignores heartbeat, CPU, worker count, Bot API pings, and
handler age. Those are useful diagnostics, but they made recovery noisy. The only
question this watchdog answers is: "can the bot still process Telegram updates?"

Start the watchdog with PM2:

```bash
pm2 delete melodyfetch-watchdog 2>/dev/null || true
pm2 start /home/ubuntu/MelodyFetch/.venv/bin/python \
  --name melodyfetch-watchdog \
  --cwd /home/ubuntu/MelodyFetch \
  --interpreter none \
  -- \
  scripts/watchdog.py
pm2 save
```

With systemd, run the watchdog as its own small service and let the main bot
service use `Restart=always`.

`/status` shows the watchdog mode, stale-update window, assistant-probe window,
last recovery reason, last update, and current work.
