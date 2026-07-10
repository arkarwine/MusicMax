# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from dataclasses import fields
from pathlib import Path

from pyrogram.types import Message

from anony import anon, app, db, lang, logger, queue, userbot, yt
from anony.helpers import Media, Track


class PlaybackRecovery:
    """Restore queues first, then reconnect playback as an observable workflow."""

    def __init__(self) -> None:
        self._startup_sessions: list[dict] = []
        self._locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def _restore_item(item: dict) -> Media | Track:
        cls = Track if item["type"] == "track" else Media
        allowed = {field.name for field in fields(cls)}
        payload = {
            key: value for key, value in item["payload"].items() if key in allowed
        }
        return cls(**payload)

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def restore_queues(self) -> int:
        """Load durable queues without making Telegram calls during boot."""
        self._startup_sessions = await db.get_recovery_sessions()
        restored = 0
        for session in self._startup_sessions:
            chat_id = session["chat_id"]
            try:
                items = [self._restore_item(item) for item in session["items"]]
            except Exception as exc:
                logger.exception("Could not decode saved queue for chat %s", chat_id)
                await db.set_recovery_status(
                    chat_id,
                    "queue_decode_failed",
                    f"{type(exc).__name__}: {exc}",
                )
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
            media = items[0]
            if media.duration_sec and position >= media.duration_sec - 5:
                position = 0
            media.time = position
            session["position"] = position
            restored += 1
            if not await db.get_recovery_status(chat_id):
                await db.set_recovery_status(
                    chat_id, "queue_loaded", session["state"]
                )

        logger.info("Loaded %s persisted playback queue(s).", restored)
        return restored

    async def run_startup(self, delay: float = 4.0) -> None:
        """Reconnect active sessions after all clients and handlers have settled."""
        active = [
            session
            for session in self._startup_sessions
            if session["state"] in {"playing", "paused"}
            and queue.get_current(session["chat_id"])
        ]
        if not active:
            logger.info("No active playback sessions require startup recovery.")
            return

        logger.info(
            "Playback recovery scheduled for %s chat(s) in %.1f seconds.",
            len(active),
            delay,
        )
        await asyncio.sleep(delay)
        for session in active:
            chat_id = session["chat_id"]
            try:
                await self.recover(
                    chat_id,
                    desired_state=session["state"],
                    position=session["position"],
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Recovery coordinator failed for chat %s", chat_id)
                await db.save_playback(
                    chat_id, session["state"], session["position"]
                )
                await db.set_recovery_status(
                    chat_id,
                    "coordinator_failed",
                    f"{type(exc).__name__}: {exc}",
                )

    @staticmethod
    async def _file_ready(media: Media | Track, redownload: bool = False) -> bool:
        remote_file = bool(
            media.file_path
            and media.file_path.startswith(("http://", "https://"))
        )
        local_ready = bool(media.file_path and Path(media.file_path).exists())
        if not redownload and (remote_file or local_ready):
            return True
        if isinstance(media, Track):
            media.file_path = await yt.download(media.id, video=media.video)
        return bool(media.file_path)

    async def recover(
        self,
        chat_id: int,
        source: Message | None = None,
        desired_state: str = "playing",
        position: int | None = None,
    ) -> bool:
        """Reconnect one queue, retry safely, and retain a useful failure reason."""
        async with self._lock(chat_id):
            if await db.get_call(chat_id):
                logger.info("Recovery skipped; chat %s is already connected.", chat_id)
                return True

            media = queue.get_current(chat_id)
            if not media:
                await db.set_recovery_status(chat_id, "empty_queue", "nothing to recover")
                return False

            _lang = await lang.get_lang(chat_id)
            position = max(media.time if position is None else position, 0)
            status = (
                await source.reply_text(_lang["recovery_resuming"])
                if source
                else await app.send_message(chat_id, _lang["recovery_checking"])
            )
            status.lang = _lang
            await db.set_recovery_status(chat_id, "checking_assistant")
            logger.info(
                "Playback recovery started for chat %s at position %s (%s).",
                chat_id,
                position,
                desired_state,
            )

            # Imported here to avoid coupling normal startup imports to command helpers.
            from anony.helpers._play import ensure_assistant

            if not await ensure_assistant(status):
                # Keep the desired durable state so a later process restart can
                # retry automatically instead of permanently downgrading it.
                await db.save_playback(chat_id, desired_state, position)
                await db.set_recovery_status(
                    chat_id, "assistant_unavailable", "membership check failed"
                )
                try:
                    await status.edit_text(_lang["recovery_assistant_failed"])
                except Exception:
                    pass
                return False

            # A stored seek can be stale after a fresh download. Try it first,
            # then start safely from zero, then refresh YouTube media entirely.
            attempts = [
                (position, False, "saved_position"),
                (0, False, "safe_start"),
                (0, True, "fresh_file"),
            ]
            last_detail = "connection_not_started"
            attempts_made = 0
            for attempt, (seek_time, redownload, strategy) in enumerate(attempts, 1):
                if redownload and not isinstance(media, Track):
                    continue
                attempts_made += 1
                await db.set_recovery_status(
                    chat_id, "preparing", strategy, attempt
                )
                logger.info(
                    "Playback recovery attempt %s/3 for chat %s "
                    "(strategy=%s, seek=%s, file=%s).",
                    attempt,
                    chat_id,
                    strategy,
                    seek_time,
                    media.file_path or "missing",
                )

                try:
                    ready = await self._file_ready(media, redownload=redownload)
                except Exception as exc:
                    ready = False
                    last_detail = f"download:{type(exc).__name__}: {exc}"
                    logger.exception(
                        "Media preparation failed during recovery for chat %s",
                        chat_id,
                    )
                if not ready:
                    if not last_detail.startswith("download:"):
                        last_detail = "media_file_unavailable"
                    await db.set_recovery_status(
                        chat_id, "retrying", last_detail, attempts_made
                    )
                    logger.warning(
                        "Recovery media is unavailable for chat %s "
                        "(strategy=%s).",
                        chat_id,
                        strategy,
                    )
                    continue

                await db.save_queue(chat_id, queue.get_queue(chat_id))
                await db.set_recovery_status(
                    chat_id, "connecting", strategy, attempt
                )
                media.message_id = status.id
                try:
                    connected = await anon.play_media(
                        chat_id,
                        status,
                        media,
                        seek_time=seek_time,
                        recovering=True,
                    )
                except Exception as exc:
                    connected = False
                    last_detail = f"attempt:{type(exc).__name__}: {exc}"
                    anon.connection_errors[chat_id] = last_detail
                    logger.exception(
                        "Unexpected recovery attempt failure for chat %s",
                        chat_id,
                    )
                if connected:
                    paused = desired_state == "paused"
                    if paused and not await anon.wait_for_state(chat_id, paused=True):
                        last_detail = "pause_state_not_restored"
                        await db.set_recovery_status(
                            chat_id, "connected_playing", last_detail, attempt
                        )
                        logger.warning(
                            "Chat %s reconnected but its paused state was not restored.",
                            chat_id,
                        )
                    else:
                        await db.set_recovery_status(
                            chat_id,
                            "paused" if paused else "playing",
                            f"verified via {strategy}",
                            attempt,
                        )
                    logger.info(
                        "Playback recovery completed for chat %s on attempt %s.",
                        chat_id,
                        attempt,
                    )
                    return True

                last_detail = anon.connection_errors.get(
                    chat_id, "native_connection_not_found"
                )
                await db.set_recovery_status(
                    chat_id, "retrying", last_detail, attempt
                )
                await anon.discard_failed_connection(chat_id)
                if attempt < len(attempts):
                    await asyncio.sleep(2)

            await db.save_playback(chat_id, desired_state, position)
            await db.set_recovery_status(
                chat_id, "waiting", last_detail, attempts_made
            )
            logger.error(
                "Playback recovery exhausted all attempts for chat %s: %s",
                chat_id,
                last_detail,
            )
            text = (
                _lang["recovery_call_unavailable"]
                if last_detail.startswith("no_active_video_chat")
                else _lang["recovery_failed"]
            )
            try:
                await status.edit_text(text)
            except Exception:
                logger.warning(
                    "Could not update failed recovery message in chat %s",
                    chat_id,
                    exc_info=True,
                )
            return False


recovery = PlaybackRecovery()
