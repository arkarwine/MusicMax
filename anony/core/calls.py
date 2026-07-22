# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from os import getenv

from ntgcalls import (ConnectionNotFound, TelegramServerError,
                      RTMPStreamingUnsupported, ConnectionError)
from pyrogram import enums
from pyrogram.errors import (BadRequest, ChatSendMediaForbidden,
                             ChatSendPhotosForbidden, MessageIdInvalid)
from pyrogram.types import InputMediaPhoto, Message
from pytgcalls import PyTgCalls, exceptions, types
from pytgcalls.pytgcalls_session import PyTgCallsSession

from anony import (app, config, db, lang, logger, queue, supervisor,
                   thumb, userbot, yt)
from anony.core.audio import build_ffmpeg_parameters
from anony.helpers import Media, Track, buttons
from anony.core.play_message import (
    render_play_message,
    select_play_media,
)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int((getenv(name) or "").strip())
    except ValueError:
        return default
    return max(value, minimum)
from anony.core.rich_messages import RichMedia


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
        if not self.clients:
            return
        try:
            client = await db.get_assistant(chat_id)
        except RuntimeError:
            logger.info(
                "No active assistant is available to leave call %s", chat_id
            )
            return
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

    @staticmethod
    def _play_rich_media(
        override, artwork, placement: str | int = "before"
    ) -> RichMedia | None:
        sources = select_play_media(override, artwork)
        if len(sources) == 2:
            return RichMedia(
                list(sources),
                "photo",
                placement,
                "slideshow",
            )
        return (
            RichMedia(sources[0], "photo", placement)
            if sources else None
        )

    async def _legacy_play_card(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        text: str,
        keyboard,
        override,
        artwork,
    ) -> None:
        candidates = []
        for candidate in (override, artwork, None):
            if candidate not in candidates:
                candidates.append(candidate)

        async def deliver(*, edit: bool):
            last_error = None
            for candidate in candidates:
                try:
                    if edit and candidate:
                        return await app._legacy_edit_message_media(
                            chat_id,
                            message.id,
                            InputMediaPhoto(
                                media=candidate,
                                caption=text,
                                parse_mode=enums.ParseMode.HTML,
                            ),
                            reply_markup=keyboard,
                        )
                    if edit:
                        return await app._legacy_edit_message_text(
                            chat_id,
                            message.id,
                            text,
                            parse_mode=enums.ParseMode.HTML,
                            reply_markup=keyboard,
                        )
                    if candidate:
                        return await app._legacy_send_photo(
                            chat_id=chat_id,
                            photo=candidate,
                            caption=text,
                            parse_mode=enums.ParseMode.HTML,
                            reply_markup=keyboard,
                        )
                    return await app._legacy_send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode=enums.ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                except MessageIdInvalid:
                    raise
                except (
                    BadRequest,
                    ChatSendMediaForbidden,
                    ChatSendPhotosForbidden,
                ) as exc:
                    last_error = exc
            raise RuntimeError("Could not deliver the play card") from last_error

        try:
            sent = await deliver(edit=True)
        except MessageIdInvalid:
            sent = await deliver(edit=False)
        media.message_id = sent.id

    async def _show_play_card(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        _lang: dict,
        lang_code: str,
        _thumb,
    ) -> None:
        default_template = _lang["play_message_template"]
        template = (
            config.play_message_template(lang_code) or default_template
        )
        rendered = render_play_message(
            template,
            default_template,
            title=media.title or _lang["unknown_track"],
            url=media.url,
            duration=media.duration or "--:--",
            requester=media.user or _lang["someone"],
        )
        if rendered.used_default:
            logger.warning(
                "Custom %s /play template failed at render time; "
                "using the localized default.",
                lang_code,
            )

        keyboard = buttons.controls(chat_id, playing=True)
        artwork = _thumb if config.THUMB_GEN else None
        override_url = config.play_image_url()
        override = None
        if override_url:
            override = await thumb.play_image(override_url)
            if override is None:
                logger.warning(
                    "Could not cache PLAY_IMAGE; using its remote URL."
                )
                override = override_url
        rich_media = self._play_rich_media(
            override,
            artwork,
            rendered.media_index
            if rendered.media_index is not None else "before",
        )
        sent = await app.rich_messages.edit(
            chat_id,
            message.id,
            rendered.rich_blocks,
            media=rich_media,
            fallback_text=rendered.fallback_html,
            reply_markup=keyboard,
        )
        if sent is not None:
            media.message_id = sent.id
            return

        await self._legacy_play_card(
            chat_id,
            message,
            media,
            rendered.fallback_html,
            keyboard,
            override,
            artwork,
        )


    async def play_media(
        self,
        chat_id: int,
        message: Message,
        media: Media | Track,
        seek_time: int = 0,
        new_session: bool = False,
        artwork_task: asyncio.Task | None = None,
    ) -> bool:
        client = await db.get_assistant(chat_id)
        lang_code = await db.get_lang(chat_id)
        _lang = lang.languages.get(lang_code, lang.languages["en"])
        show_card = not seek_time or new_session
        _thumb = None
        if show_card and config.THUMB_GEN:
            if isinstance(media, Track):
                if artwork_task is None:
                    artwork_task = supervisor.spawn_once(
                        f"artwork:{chat_id}", thumb.generate(media)
                    )
            else:
                _thumb = config.DEFAULT_THUMB

        if not media.file_path:
            if artwork_task is not None and not artwork_task.done():
                artwork_task.cancel()
            await message.edit_text(_lang["error_no_file"].format(config.SUPPORT_CHAT))
            await self.play_next(chat_id)
            return False

        audio_mode = await db.get_audio_mode(chat_id)
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
            ffmpeg_parameters=build_ffmpeg_parameters(seek_time, audio_mode),
        )
        try:
            if not await db.get_call(chat_id):
                await self.reset_assistant_call(chat_id)
            await asyncio.wait_for(
                client.play(
                    chat_id=chat_id,
                    stream=stream,
                    config=types.GroupCallConfig(auto_start=False),
                ),
                timeout=_env_int("PLAYBACK_CONNECT_TIMEOUT_SECONDS", 45, 10),
            )
            if not seek_time or new_session:
                media.time = max(seek_time, 1)
                await db.add_call(chat_id)
                if artwork_task is not None:
                    _thumb = await artwork_task
                try:
                    await self._show_play_card(
                        chat_id,
                        message,
                        media,
                        _lang,
                        lang_code,
                        _thumb,
                    )
                except Exception:
                    # Playback success must not be rolled back solely because a
                    # Telegram status message could not be edited or replaced.
                    logger.exception(
                        "Playback connected but its play card failed in chat %s",
                        chat_id,
                    )

                await db.save_queue(chat_id, queue.get_queue(chat_id))
                await db.save_playback(chat_id, "playing", seek_time)
                if not new_session:
                    try:
                        await db.record_play(
                            chat_id,
                            track_id=media.id,
                            title=media.title or _lang["unknown_track"],
                            url=media.url,
                        )
                    except Exception:
                        logger.warning(
                            "Could not record playback analytics for chat %s",
                            chat_id,
                            exc_info=True,
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
        finally:
            if artwork_task is not None and not artwork_task.done():
                artwork_task.cancel()


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
            if loop > 0:
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
        failed_slots = []
        for slot, ub in list(userbot.clients.items()):
            try:
                await self.add_client(slot, ub)
            except Exception:
                failed_slots.append(slot)
                logger.exception(
                    "Voice client for assistant session %s could not start", slot
                )
        for slot in failed_slots:
            try:
                await userbot.disable_session(slot)
            except Exception:
                logger.exception(
                    "Failed to take unusable assistant session %s offline", slot
                )
        if self.clients:
            logger.info("Started %s PyTgCalls client(s).", len(self.clients))
        else:
            logger.warning(
                "No voice assistant is active; continuing in bot-only mode."
            )
