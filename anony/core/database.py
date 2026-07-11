# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import json
import sqlite3
from contextlib import suppress
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from random import randint
from time import time

import aiosqlite

from anony import config, logger, userbot


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
                    feedback_cleanup INTEGER NOT NULL DEFAULT 1
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
                CREATE TABLE IF NOT EXISTS sudoers (
                    user_id INTEGER PRIMARY KEY
                );
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
                """
            )
            await self._ensure_column(
                "chats", "default_video", "INTEGER NOT NULL DEFAULT 0"
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
            for key, value in overrides.items():
                try:
                    config.set_runtime(key, value)
                except (KeyError, ValueError):
                    logger.warning("Ignored invalid runtime config value: %s", key)
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

    async def is_chat(self, chat_id: int) -> bool:
        return chat_id in self.chats

    async def add_chat(self, chat_id: int) -> None:
        if not await self.is_chat(chat_id):
            self.chats.append(chat_id)
            await self.conn.execute("INSERT OR IGNORE INTO chats (chat_id) VALUES (?)", (chat_id,))
            await self.conn.commit()

    async def rm_chat(self, chat_id: int) -> None:
        if await self.is_chat(chat_id):
            self.chats.remove(chat_id)
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
        await self.conn.commit()

    async def get_sudoers(self) -> list[int]:
        cursor = await self.conn.execute("SELECT user_id FROM sudoers")
        return [row[0] for row in await cursor.fetchall()]

    async def is_user(self, user_id: int) -> bool:
        return user_id in self.users

    async def add_user(self, user_id: int) -> None:
        if not await self.is_user(user_id):
            self.users.append(user_id)
            await self.conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
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
