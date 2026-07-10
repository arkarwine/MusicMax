# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from dataclasses import fields
from pathlib import Path

from pyrogram.types import Message

from anony import anon, app, db, lang, logger, queue, userbot, yt
from anony.helpers import Media, Track


class PlaybackRecovery:
    """Reload saved queues and play their current track after startup."""

    def __init__(self) -> None:
        self.sessions: list[dict] = []

    @staticmethod
    def _restore_item(item: dict) -> Media | Track:
        cls = Track if item["type"] == "track" else Media
        allowed = {field.name for field in fields(cls)}
        payload = {
            key: value for key, value in item["payload"].items() if key in allowed
        }
        return cls(**payload)

    async def restore_queues(self) -> int:
        self.sessions = await db.get_recovery_sessions()
        restored = 0
        for session in self.sessions:
            chat_id = session["chat_id"]
            try:
                items = [self._restore_item(item) for item in session["items"]]
            except Exception:
                logger.exception("Could not restore the saved queue for chat %s", chat_id)
                continue

            if not items:
                await db.clear_playback(chat_id)
                continue

            queue.restore(chat_id, items)
            db.loop[chat_id] = session["loop"]
            assistant_num = session["assistant_num"]
            if assistant_num and assistant_num <= len(userbot.clients):
                db.assistant[chat_id] = assistant_num
            position = max(session["position"], 0)
            if items[0].duration_sec and position >= items[0].duration_sec - 5:
                position = 0
            items[0].time = position
            restored += 1

        logger.info("Loaded %s saved playback queue(s).", restored)
        return restored

    async def run_startup(self) -> None:
        for session in self.sessions:
            if session["state"] not in {"playing", "paused"}:
                continue
            try:
                await self.play(session["chat_id"])
            except Exception:
                logger.exception(
                    "Could not restart playback for chat %s", session["chat_id"]
                )

    async def play(self, chat_id: int, source: Message | None = None) -> bool:
        """Do the same work as a fresh /play for the saved current track."""
        if await db.get_call(chat_id):
            return True

        media = queue.get_current(chat_id)
        if not media:
            return False

        _lang = await lang.get_lang(chat_id)
        status = (
            await source.reply_text(_lang["recovery_resuming"])
            if source
            else await app.send_message(chat_id, _lang["recovery_checking"])
        )
        status.lang = _lang

        from anony.helpers._play import ensure_assistant

        if not await ensure_assistant(status):
            return False

        remote_file = bool(
            media.file_path
            and media.file_path.startswith(("http://", "https://"))
        )
        if not remote_file and (
            not media.file_path or not Path(media.file_path).exists()
        ):
            if isinstance(media, Track):
                media.file_path = await yt.download(media.id, video=media.video)
            if not media.file_path:
                await status.edit_text(_lang["recovery_file_missing"])
                return False

        position = max(media.time, 0)
        media.message_id = status.id
        started = await anon.play_media(
            chat_id,
            status,
            media,
            seek_time=position,
            new_session=True,
        )
        if started:
            logger.info("Restarted saved playback for chat %s.", chat_id)
        else:
            logger.warning("Saved playback did not start for chat %s.", chat_id)
        return started


recovery = PlaybackRecovery()
