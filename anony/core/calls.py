# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio

from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported, ConnectionError)
from pyrogram.errors import (ChatSendMediaForbidden, ChatSendPhotosForbidden,
                             MessageIdInvalid)
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from anony import (app, config, db, lang, logger,
                   queue, thumb, userbot, yt)
from anony.helpers import Media, Track, buttons


class TgCall(PyTgCalls):
    def __init__(self):
        self.clients = []
        self.recovering: set[int] = set()
        self.recovery_stream_ended: set[int] = set()
        self.connection_errors: dict[int, str] = {}

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        result = await client.pause(chat_id)
        await db.playing(chat_id, paused=True)
        return result

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        result = await client.resume(chat_id)
        await db.playing(chat_id, paused=False)
        return result

    async def wait_for_state(
        self,
        chat_id: int,
        paused: bool,
        attempts: int = 10,
    ) -> bool:
        """Apply a recovered state after the native call connection is ready."""
        client = await db.get_assistant(chat_id)
        operation = client.pause if paused else client.resume
        for attempt in range(attempts):
            try:
                await operation(chat_id)
                await db.playing(chat_id, paused=paused)
                return True
            except (ConnectionNotFound, exceptions.NotInCallError):
                if attempt + 1 < attempts:
                    await asyncio.sleep(1)
            except Exception:
                logger.warning(
                    "Could not apply recovered playback state in chat %s",
                    chat_id,
                    exc_info=True,
                )
                return False
        logger.warning(
            "Recovered call connection did not become ready in chat %s", chat_id
        )
        return False

    async def stop(self, chat_id: int, clear_persistence: bool = True) -> None:
        client = await db.get_assistant(chat_id)
        queue.clear(chat_id)
        await db.remove_call(chat_id)
        await db.set_loop(chat_id, 0)
        if clear_persistence:
            await db.clear_playback(chat_id)

        try:
            await client.leave_call(chat_id, close=False)
        except Exception:
            pass

    async def _native_call_ids(self, client) -> set[int]:
        """Return ntgcalls connections, the source of truth for actual playback."""
        calls = await client._binding.calls()
        return set(calls)

    async def _wait_for_native_connection(
        self,
        client,
        chat_id: int,
        recovering: bool,
    ) -> bool:
        for _ in range(10):
            if chat_id in self.recovery_stream_ended:
                self.connection_errors[chat_id] = "stream_ended_during_connect"
                return False
            try:
                connected = chat_id in await self._native_call_ids(client)
            except Exception as exc:
                self.connection_errors[chat_id] = (
                    f"native_connection_check:{type(exc).__name__}: {exc}"
                )
                logger.warning(
                    "Native call check failed for chat %s", chat_id, exc_info=True
                )
                return False
            if connected:
                # Restored media is allowed a short settling period. This catches
                # a bad seek/file that ntgcalls accepts and immediately ends.
                await asyncio.sleep(1.5 if recovering else 0.15)
                if chat_id in self.recovery_stream_ended:
                    self.connection_errors[chat_id] = "stream_ended_during_connect"
                    return False
                return chat_id in await self._native_call_ids(client)
            await asyncio.sleep(0.4)

        self.connection_errors[chat_id] = "native_connection_not_found"
        return False

    async def _failed_recovery(
        self,
        chat_id: int,
        code: str,
        exc: Exception | None = None,
    ) -> bool:
        detail = code
        if exc is not None:
            detail = f"{code}:{type(exc).__name__}: {exc}"
        self.connection_errors[chat_id] = detail
        await db.remove_call(chat_id)
        logger.warning(
            "Playback recovery connection failed in chat %s: %s",
            chat_id,
            detail,
            exc_info=exc is not None,
        )
        return False

    async def discard_failed_connection(self, chat_id: int) -> None:
        """Remove a partial native connection without touching the saved queue."""
        client = await db.get_assistant(chat_id)
        try:
            if chat_id in await self._native_call_ids(client):
                await client.leave_call(chat_id, close=False)
        except Exception:
            logger.debug(
                "No partial recovery connection to discard in chat %s",
                chat_id,
                exc_info=True,
            )
        await db.remove_call(chat_id)

    async def _show_play_card(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        _lang: dict,
        _thumb,
    ) -> None:
        text = _lang["play_media"].format(
            media.url,
            media.title,
            media.duration,
            media.user,
        )
        keyboard = buttons.controls(chat_id)
        try:
            if _thumb:
                await message.edit_media(
                    media=InputMediaPhoto(media=_thumb, caption=text),
                    reply_markup=keyboard,
                )
            else:
                await message.edit_text(text, reply_markup=keyboard)
        except (ChatSendMediaForbidden, ChatSendPhotosForbidden):
            sent = await app.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
            )
            media.message_id = sent.id
        except MessageIdInvalid:
            try:
                sent = (
                    await app.send_photo(
                        chat_id=chat_id,
                        photo=_thumb,
                        caption=text,
                        reply_markup=keyboard,
                    )
                    if _thumb
                    else await app.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=keyboard,
                    )
                )
            except (ChatSendMediaForbidden, ChatSendPhotosForbidden):
                sent = await app.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                )
            media.message_id = sent.id


    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
        recovering: bool = False,
    ) -> bool:
        client = await db.get_assistant(chat_id)
        _lang = await lang.get_lang(chat_id)
        _thumb = (
            await thumb.generate(media)
            if isinstance(media, Track)
            else config.DEFAULT_THUMB
        ) if config.THUMB_GEN else None

        if not media.file_path:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            if recovering:
                return await self._failed_recovery(chat_id, "file_missing")
            await self.play_next(chat_id)
            return False

        stream = types.MediaStream(
            media_path=media.file_path,
            audio_parameters=types.AudioQuality.HIGH,
            video_parameters=types.VideoQuality.HD_720p,
            audio_flags=types.MediaStream.Flags.REQUIRED,
            video_flags=(
                types.MediaStream.Flags.AUTO_DETECT
                if media.video
                else types.MediaStream.Flags.IGNORE
            ),
            ffmpeg_parameters=f"-ss {seek_time}" if seek_time > 1 else None,
        )
        if recovering:
            self.recovering.add(chat_id)
            self.recovery_stream_ended.discard(chat_id)
            self.connection_errors.pop(chat_id, None)
        try:
            await client.play(
                chat_id=chat_id,
                stream=stream,
                config=types.GroupCallConfig(auto_start=False),
            )
            if not await self._wait_for_native_connection(
                client, chat_id, recovering=recovering
            ):
                if recovering:
                    return await self._failed_recovery(
                        chat_id,
                        self.connection_errors.get(
                            chat_id, "native_connection_not_found"
                        ),
                    )
                await self.stop(chat_id)
                await message.edit_text(_lang["error_tg_server"])
                return False
            if not seek_time or recovering:
                media.time = max(seek_time, 1)
                await db.add_call(chat_id)
                await db.save_queue(chat_id, queue.get_queue(chat_id))
                await db.save_playback(chat_id, "playing", seek_time)
                try:
                    await self._show_play_card(
                        chat_id, message, media, _lang, _thumb
                    )
                except Exception:
                    # Playback success must not be rolled back solely because a
                    # Telegram status message could not be edited or replaced.
                    logger.exception(
                        "Playback connected but its play card failed in chat %s",
                        chat_id,
                    )
            logger.info(
                "Playback connection verified in chat %s (recovery=%s, position=%s)",
                chat_id,
                recovering,
                seek_time,
            )
            return True
        except FileNotFoundError as exc:
            if recovering:
                return await self._failed_recovery(chat_id, "file_not_found", exc)
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self.play_next(chat_id)
            return False
        except exceptions.NoActiveGroupCall as exc:
            if recovering:
                return await self._failed_recovery(
                    chat_id, "no_active_video_chat", exc
                )
            else:
                await self.stop(chat_id)
                await message.edit_text(_lang["error_no_call"])
            return False
        except exceptions.NoAudioSourceFound as exc:
            if recovering:
                return await self._failed_recovery(chat_id, "no_audio_source", exc)
            await message.edit_text(_lang["error_no_audio"])
            await self.play_next(chat_id)
            return False
        except (ConnectionError, ConnectionNotFound, TelegramServerError) as exc:
            if recovering:
                return await self._failed_recovery(
                    chat_id, "telegram_connection_error", exc
                )
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
            return False
        except RTMPStreamingUnsupported as exc:
            if recovering:
                return await self._failed_recovery(chat_id, "rtmp_unsupported", exc)
            await self.stop(chat_id)
            await message.edit_text(_lang["error_rtmp"])
            return False
        except Exception as exc:
            if recovering:
                return await self._failed_recovery(
                    chat_id, "unexpected_connection_error", exc
                )
            logger.exception("Playback failed in chat %s", chat_id)
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
            return False
        finally:
            if recovering:
                self.recovering.discard(chat_id)


    async def replay(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return

        media = queue.get_current(chat_id)
        if not media:
            return await self.stop(chat_id)
        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)


    async def play_next(self, chat_id: int) -> None:
        if loop := await db.get_loop(chat_id):
            await db.set_loop(chat_id, loop - 1)
            return await self.replay(chat_id)

        media = queue.get_next(chat_id)
        if not media:
            return await self.stop(chat_id)
        await db.save_queue(chat_id, queue.get_queue(chat_id))

        try:
            if media.message_id:
                await app.delete_messages(
                    chat_id=chat_id,
                    message_ids=media.message_id,
                    revoke=True,
                )
                media.message_id = 0
        except Exception:
            pass

        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_next"])
        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
            if not media.file_path:
                await self.play_next(chat_id)
                return await msg.edit_text(
                    _lang["error_no_file"].format(config.SUPPORT_CHAT)
                )

        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)


    async def ping(self) -> float:
        pings = [client.ping for client in self.clients]
        return round(sum(pings) / len(pings), 2) if pings else 0.0


    async def decorators(self, client: PyTgCalls) -> None:
        @client.on_update()
        async def update_handler(_, update: types.Update) -> None:
            if isinstance(update, types.StreamEnded):
                if update.stream_type == types.StreamEnded.Type.AUDIO:
                    if update.chat_id in self.recovering:
                        self.recovery_stream_ended.add(update.chat_id)
                        logger.warning(
                            "Restored stream ended before recovery completed in chat %s",
                            update.chat_id,
                        )
                        return
                    logger.info("Audio stream ended in chat %s", update.chat_id)
                    await self.play_next(update.chat_id)
            elif isinstance(update, types.ChatUpdate):
                if update.status in [
                    types.ChatUpdate.Status.KICKED,
                    types.ChatUpdate.Status.LEFT_GROUP,
                    types.ChatUpdate.Status.CLOSED_VOICE_CHAT,
                ]:
                    await self.stop(update.chat_id)


    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for ub in userbot.clients:
            client = PyTgCalls(ub, cache_duration=100)
            await client.start()
            self.clients.append(client)
            await self.decorators(client)
        logger.info("PyTgCalls client(s) started.")
