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
PM2 restarts the process only when it actually exits. The bot's internal health
monitor reports degraded components but does not deliberately exit or request a
PM2 restart. No arbitrary memory restart limit is configured.

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

## Private health alerts

Each sudo user chooses independently in the bot's private chat:

```text
/healthalerts on
/healthalerts off
```

Alerts are off by default. They report health state changes and recovery without
stopping the process. `/status` shows the current supervisor state, workers,
heartbeat freshness, previous shutdown result, and personal alert preference.
