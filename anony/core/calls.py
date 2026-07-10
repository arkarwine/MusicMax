# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from html import escape

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
        self.clients: dict[int, PyTgCalls] = {}

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

    async def stop(self, chat_id: int, clear_persistence: bool = True) -> None:
        queue.clear(chat_id)
        await db.remove_call(chat_id)
        await db.set_loop(chat_id, 0)
        if clear_persistence:
            await db.clear_playback(chat_id)
        await self._leave_assistant_call(chat_id)

    async def _leave_assistant_call(self, chat_id: int) -> None:
        client = await db.get_assistant(chat_id)
        try:
            await client.leave_call(chat_id, close=False)
        except (ConnectionNotFound, exceptions.NotInCallError):
            # A new process has no local ntgcalls connection, but Telegram can
            # still contain the assistant left behind by the previous process.
            try:
                await client._app.leave_group_call(chat_id)
            except Exception:
                logger.debug(
                    "Assistant had no stale call in chat %s", chat_id,
                    exc_info=True,
                )
        except exceptions.NoActiveGroupCall:
            pass
        except Exception:
            logger.warning(
                "Could not leave the assistant call in chat %s",
                chat_id,
                exc_info=True,
            )

    async def reset_assistant_call(self, chat_id: int) -> None:
        """Clear a call connection left behind by an earlier bot process."""
        await self._leave_assistant_call(chat_id)
        await asyncio.sleep(1)

    async def exit(self) -> None:
        """Leave active calls before assistant sessions are disconnected."""
        for chat_id in list(db.active_calls):
            await db.remove_call(chat_id)
            await self._leave_assistant_call(chat_id)
        logger.info("Assistant voice calls stopped.")

    async def _show_play_card(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        _lang: dict,
        _thumb,
    ) -> None:
        text = _lang["play_media"].format(
            escape(media.url or "", quote=True),
            escape(media.title or _lang["unknown_track"]),
            escape(media.duration or "--:--"),
            media.user or _lang["someone"],
        )
        keyboard = buttons.controls(chat_id, playing=True)
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
        new_session: bool = False,
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
        try:
            if not await db.get_call(chat_id):
                await self.reset_assistant_call(chat_id)
            await client.play(
                chat_id=chat_id,
                stream=stream,
                config=types.GroupCallConfig(auto_start=False),
            )
            if not seek_time or new_session:
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
                "Playback started in chat %s at position %s.",
                chat_id,
                seek_time,
            )
            return True
        except FileNotFoundError:
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self.play_next(chat_id)
            return False
        except exceptions.NoActiveGroupCall:
            # Keep the saved queue so /resume can run the same play path later.
            await db.remove_call(chat_id)
            await db.save_queue(chat_id, queue.get_queue(chat_id))
            await db.save_playback(chat_id, "waiting", media.time)
            await message.edit_text(_lang["error_no_call"])
            return False
        except exceptions.NoAudioSourceFound:
            await message.edit_text(_lang["error_no_audio"])
            await self.play_next(chat_id)
            return False
        except (ConnectionError, ConnectionNotFound, TelegramServerError):
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
            return False
        except RTMPStreamingUnsupported:
            await self.stop(chat_id)
            await message.edit_text(_lang["error_rtmp"])
            return False
        except Exception:
            logger.exception("Playback failed in chat %s", chat_id)
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
            return False


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
        pings = [client.ping for client in self.clients.values()]
        return round(sum(pings) / len(pings), 2) if pings else 0.0


    async def decorators(self, client: PyTgCalls) -> None:
        @client.on_update()
        async def update_handler(_, update: types.Update) -> None:
            if isinstance(update, types.StreamEnded):
                if update.stream_type == types.StreamEnded.Type.AUDIO:
                    if not await db.get_call(update.chat_id):
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


    async def add_client(self, slot: int, ub) -> PyTgCalls:
        if slot in self.clients:
            return self.clients[slot]
        client = PyTgCalls(ub, cache_duration=100)
        await client.start()
        self.clients[slot] = client
        await self.decorators(client)
        return client

    async def boot(self) -> None:
        PyTgCallsSession.notice_displayed = True
        for slot, ub in userbot.clients.items():
            await self.add_client(slot, ub)
        logger.info("PyTgCalls client(s) started.")
