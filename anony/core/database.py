# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import json
import sqlite3
from contextlib import suppress
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import randint
from time import time

import aiosqlite

from anony import config, logger, userbot
from anony.core.audio import normalize_audio_mode


class SQLiteDB:
    def __init__(self):
        self.path = Path(config.DATABASE_PATH).expanduser()
        self.connection: aiosqlite.Connection | None = None
        self.write_lock = asyncio.Lock()

        self.admin_list = {}
        self.active_calls = {}
        self.admin_play = []
        self.blacklisted = []
        self.cmd_delete = []
        self.audio_mode = {}
        self.default_video = {}
        self.feedback_cleanup = {}
        self.loop = {}
        self.notified = []
        self.logger = False

        self.assistant = {}
        self.auth = {}
        self.chats = []
        self.lang = {}
        self.users = []

    @property
    def conn(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not connected")
        return self.connection

    async def connect(self) -> None:
        """Open the SQLite database and initialize its schema."""
        try:
            start = time()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = await aiosqlite.connect(self.path)
            with suppress(OSError):
                self.path.chmod(0o600)
            await self.conn.execute("PRAGMA journal_mode = WAL")
            await self.conn.execute("PRAGMA foreign_keys = ON")
            await self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS assistants (
                    chat_id INTEGER PRIMARY KEY,
                    num INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assistant_sessions (
                    slot INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_string TEXT NOT NULL UNIQUE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'runtime',
                    user_id INTEGER,
                    username TEXT,
                    display_name TEXT,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                CREATE TABLE IF NOT EXISTS blacklist (
                    kind TEXT NOT NULL CHECK (kind IN ('chat', 'user')),
                    entity_id INTEGER NOT NULL,
                    PRIMARY KEY (kind, entity_id)
                );
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    cmd_delete INTEGER NOT NULL DEFAULT 0,
                    admin_play INTEGER NOT NULL DEFAULT 0,
                    default_video INTEGER NOT NULL DEFAULT 0,
                    feedback_cleanup INTEGER NOT NULL DEFAULT 1,
                    audio_mode TEXT NOT NULL DEFAULT 'original'
                        CHECK (audio_mode IN ('original', 'spatial', 'hall'))
                );
                CREATE TABLE IF NOT EXISTS languages (
                    chat_id INTEGER PRIMARY KEY,
                    lang TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                CREATE TABLE IF NOT EXISTS themes (
                    theme_id TEXT PRIMARY KEY,
                    manifest TEXT NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                CREATE TABLE IF NOT EXISTS theme_overrides (
                    theme_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    PRIMARY KEY (theme_id, path),
                    FOREIGN KEY (theme_id) REFERENCES themes(theme_id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sudoers (
                    user_id INTEGER PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS health_alert_subscriptions (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1
                        CHECK (enabled IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS process_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    heartbeat_at INTEGER NOT NULL DEFAULT (unixepoch()),
                    stopped_at INTEGER,
                    stop_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS process_runs_started
                    ON process_runs (started_at DESC);
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS playback_sessions (
                    chat_id INTEGER PRIMARY KEY,
                    assistant_num INTEGER,
                    state TEXT NOT NULL DEFAULT 'waiting',
                    position_seconds INTEGER NOT NULL DEFAULT 0,
                    loop_remaining INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                CREATE TABLE IF NOT EXISTS queue_items (
                    chat_id INTEGER NOT NULL,
                    item_order INTEGER NOT NULL,
                    item_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (chat_id, item_order)
                );
                CREATE INDEX IF NOT EXISTS queue_items_chat
                    ON queue_items (chat_id, item_order);
                CREATE TABLE IF NOT EXISTS analytics_daily (
                    day TEXT PRIMARY KEY,
                    users_added INTEGER NOT NULL DEFAULT 0,
                    groups_added INTEGER NOT NULL DEFAULT 0,
                    plays INTEGER NOT NULL DEFAULT 0,
                    peak_streams INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS stream_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    started_at INTEGER NOT NULL DEFAULT (unixepoch())
                );
                CREATE INDEX IF NOT EXISTS stream_events_started
                    ON stream_events (started_at);
                CREATE INDEX IF NOT EXISTS stream_events_chat_started
                    ON stream_events (chat_id, started_at);
                CREATE TABLE IF NOT EXISTS track_plays (
                    day TEXT NOT NULL,
                    track_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT,
                    plays INTEGER NOT NULL DEFAULT 0,
                    last_played INTEGER NOT NULL DEFAULT (unixepoch()),
                    PRIMARY KEY (day, track_id)
                );
                CREATE INDEX IF NOT EXISTS track_plays_recent
                    ON track_plays (day, plays DESC);
                """
            )
            await self._ensure_column(
                "chats", "default_video", "INTEGER NOT NULL DEFAULT 0"
            )
            await self._ensure_column(
                "chats",
                "audio_mode",
                "TEXT NOT NULL DEFAULT 'original' "
                "CHECK (audio_mode IN ('original', 'spatial', 'hall'))",
            )
            cleanup_added = await self._ensure_column(
                "chats", "feedback_cleanup", "INTEGER NOT NULL DEFAULT 1"
            )
            if cleanup_added:
                # Existing groups retain their previous message behavior.
                await self.conn.execute(
                    "UPDATE chats SET feedback_cleanup = 0"
                )
            await self.conn.commit()
            overrides = await self.get_runtime_config()
            invalid_runtime_keys = []
            for key, value in overrides.items():
                try:
                    config.set_runtime(key, value)
                except (KeyError, ValueError):
                    logger.warning("Ignored invalid runtime config value: %s", key)
                    invalid_runtime_keys.append(key)
            if invalid_runtime_keys:
                await self.conn.executemany(
                    "DELETE FROM runtime_config WHERE key = ?",
                    ((key,) for key in invalid_runtime_keys),
                )
                await self.conn.commit()
            await self.compact_assistant_slots()
            logger.info(f"Database connection successful. ({time() - start:.2f}s)")
            await self.load_cache()
        except Exception as e:
            if self.connection is not None:
                await self.connection.close()
                self.connection = None
            raise SystemExit(f"Database connection failed: {type(e).__name__}") from e

    async def _ensure_column(
        self,
        table: str,
        column: str,
        definition: str,
    ) -> bool:
        cursor = await self.conn.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cursor.fetchall()}
        if column not in columns:
            await self.conn.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )
            return True
        return False

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None
        logger.info("Database connection closed.")

    async def backup(self, keep: int = 7) -> Path:
        backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        destination = backup_dir / f"anonxmusic-{stamp}.db"
        target = sqlite3.connect(destination)
        try:
            async with self.write_lock:
                await self.conn.backup(target)
        finally:
            target.close()
        with suppress(OSError):
            destination.chmod(0o600)

        backups = sorted(backup_dir.glob("anonxmusic-*.db"), reverse=True)
        for old_backup in backups[max(keep, 1):]:
            old_backup.unlink(missing_ok=True)
        return destination

    async def get_call(self, chat_id: int) -> bool:
        return chat_id in self.active_calls

    async def add_call(self, chat_id: int) -> None:
        self.active_calls[chat_id] = 1
        try:
            await self.record_peak(sum(self.active_calls.values()))
        except Exception:
            logger.warning("Could not update the daily stream peak", exc_info=True)

    async def remove_call(self, chat_id: int) -> None:
        self.active_calls.pop(chat_id, None)

    async def playing(self, chat_id: int, paused: bool = None) -> bool | None:
        if paused is not None:
            self.active_calls[chat_id] = int(not paused)
            await self.conn.execute(
                "UPDATE playback_sessions SET state = ?, updated_at = unixepoch() "
                "WHERE chat_id = ?",
                ("paused" if paused else "playing", chat_id),
            )
            await self.conn.commit()
            if paused is False:
                try:
                    await self.record_peak(sum(self.active_calls.values()))
                except Exception:
                    logger.warning(
                        "Could not update the daily stream peak after resume",
                        exc_info=True,
                    )
        return bool(self.active_calls.get(chat_id, 0))

    async def get_admins(self, chat_id: int, reload: bool = False) -> list[int]:
        from anony.helpers._admins import reload_admins

        if chat_id not in self.admin_list or reload:
            self.admin_list[chat_id] = await reload_admins(chat_id)
        return self.admin_list[chat_id]

    async def get_loop(self, chat_id: int) -> int:
        return self.loop.get(chat_id, 0)

    async def set_loop(self, chat_id: int, count: int) -> None:
        self.loop[chat_id] = count
        await self.conn.execute(
            "UPDATE playback_sessions SET loop_remaining = ?, updated_at = unixepoch() "
            "WHERE chat_id = ?",
            (count, chat_id),
        )
        await self.conn.commit()

    @staticmethod
    def _json_value(value):
        """Convert Telegram wrapper values into plain JSON-safe values."""
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return str(value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (list, tuple, set)):
            return [SQLiteDB._json_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): SQLiteDB._json_value(item)
                for key, item in value.items()
            }
        return str(value)

    async def save_queue(self, chat_id: int, items: list) -> None:
        rows = []
        for position, item in enumerate(items):
            if is_dataclass(item):
                payload = {
                    field.name: self._json_value(getattr(item, field.name))
                    for field in fields(item)
                }
            else:
                payload = {
                    key: self._json_value(value)
                    for key, value in vars(item).items()
                }
            rows.append(
                (chat_id, position, type(item).__name__.lower(), json.dumps(payload))
            )

        async with self.write_lock:
            await self.conn.execute("DELETE FROM queue_items WHERE chat_id = ?", (chat_id,))
            if rows:
                await self.conn.executemany(
                    "INSERT INTO queue_items "
                    "(chat_id, item_order, item_type, payload) VALUES (?, ?, ?, ?)",
                    rows,
                )
            await self.conn.commit()

    async def save_playback(
        self,
        chat_id: int,
        state: str,
        position: int = 0,
    ) -> None:
        assistant_num = self.assistant.get(chat_id)
        await self.conn.execute(
            "INSERT INTO playback_sessions "
            "(chat_id, assistant_num, state, position_seconds, loop_remaining, updated_at) "
            "VALUES (?, ?, ?, ?, ?, unixepoch()) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "assistant_num = excluded.assistant_num, state = excluded.state, "
            "position_seconds = excluded.position_seconds, "
            "loop_remaining = excluded.loop_remaining, updated_at = unixepoch()",
            (chat_id, assistant_num, state, max(position, 0), self.loop.get(chat_id, 0)),
        )
        await self.conn.commit()

    async def checkpoint_playback(self, chat_id: int, position: int) -> None:
        await self.conn.execute(
            "UPDATE playback_sessions SET position_seconds = ?, updated_at = unixepoch() "
            "WHERE chat_id = ?",
            (max(position, 0), chat_id),
        )
        await self.conn.commit()

    async def mark_playback_waiting(self, chat_id: int, position: int = 0) -> None:
        await self.save_playback(chat_id, "waiting", position)

    async def clear_playback(self, chat_id: int) -> None:
        async with self.write_lock:
            await self.conn.execute(
                "DELETE FROM playback_sessions WHERE chat_id = ?", (chat_id,)
            )
            await self.conn.execute("DELETE FROM queue_items WHERE chat_id = ?", (chat_id,))
            await self.conn.commit()

    async def get_recovery_sessions(self) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT chat_id, assistant_num, state, position_seconds, loop_remaining "
            "FROM playback_sessions ORDER BY updated_at"
        )
        sessions = []
        for chat_id, assistant_num, state, position, loop in await cursor.fetchall():
            items_cursor = await self.conn.execute(
                "SELECT item_type, payload FROM queue_items "
                "WHERE chat_id = ? ORDER BY item_order",
                (chat_id,),
            )
            items = [
                {"type": item_type, "payload": json.loads(payload)}
                for item_type, payload in await items_cursor.fetchall()
            ]
            sessions.append(
                {
                    "chat_id": chat_id,
                    "assistant_num": assistant_num,
                    "state": state,
                    "position": position,
                    "loop": loop,
                    "items": items,
                }
            )
        return sessions

    async def get_playback_state(self, chat_id: int) -> str | None:
        cursor = await self.conn.execute(
            "SELECT state FROM playback_sessions WHERE chat_id = ?", (chat_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def _get_auth(self, chat_id: int) -> set[int]:
        if chat_id not in self.auth:
            cursor = await self.conn.execute(
                "SELECT user_id FROM auth WHERE chat_id = ?", (chat_id,)
            )
            self.auth[chat_id] = {row[0] for row in await cursor.fetchall()}
        return self.auth[chat_id]

    async def is_auth(self, chat_id: int, user_id: int) -> bool:
        return user_id in await self._get_auth(chat_id)

    async def add_auth(self, chat_id: int, user_id: int) -> None:
        users = await self._get_auth(chat_id)
        if user_id not in users:
            users.add(user_id)
            await self.conn.execute(
                "INSERT OR IGNORE INTO auth (chat_id, user_id) VALUES (?, ?)",
                (chat_id, user_id),
            )
            await self.conn.commit()

    async def rm_auth(self, chat_id: int, user_id: int) -> None:
        users = await self._get_auth(chat_id)
        if user_id in users:
            users.discard(user_id)
            await self.conn.execute(
                "DELETE FROM auth WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            await self.conn.commit()

    async def set_assistant(self, chat_id: int, slot: int | None = None) -> int:
        from anony import anon

        slots = tuple(
            slot for slot in userbot.clients if slot in anon.clients
        )
        if not slots:
            raise RuntimeError("No assistant sessions are active")
        if slot is not None and slot not in slots:
            raise RuntimeError(f"Assistant session {slot} is not active")
        num = slot if slot is not None else slots[randint(0, len(slots) - 1)]
        await self.conn.execute(
            "INSERT INTO assistants (chat_id, num) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET num = excluded.num",
            (chat_id, num),
        )
        await self.conn.commit()
        self.assistant[chat_id] = num
        return num

    async def get_assistant(self, chat_id: int):
        from anony import anon

        num = self.assistant.get(chat_id)
        if num is None:
            cursor = await self.conn.execute(
                "SELECT num FROM assistants WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            num = row[0] if row else None
        if not num or num not in anon.clients:
            num = await self.set_assistant(chat_id)
        self.assistant[chat_id] = num
        return anon.clients[num]

    async def get_client(self, chat_id: int):
        if chat_id not in self.assistant:
            await self.get_assistant(chat_id)
        num = self.assistant[chat_id]
        if num not in userbot.clients:
            num = await self.set_assistant(chat_id)
        return userbot.clients[num]

    async def ensure_assistant_session(
        self,
        session_string: str,
        source: str = "runtime",
    ) -> int:
        async with self.write_lock:
            cursor = await self.conn.execute(
                "SELECT slot FROM assistant_sessions WHERE session_string = ?",
                (session_string,),
            )
            row = await cursor.fetchone()
            if row:
                if source == "environment":
                    await self.conn.execute(
                        "UPDATE assistant_sessions SET source = 'environment' "
                        "WHERE slot = ?",
                        (row[0],),
                    )
                    await self.conn.commit()
                return row[0]

            cursor = await self.conn.execute(
                "SELECT slot FROM assistant_sessions ORDER BY slot"
            )
            used = {row[0] for row in await cursor.fetchall()}
            slot = 1
            while slot in used:
                slot += 1
            await self.conn.execute(
                "INSERT INTO assistant_sessions (slot, session_string, source) "
                "VALUES (?, ?, ?)",
                (slot, session_string, source),
            )
            await self.conn.commit()
            return slot

    async def get_assistant_sessions(self) -> list[dict]:
        cursor = await self.conn.execute(
            "SELECT slot, session_string, enabled, source, user_id, username, "
            "display_name, created_at FROM assistant_sessions ORDER BY slot"
        )
        return [
            {
                "slot": row[0],
                "session_string": row[1],
                "enabled": bool(row[2]),
                "source": row[3],
                "user_id": row[4],
                "username": row[5],
                "display_name": row[6],
                "created_at": row[7],
            }
            for row in await cursor.fetchall()
        ]

    async def get_assistant_session(self, slot: int) -> dict | None:
        return next(
            (
                session
                for session in await self.get_assistant_sessions()
                if session["slot"] == slot
            ),
            None,
        )

    async def update_assistant_session(
        self,
        slot: int,
        *,
        enabled: bool | None = None,
        user_id: int | None = None,
        username: str | None = None,
        display_name: str | None = None,
    ) -> None:
        updates = []
        values = []
        for column, value in (
            ("enabled", None if enabled is None else int(enabled)),
            ("user_id", user_id),
            ("username", username),
            ("display_name", display_name),
        ):
            if value is not None:
                updates.append(f"{column} = ?")
                values.append(value)
        if not updates:
            return
        values.append(slot)
        await self.conn.execute(
            f"UPDATE assistant_sessions SET {', '.join(updates)} WHERE slot = ?",
            values,
        )
        await self.conn.commit()

    async def release_assistant_slot(self, slot: int) -> None:
        await self.conn.execute("DELETE FROM assistants WHERE num = ?", (slot,))
        await self.conn.execute(
            "UPDATE playback_sessions SET assistant_num = NULL "
            "WHERE assistant_num = ?",
            (slot,),
        )
        await self.conn.commit()
        for chat_id, assigned in list(self.assistant.items()):
            if assigned == slot:
                self.assistant.pop(chat_id, None)

    async def compact_assistant_slots(self) -> dict[int, int]:
        """Keep public assistant IDs dense while preserving every reference."""
        async with self.write_lock:
            cursor = await self.conn.execute(
                "SELECT slot FROM assistant_sessions ORDER BY slot"
            )
            slots = [row[0] for row in await cursor.fetchall()]
            mapping = {old: new for new, old in enumerate(slots, start=1)}
            changed = {old: new for old, new in mapping.items() if old != new}
            if not changed:
                return mapping

            for old in changed:
                await self.conn.execute(
                    "UPDATE assistant_sessions SET slot = ? WHERE slot = ?",
                    (-old, old),
                )
                await self.conn.execute(
                    "UPDATE assistants SET num = ? WHERE num = ?", (-old, old)
                )
                await self.conn.execute(
                    "UPDATE playback_sessions SET assistant_num = ? "
                    "WHERE assistant_num = ?",
                    (-old, old),
                )
            for old, new in changed.items():
                await self.conn.execute(
                    "UPDATE assistant_sessions SET slot = ? WHERE slot = ?",
                    (new, -old),
                )
                await self.conn.execute(
                    "UPDATE assistants SET num = ? WHERE num = ?", (new, -old)
                )
                await self.conn.execute(
                    "UPDATE playback_sessions SET assistant_num = ? "
                    "WHERE assistant_num = ?",
                    (new, -old),
                )
            await self.conn.commit()
            self.assistant = {
                chat_id: mapping.get(assigned, assigned)
                for chat_id, assigned in self.assistant.items()
            }
            return mapping

    async def delete_assistant_session(self, slot: int) -> dict[int, int]:
        await self.release_assistant_slot(slot)
        await self.conn.execute(
            "DELETE FROM assistant_sessions WHERE slot = ?", (slot,)
        )
        await self.conn.commit()
        return await self.compact_assistant_slots()

    def active_chats_for_assistant(self, slot: int) -> list[int]:
        return [
            chat_id
            for chat_id in self.active_calls
            if self.assistant.get(chat_id) == slot
        ]

    async def add_blacklist(self, chat_id: int) -> None:
        kind = "chat" if chat_id < 0 else "user"
        if kind == "chat" and chat_id not in self.blacklisted:
            self.blacklisted.append(chat_id)
        await self.conn.execute(
            "INSERT OR IGNORE INTO blacklist (kind, entity_id) VALUES (?, ?)",
            (kind, chat_id),
        )
        await self.conn.commit()

    async def del_blacklist(self, chat_id: int) -> None:
        kind = "chat" if chat_id < 0 else "user"
        if kind == "chat" and chat_id in self.blacklisted:
            self.blacklisted.remove(chat_id)
        await self.conn.execute(
            "DELETE FROM blacklist WHERE kind = ? AND entity_id = ?", (kind, chat_id)
        )
        await self.conn.commit()

    async def get_blacklisted(self, chat: bool = False) -> list[int]:
        kind = "chat" if chat else "user"
        cursor = await self.conn.execute(
            "SELECT entity_id FROM blacklist WHERE kind = ?", (kind,)
        )
        values = [row[0] for row in await cursor.fetchall()]
        if chat:
            self.blacklisted[:] = values
            return self.blacklisted
        return values

    async def _increment_analytics(
        self,
        *,
        users_added: int = 0,
        groups_added: int = 0,
        plays: int = 0,
        peak_streams: int = 0,
    ) -> None:
        await self.conn.execute(
            "INSERT INTO analytics_daily "
            "(day, users_added, groups_added, plays, peak_streams) "
            "VALUES (date('now'), ?, ?, ?, ?) "
            "ON CONFLICT(day) DO UPDATE SET "
            "users_added = users_added + excluded.users_added, "
            "groups_added = groups_added + excluded.groups_added, "
            "plays = plays + excluded.plays, "
            "peak_streams = MAX(peak_streams, excluded.peak_streams)",
            (users_added, groups_added, plays, peak_streams),
        )

    async def record_peak(self, active_streams: int) -> None:
        async with self.write_lock:
            await self._increment_analytics(
                peak_streams=max(active_streams, 0),
            )
            await self.conn.commit()

    async def record_play(
        self,
        chat_id: int,
        *,
        track_id: str | None = None,
        title: str | None = None,
        url: str | None = None,
    ) -> None:
        async with self.write_lock:
            await self._increment_analytics(plays=1)
            await self.conn.execute(
                "INSERT INTO stream_events (chat_id, started_at) "
                "VALUES (?, unixepoch())",
                (chat_id,),
            )
            await self.conn.execute(
                "DELETE FROM stream_events "
                "WHERE started_at < unixepoch() - 2678400"
            )
            if track_id and title:
                await self.conn.execute(
                    "INSERT INTO track_plays "
                    "(day, track_id, title, url, plays, last_played) "
                    "VALUES (date('now'), ?, ?, ?, 1, unixepoch()) "
                    "ON CONFLICT(day, track_id) DO UPDATE SET "
                    "title = excluded.title, url = excluded.url, "
                    "plays = track_plays.plays + 1, last_played = unixepoch()",
                    (
                        str(track_id)[:128],
                        str(title)[:300],
                        str(url)[:500] if url else None,
                    ),
                )
                await self.conn.execute(
                    "DELETE FROM track_plays WHERE day < date('now', '-30 days')"
                )
            await self.conn.commit()

    async def get_stream_activity(self, hours: int = 24) -> dict:
        hours = max(1, min(hours, 24 * 31))
        cursor = await self.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT chat_id) FROM stream_events "
            "WHERE started_at >= unixepoch() - ?",
            (hours * 3600,),
        )
        row = await cursor.fetchone()
        return {
            "streams": int(row[0] if row else 0),
            "active_chats": int(row[1] if row else 0),
        }

    async def get_trending_tracks(
        self,
        days: int = 7,
        limit: int = 10,
    ) -> list[dict]:
        days = max(1, min(days, 30))
        limit = max(1, min(limit, 20))
        cursor = await self.conn.execute(
            "SELECT track_id, MAX(title), MAX(url), SUM(plays), "
            "MAX(last_played) FROM track_plays "
            "WHERE day >= date('now', ?) GROUP BY track_id "
            "ORDER BY SUM(plays) DESC, MAX(last_played) DESC LIMIT ?",
            (f"-{days - 1} days", limit),
        )
        return [
            {
                "id": row[0],
                "title": row[1],
                "url": row[2],
                "plays": row[3],
                "last_played": row[4],
            }
            for row in await cursor.fetchall()
        ]

    async def get_analytics(self, days: int = 7) -> list[dict]:
        days = max(1, min(days, 31))
        today = datetime.now(timezone.utc).date()
        first = today - timedelta(days=days - 1)
        cursor = await self.conn.execute(
            "SELECT day, users_added, groups_added, plays, peak_streams "
            "FROM analytics_daily WHERE day >= ? ORDER BY day",
            (first.isoformat(),),
        )
        stored = {
            row[0]: {
                "users_added": row[1],
                "groups_added": row[2],
                "plays": row[3],
                "peak_streams": row[4],
            }
            for row in await cursor.fetchall()
        }
        activity_cursor = await self.conn.execute(
            "SELECT date(started_at, 'unixepoch'), COUNT(DISTINCT chat_id) "
            "FROM stream_events WHERE started_at >= unixepoch(?) "
            "GROUP BY date(started_at, 'unixepoch')",
            (first.isoformat(),),
        )
        active_chats = {
            row[0]: int(row[1])
            for row in await activity_cursor.fetchall()
        }
        result = []
        for offset in range(days):
            day = first + timedelta(days=offset)
            values = stored.get(day.isoformat(), {})
            result.append(
                {
                    "day": day.isoformat(),
                    "label": day.strftime("%a"),
                    "users_added": values.get("users_added", 0),
                    "groups_added": values.get("groups_added", 0),
                    "plays": values.get("plays", 0),
                    "active_chats": active_chats.get(day.isoformat(), 0),
                    "peak_streams": values.get("peak_streams", 0),
                }
            )
        return result

    async def get_analytics_totals(self) -> dict:
        cursor = await self.conn.execute(
            "SELECT COALESCE(SUM(users_added), 0), "
            "COALESCE(SUM(groups_added), 0), COALESCE(SUM(plays), 0) "
            "FROM analytics_daily"
        )
        row = await cursor.fetchone()
        return {
            "users_added": int(row[0] if row else 0),
            "groups_added": int(row[1] if row else 0),
            "plays": int(row[2] if row else 0),
        }

    async def is_chat(self, chat_id: int) -> bool:
        return chat_id in self.chats

    async def add_chat(self, chat_id: int) -> None:
        if not await self.is_chat(chat_id):
            self.chats.append(chat_id)
            await self.conn.execute("INSERT OR IGNORE INTO chats (chat_id) VALUES (?)", (chat_id,))
            await self._increment_analytics(groups_added=1)
            await self.conn.commit()

    async def rm_chat(self, chat_id: int) -> None:
        if await self.is_chat(chat_id):
            self.chats.remove(chat_id)
            self.audio_mode.pop(chat_id, None)
            self.default_video.pop(chat_id, None)
            self.feedback_cleanup.pop(chat_id, None)
            await self.conn.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            await self.conn.commit()

    async def get_chats(self) -> list[int]:
        cursor = await self.conn.execute("SELECT chat_id FROM chats")
        self.chats[:] = [row[0] for row in await cursor.fetchall()]
        return self.chats

    async def get_cmd_delete(self, chat_id: int) -> bool:
        if chat_id not in self.cmd_delete:
            cursor = await self.conn.execute(
                "SELECT cmd_delete FROM chats WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            if row and row[0]:
                self.cmd_delete.append(chat_id)
        return chat_id in self.cmd_delete

    async def set_cmd_delete(self, chat_id: int, delete: bool = False) -> None:
        if delete and chat_id not in self.cmd_delete:
            self.cmd_delete.append(chat_id)
        elif not delete and chat_id in self.cmd_delete:
            self.cmd_delete.remove(chat_id)
        await self.conn.execute(
            "INSERT INTO chats (chat_id, cmd_delete) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET cmd_delete = excluded.cmd_delete",
            (chat_id, int(delete)),
        )
        await self.conn.commit()

    async def get_default_video(self, chat_id: int) -> bool:
        if chat_id not in self.default_video:
            cursor = await self.conn.execute(
                "SELECT default_video FROM chats WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            self.default_video[chat_id] = bool(row[0]) if row else False
        return self.default_video[chat_id]

    async def set_default_video(self, chat_id: int, video: bool) -> None:
        self.default_video[chat_id] = video
        await self.conn.execute(
            "INSERT INTO chats (chat_id, default_video) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "default_video = excluded.default_video",
            (chat_id, int(video)),
        )
        await self.conn.commit()

    async def get_audio_mode(self, chat_id: int) -> str:
        if chat_id not in self.audio_mode:
            cursor = await self.conn.execute(
                "SELECT audio_mode FROM chats WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            self.audio_mode[chat_id] = normalize_audio_mode(row[0] if row else None)
        return self.audio_mode[chat_id]

    async def set_audio_mode(self, chat_id: int, mode: str) -> None:
        selected = normalize_audio_mode(mode)
        self.audio_mode[chat_id] = selected
        await self.conn.execute(
            "INSERT INTO chats (chat_id, audio_mode) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET audio_mode = excluded.audio_mode",
            (chat_id, selected),
        )
        await self.conn.commit()

    async def get_feedback_cleanup(self, chat_id: int) -> bool:
        if chat_id not in self.feedback_cleanup:
            cursor = await self.conn.execute(
                "SELECT feedback_cleanup FROM chats WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            self.feedback_cleanup[chat_id] = bool(row[0]) if row else True
        return self.feedback_cleanup[chat_id]

    async def set_feedback_cleanup(self, chat_id: int, enabled: bool) -> None:
        self.feedback_cleanup[chat_id] = enabled
        await self.conn.execute(
            "INSERT INTO chats (chat_id, feedback_cleanup) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "feedback_cleanup = excluded.feedback_cleanup",
            (chat_id, int(enabled)),
        )
        await self.conn.commit()

    async def set_lang(self, chat_id: int, lang_code: str) -> None:
        if lang_code not in {"en", "my"}:
            lang_code = "en"
        await self.conn.execute(
            "INSERT INTO languages (chat_id, lang) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET lang = excluded.lang",
            (chat_id, lang_code),
        )
        await self.conn.commit()
        self.lang[chat_id] = lang_code

    async def get_lang(self, chat_id: int) -> str:
        if chat_id not in self.lang:
            cursor = await self.conn.execute(
                "SELECT lang FROM languages WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            selected = row[0] if row else config.LANG_CODE
            self.lang[chat_id] = selected if selected in {"en", "my"} else "en"
        return self.lang[chat_id]

    async def get_runtime_config(self) -> dict[str, str]:
        cursor = await self.conn.execute(
            "SELECT key, value FROM runtime_config ORDER BY key"
        )
        return dict(await cursor.fetchall())

    async def set_runtime_config(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO runtime_config (key, value, updated_at) "
            "VALUES (?, ?, unixepoch()) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = unixepoch()",
            (key, value),
        )
        await self.conn.commit()

    async def reset_runtime_config(self, key: str) -> None:
        await self.conn.execute("DELETE FROM runtime_config WHERE key = ?", (key,))
        await self.conn.commit()

    async def reset_all_runtime_config(self) -> None:
        """Atomically remove every runtime override."""
        await self.conn.execute("DELETE FROM runtime_config")
        await self.conn.commit()

    async def migrate_theme_config_to_runtime(
        self, _theme_id: str, values: dict[str, str]
    ) -> None:
        """Move legacy per-theme config edits to bot-wide overrides once."""
        async with self.write_lock:
            if values:
                await self.conn.executemany(
                    "INSERT INTO runtime_config (key, value, updated_at) "
                    "VALUES (?, ?, unixepoch()) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                    "updated_at = unixepoch()",
                    tuple(values.items()),
                )
            await self.conn.execute(
                "DELETE FROM theme_overrides WHERE path LIKE 'config.%'"
            )
            await self.conn.execute(
                "INSERT INTO settings (key, value) VALUES "
                "('runtime_config_v2', '1') ON CONFLICT(key) DO NOTHING"
            )
            await self.conn.commit()

    async def get_setting_value(self, key: str) -> str | None:
        cursor = await self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def set_setting_value(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    async def get_theme_manifests(self) -> dict[str, dict]:
        cursor = await self.conn.execute(
            "SELECT theme_id, manifest FROM themes ORDER BY theme_id"
        )
        result = {}
        for theme_id, manifest in await cursor.fetchall():
            try:
                result[theme_id] = json.loads(manifest)
            except (TypeError, json.JSONDecodeError):
                logger.warning("Ignored invalid stored theme: %s", theme_id)
        return result

    async def save_theme_manifest(self, theme_id: str, manifest: dict) -> None:
        encoded = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
        await self.conn.execute(
            "INSERT INTO themes (theme_id, manifest) VALUES (?, ?) "
            "ON CONFLICT(theme_id) DO UPDATE SET manifest = excluded.manifest, "
            "updated_at = unixepoch()",
            (theme_id, encoded),
        )
        await self.conn.commit()

    async def delete_theme_manifest(self, theme_id: str) -> None:
        await self.conn.execute("DELETE FROM themes WHERE theme_id = ?", (theme_id,))
        await self.conn.commit()

    async def get_theme_overrides(self, theme_id: str) -> dict[str, object]:
        cursor = await self.conn.execute(
            "SELECT path, value FROM theme_overrides WHERE theme_id = ?",
            (theme_id,),
        )
        result = {}
        for path, value in await cursor.fetchall():
            try:
                result[path] = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                logger.warning("Ignored invalid theme override: %s %s", theme_id, path)
        return result

    async def set_theme_override(
        self, theme_id: str, path: str, value: object
    ) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        await self.conn.execute(
            "INSERT INTO theme_overrides (theme_id, path, value) VALUES (?, ?, ?) "
            "ON CONFLICT(theme_id, path) DO UPDATE SET value = excluded.value, "
            "updated_at = unixepoch()",
            (theme_id, path, encoded),
        )
        await self.conn.commit()

    async def reset_theme_override(self, theme_id: str, path: str) -> None:
        await self.conn.execute(
            "DELETE FROM theme_overrides WHERE theme_id = ? AND path = ?",
            (theme_id, path),
        )
        await self.conn.commit()

    async def reset_theme_overrides(
        self, theme_id: str, prefix: str | None = None
    ) -> None:
        if prefix is None:
            await self.conn.execute(
                "DELETE FROM theme_overrides WHERE theme_id = ?", (theme_id,)
            )
        else:
            await self.conn.execute(
                "DELETE FROM theme_overrides WHERE theme_id = ? AND path LIKE ?",
                (theme_id, prefix + "%"),
            )
        await self.conn.commit()

    async def complete_theme_migration(
        self, active_theme: str, manifest: dict | None = None
    ) -> None:
        async with self.write_lock:
            if manifest is not None:
                encoded = json.dumps(
                    manifest, ensure_ascii=False, separators=(",", ":")
                )
                await self.conn.execute(
                    "INSERT OR IGNORE INTO themes (theme_id, manifest) VALUES (?, ?)",
                    (manifest["id"], encoded),
                )
            await self.conn.execute(
                "INSERT INTO settings (key, value) VALUES ('active_theme', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (active_theme,),
            )
            await self.conn.execute(
                "INSERT INTO settings (key, value) VALUES "
                "('theme_migration_v1', '1') ON CONFLICT(key) DO NOTHING"
            )
            await self.conn.execute("DELETE FROM runtime_config")
            await self.conn.commit()

    async def is_logger(self) -> bool:
        return self.logger

    async def get_logger(self) -> bool:
        cursor = await self.conn.execute("SELECT value FROM settings WHERE key = 'logger'")
        row = await cursor.fetchone()
        self.logger = bool(int(row[0])) if row else False
        return self.logger

    async def set_logger(self, status: bool) -> None:
        self.logger = status
        await self.conn.execute(
            "INSERT INTO settings (key, value) VALUES ('logger', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(int(status)),),
        )
        await self.conn.commit()

    async def get_log_chat(self) -> int | None:
        cursor = await self.conn.execute(
            "SELECT value FROM settings WHERE key = 'log_chat_id'"
        )
        row = await cursor.fetchone()
        return int(row[0]) if row and row[0] else None

    async def set_log_chat(self, chat_id: int | None) -> None:
        if chat_id is None:
            await self.conn.execute(
                "DELETE FROM settings WHERE key = 'log_chat_id'"
            )
        else:
            await self.conn.execute(
                "INSERT INTO settings (key, value) VALUES ('log_chat_id', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(chat_id),),
            )
        await self.conn.commit()

    async def get_play_mode(self, chat_id: int) -> bool:
        if chat_id not in self.admin_play:
            cursor = await self.conn.execute(
                "SELECT admin_play FROM chats WHERE chat_id = ?", (chat_id,)
            )
            row = await cursor.fetchone()
            if row and row[0]:
                self.admin_play.append(chat_id)
        return chat_id in self.admin_play

    async def set_play_mode(self, chat_id: int, remove: bool = False) -> None:
        enabled = not remove
        if enabled and chat_id not in self.admin_play:
            self.admin_play.append(chat_id)
        elif not enabled and chat_id in self.admin_play:
            self.admin_play.remove(chat_id)
        await self.conn.execute(
            "INSERT INTO chats (chat_id, admin_play) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET admin_play = excluded.admin_play",
            (chat_id, int(enabled)),
        )
        await self.conn.commit()

    async def add_sudo(self, user_id: int) -> None:
        await self.conn.execute("INSERT OR IGNORE INTO sudoers (user_id) VALUES (?)", (user_id,))
        await self.conn.commit()

    async def del_sudo(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM sudoers WHERE user_id = ?", (user_id,))
        await self.conn.execute(
            "DELETE FROM health_alert_subscriptions WHERE user_id = ?",
            (user_id,),
        )
        await self.conn.commit()

    async def get_sudoers(self) -> list[int]:
        cursor = await self.conn.execute("SELECT user_id FROM sudoers")
        return [row[0] for row in await cursor.fetchall()]

    async def set_health_alerts(self, user_id: int, enabled: bool) -> None:
        if enabled:
            await self.conn.execute(
                "INSERT INTO health_alert_subscriptions (user_id, enabled) "
                "VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET enabled = 1",
                (user_id,),
            )
        else:
            await self.conn.execute(
                "DELETE FROM health_alert_subscriptions WHERE user_id = ?",
                (user_id,),
            )
        await self.conn.commit()

    async def health_alerts_enabled(self, user_id: int) -> bool:
        cursor = await self.conn.execute(
            "SELECT enabled FROM health_alert_subscriptions WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return bool(row and row[0])

    async def get_health_alert_subscribers(self) -> list[int]:
        cursor = await self.conn.execute(
            "SELECT user_id FROM health_alert_subscriptions WHERE enabled = 1"
        )
        return [int(row[0]) for row in await cursor.fetchall()]

    async def start_process_run(self, run_id: str) -> dict | None:
        cursor = await self.conn.execute(
            "SELECT run_id, started_at, heartbeat_at, stopped_at, stop_reason "
            "FROM process_runs ORDER BY started_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        previous = None
        if row:
            previous = {
                "run_id": row[0],
                "started_at": int(row[1]),
                "heartbeat_at": int(row[2]),
                "stopped_at": int(row[3]) if row[3] is not None else None,
                "stop_reason": row[4],
            }
        await self.conn.execute(
            "INSERT INTO process_runs (run_id) VALUES (?)", (run_id,)
        )
        await self.conn.commit()
        return previous

    async def heartbeat_process_run(self, run_id: str) -> None:
        await self.conn.execute(
            "UPDATE process_runs SET heartbeat_at = unixepoch() WHERE run_id = ?",
            (run_id,),
        )
        await self.conn.commit()

    async def finish_process_run(self, run_id: str, reason: str) -> None:
        await self.conn.execute(
            "UPDATE process_runs SET heartbeat_at = unixepoch(), "
            "stopped_at = unixepoch(), stop_reason = ? WHERE run_id = ?",
            (reason[:200], run_id),
        )
        await self.conn.commit()

    async def ping(self) -> bool:
        cursor = await self.conn.execute("SELECT 1")
        row = await cursor.fetchone()
        return bool(row and row[0] == 1)

    async def is_user(self, user_id: int) -> bool:
        return user_id in self.users

    async def add_user(self, user_id: int) -> None:
        if not await self.is_user(user_id):
            self.users.append(user_id)
            await self.conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await self._increment_analytics(users_added=1)
            await self.conn.commit()

    async def rm_user(self, user_id: int) -> None:
        if await self.is_user(user_id):
            self.users.remove(user_id)
            await self.conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            await self.conn.commit()

    async def get_users(self) -> list[int]:
        cursor = await self.conn.execute("SELECT user_id FROM users")
        self.users[:] = [row[0] for row in await cursor.fetchall()]
        return self.users

    async def load_cache(self) -> None:
        await self.get_chats()
        await self.get_users()
        await self.get_blacklisted(True)
        await self.get_logger()
        logger.info("Database cache loaded.")
