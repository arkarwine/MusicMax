# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from os import getenv

from pyrogram import enums
from pyrogram.errors import (BadRequest, ChatSendMediaForbidden,
                             ChatSendPhotosForbidden, MessageIdInvalid)
from pyrogram.types import InputMediaPhoto, Message

from anony import (app, config, db, lang, logger, queue, supervisor,
                   thumb, userbot, yt)
from anony.core.voice_worker import (
    VoiceWorkerClient,
    VoiceWorkerError,
)
from anony.helpers import Media, Track, buttons
from anony.core.play_message import (
    render_play_message,
)


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        value = int((getenv(name) or "").strip())
    except ValueError:
        return default
    return max(value, minimum)
class TgCall:
    def __init__(self):
        self.clients: dict[int, VoiceWorkerClient] = {}
        self._client_locks: dict[int, asyncio.Lock] = {}
        self._restart_tasks: dict[int, asyncio.Task] = {}

    async def _peer_payload(self, chat_id: int) -> dict | None:
        slot = db.assistant.get(chat_id)
        assistant = userbot.clients.get(slot) if slot is not None else None
        if assistant is None:
            return None
        try:
            peer = await assistant.resolve_peer(chat_id)
        except Exception:
            logger.warning(
                "Could not resolve chat %s for voice worker %s",
                chat_id,
                slot,
                exc_info=True,
            )
            return None
        return {
            "id": chat_id,
            "access_hash": int(getattr(peer, "access_hash", 0) or 0),
            "type": (
                "supergroup"
                if str(chat_id).startswith("-100")
                else "group"
            ),
        }

    async def pause(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        result = await client.pause(
            chat_id,
            peer=await self._peer_payload(chat_id),
        )
        await db.playing(chat_id, paused=True)
        return result

    async def resume(self, chat_id: int) -> bool:
        client = await db.get_assistant(chat_id)
        result = await client.resume(
            chat_id,
            peer=await self._peer_payload(chat_id),
        )
        await db.playing(chat_id, paused=False)
        return result

    async def stop(self, chat_id: int, clear_persistence: bool = True) -> None:
        slot = db.assistant.get(chat_id)
        queue.clear(chat_id)
        await db.remove_call(chat_id)
        await db.set_loop(chat_id, 0)
        if clear_persistence:
            await db.clear_playback(chat_id)
        await self._leave_assistant_call(chat_id)
        if slot is not None:
            await userbot.finish_draining(slot)

    async def _leave_assistant_call(self, chat_id: int) -> None:
        if not self.clients:
            return
        assigned = db.assistant.get(chat_id)
        client = self.clients.get(assigned) if assigned is not None else None
        if client is None:
            if assigned is not None:
                logger.info(
                    "Voice worker %s is unavailable while leaving call %s",
                    assigned,
                    chat_id,
                )
                return
            try:
                client = await db.get_assistant(chat_id)
            except RuntimeError:
                logger.info(
                    "No active assistant is available to leave call %s",
                    chat_id,
                )
                return
        try:
            await client.leave_call(
                chat_id,
                close=False,
                peer=await self._peer_payload(chat_id),
            )
        except VoiceWorkerError as exc:
            if exc.remote_type in {
                "ConnectionNotFound",
                "NotInCallError",
                "NoActiveGroupCall",
            }:
                return
            logger.warning(
                "Could not leave the assistant call in chat %s: %s",
                chat_id,
                exc,
            )
        except Exception:
            logger.warning(
                "Could not leave the assistant call in chat %s",
                chat_id,
                exc_info=True,
            )

    async def reset_assistant_call(self, chat_id: int) -> None:
        """Clear a call connection left behind by an earlier bot process."""
        await self._leave_assistant_call(chat_id)
        # Telegram only needs a short scheduling turn after a stale call is
        # explicitly left. Healthy starts no longer take this recovery path.
        await asyncio.sleep(0.5)

    async def exit(self) -> None:
        """Leave active calls before assistant sessions are disconnected."""
        for chat_id in list(db.active_calls):
            await db.remove_call(chat_id)
            await self._leave_assistant_call(chat_id)
        workers = list(self.clients.items())
        self.clients.clear()
        for task in tuple(self._restart_tasks.values()):
            task.cancel()
        self._restart_tasks.clear()
        if workers:
            await asyncio.gather(
                *(worker.stop() for _, worker in workers),
                return_exceptions=True,
            )
        logger.info("Assistant voice workers stopped.")

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
        for candidate in (artwork, override):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        candidates.append(None)

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
        # A real generated cover wins. PLAY_IMAGE is the next fallback, and
        # DEFAULT_THUMB is used only when neither is available.
        artwork = (
            _thumb
            if config.THUMB_GEN
            and _thumb
            and _thumb != config.DEFAULT_THUMB
            else None
        )
        override = None
        # PLAY_IMAGE is a placeholder, not a second slide. Avoid resolving or
        # uploading it after generated artwork is ready.
        if artwork is None:
            override_url = config.play_image_url()
            if override_url:
                override = await thumb.play_image(override_url)
                if override is None:
                    logger.warning(
                        "Could not cache PLAY_IMAGE; using its remote URL."
                    )
                    override = override_url
            if override is None and _thumb:
                override = _thumb
        # Telegram rich paragraph blocks collapse whitespace on some clients.
        # Standard captions preserve the template's real newline characters
        # and avoid a slow rich-to-standard retry.
        await self._legacy_play_card(
            chat_id,
            message,
            media,
            rendered.fallback_html,
            keyboard,
            override,
            artwork,
        )

    async def _refresh_play_card_artwork(
        self,
        chat_id: int,
        message_id: int,
        media: Media | Track,
        _lang: dict,
        lang_code: str,
        artwork_task: asyncio.Task,
    ) -> None:
        try:
            artwork = await artwork_task
            if not artwork:
                return
            current = queue.get_current(chat_id)
            if current is None or getattr(current, "id", None) != getattr(
                media, "id", None
            ):
                return
            if not await db.get_call(chat_id):
                return
            card_id = getattr(media, "message_id", 0) or message_id
            if not card_id:
                return
            message = await app.get_messages(chat_id, card_id)
            if not message:
                return
            await self._show_play_card(
                chat_id,
                message,
                media,
                _lang,
                lang_code,
                artwork,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "Could not refresh play card artwork in chat %s",
                chat_id,
                exc_info=True,
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
        lang_code = await db.get_lang(chat_id)
        _lang = lang.languages.get(lang_code, lang.languages["en"])
        assigned = db.assistant.get(chat_id)
        if (
            assigned is not None
            and not userbot.is_accepting(assigned)
        ):
            await message.edit_text(_lang["play_session_locked"])
            return False
        client = await db.get_assistant(chat_id)
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

        artwork_handed_off = False

        async def connect() -> None:
            await client.play(
                chat_id=chat_id,
                media_path=media.file_path,
                video=media.video,
                audio_quality=config.AUDIO_QUALITY,
                video_quality=config.VIDEO_QUALITY,
                video_fps=config.VIDEO_FPS,
                ffmpeg_parameters=(
                    f"-ss {seek_time}" if seek_time > 1 else None
                ),
                peer=await self._peer_payload(chat_id),
                timeout=_env_int(
                    "PLAYBACK_CONNECT_TIMEOUT_SECONDS",
                    45,
                    10,
                ),
            )

        try:
            try:
                await connect()
            except VoiceWorkerError as exc:
                if (
                    not await db.get_call(chat_id)
                    and exc.remote_type in {
                        "ConnectionNotFound",
                        "NotInCallError",
                    }
                ):
                    logger.info(
                        "Clearing a stale assistant call in chat %s.",
                        chat_id,
                    )
                    await self.reset_assistant_call(chat_id)
                    await connect()
                else:
                    raise
            if not seek_time or new_session:
                media.time = max(seek_time, 1)
                await db.add_call(chat_id)
                refresh_artwork = False
                if artwork_task is not None:
                    if artwork_task.done():
                        try:
                            _thumb = artwork_task.result()
                        except Exception:
                            logger.debug(
                                "Generated artwork is unavailable for chat %s",
                                chat_id,
                                exc_info=True,
                            )
                            _thumb = None
                    else:
                        try:
                            _thumb = await asyncio.wait_for(
                                asyncio.shield(artwork_task),
                                timeout=0.8,
                            )
                        except asyncio.TimeoutError:
                            refresh_artwork = True
                            if _thumb is None:
                                _thumb = config.DEFAULT_THUMB
                        except Exception:
                            logger.debug(
                                "Generated artwork is unavailable for chat %s",
                                chat_id,
                                exc_info=True,
                            )
                            _thumb = None
                try:
                    await self._show_play_card(
                        chat_id,
                        message,
                        media,
                        _lang,
                        lang_code,
                        _thumb,
                    )
                    if refresh_artwork:
                        artwork_handed_off = True
                        supervisor.spawn_once(
                            f"play-card-artwork:{chat_id}",
                            self._refresh_play_card_artwork(
                                chat_id,
                                message.id,
                                media,
                                _lang,
                                lang_code,
                                artwork_task,
                            ),
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
        except VoiceWorkerError as exc:
            if exc.remote_type == "FileNotFoundError":
                await message.edit_text(
                    _lang["error_no_file"].format(config.SUPPORT_CHAT)
                )
                await self.play_next(chat_id)
                return False
            if exc.remote_type == "NoActiveGroupCall":
                # Keep the saved queue so /resume can run the same play path.
                await db.remove_call(chat_id)
                await db.save_queue(chat_id, queue.get_queue(chat_id))
                await db.save_playback(chat_id, "waiting", media.time)
                await message.edit_text(_lang["error_no_call"])
                return False
            if exc.remote_type == "NoAudioSourceFound":
                await message.edit_text(_lang["error_no_audio"])
                await self.play_next(chat_id)
                return False
            if exc.remote_type == "RTMPStreamingUnsupported":
                await self.stop(chat_id)
                await message.edit_text(_lang["error_rtmp"])
                return False
            logger.error(
                "Voice worker failed playback in chat %s: %s",
                chat_id,
                exc,
            )
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
            return False
        except Exception:
            logger.exception("Playback failed in chat %s", chat_id)
            await self.stop(chat_id)
            await message.edit_text(_lang["error_tg_server"])
            return False
        finally:
            if (
                not artwork_handed_off
                and artwork_task is not None
                and not artwork_task.done()
            ):
                artwork_task.cancel()


    async def replay(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return
        assigned = db.assistant.get(chat_id)
        if assigned is not None and not userbot.is_accepting(assigned):
            return await self.stop(chat_id)

        media = queue.get_current(chat_id)
        if not media:
            return await self.stop(chat_id)
        _lang = await lang.get_lang(chat_id)
        msg = await app.send_message(chat_id=chat_id, text=_lang["play_again"])
        media.message_id = msg.id
        await self.play_media(chat_id, msg, media)


    async def play_next(self, chat_id: int) -> None:
        assigned = db.assistant.get(chat_id)
        if assigned is not None and not userbot.is_accepting(assigned):
            logger.info(
                "Playback drain completed for assistant %s in chat %s",
                assigned,
                chat_id,
            )
            return await self.stop(chat_id)

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
        if not self.clients:
            return 0.0
        results = await asyncio.gather(
            *(client.measure_ping() for client in self.clients.values()),
            return_exceptions=True,
        )
        pings = [
            value
            for value in results
            if isinstance(value, (int, float))
        ]
        return round(sum(pings) / len(pings), 2) if pings else 0.0

    async def participant_count(self, chat_id: int) -> int:
        client = await db.get_assistant(chat_id)
        return await client.get_participant_count(
            chat_id,
            peer=await self._peer_payload(chat_id),
        )

    def _on_worker_event(
        self,
        slot: int,
        worker: VoiceWorkerClient,
        event: dict,
    ) -> None:
        name = event.get("event")
        chat_id = int(event.get("chat_id") or 0)
        if name == "stream_ended" and chat_id:
            supervisor.spawn_once(
                f"voice-ended:{chat_id}",
                self._handle_stream_ended(chat_id),
            )
            return
        if name == "call_closed" and chat_id:
            supervisor.spawn_once(
                f"voice-closed:{chat_id}",
                self.stop(chat_id),
            )
            return
        if name != "worker_exit" or self.clients.get(slot) is not worker:
            return

        self.clients.pop(slot, None)
        logger.error(
            "Voice worker %s exited unexpectedly (pid=%s, code=%s)",
            slot,
            event.get("pid"),
            event.get("returncode"),
        )
        running = self._restart_tasks.get(slot)
        if running is not None and not running.done():
            return
        task = supervisor.spawn_once(
            f"voice-worker-recovery:{slot}",
            self._recover_worker(slot),
        )
        self._restart_tasks[slot] = task
        task.add_done_callback(
            lambda done, worker_slot=slot: self._restart_tasks.pop(
                worker_slot,
                None,
            )
        )

    async def _handle_stream_ended(self, chat_id: int) -> None:
        if not await db.get_call(chat_id):
            return
        logger.info("Audio stream ended in chat %s", chat_id)
        await self.play_next(chat_id)

    async def _recover_worker(self, slot: int) -> None:
        affected = []
        for chat_id in db.active_chats_for_assistant(slot):
            playing = await db.playing(chat_id)
            media = queue.get_current(chat_id)
            affected.append((chat_id, playing and media is not None))
            await db.remove_call(chat_id)
            if media is not None:
                await db.save_queue(chat_id, queue.get_queue(chat_id))
                await db.save_playback(chat_id, "waiting", media.time)

        attempts = 0
        while slot in userbot.clients and not supervisor.closing:
            session = await db.get_assistant_session(slot)
            if not session or not session["enabled"]:
                await userbot.finish_draining(slot)
                return
            delay = (1, 5, 30, 60)[min(attempts, 3)]
            await asyncio.sleep(delay)
            session = await db.get_assistant_session(slot)
            if (
                slot not in userbot.clients
                or not session
                or not session["enabled"]
            ):
                return
            try:
                await self.add_client(slot, userbot.clients[slot])
            except asyncio.CancelledError:
                raise
            except Exception:
                attempts += 1
                logger.exception(
                    "Voice worker %s restart attempt %s failed",
                    slot,
                    attempts,
                )
                continue
            logger.info(
                "Voice worker %s recovered after %s attempt(s)",
                slot,
                attempts + 1,
            )
            break
        else:
            return

        if affected:
            from anony.core.recovery import recovery

            for chat_id, was_playing in affected:
                if not was_playing:
                    continue
                try:
                    await recovery.play(chat_id)
                except Exception:
                    logger.exception(
                        "Could not restore chat %s after voice worker recovery",
                        chat_id,
                    )

    async def add_client(
        self,
        slot: int,
        ub,
    ) -> VoiceWorkerClient:
        del ub
        lock = self._client_locks.setdefault(slot, asyncio.Lock())
        async with lock:
            current = self.clients.get(slot)
            if current is not None and current.is_alive:
                return current
            if current is not None:
                self.clients.pop(slot, None)
                await current.stop()

            session = await db.get_assistant_session(slot)
            if not session:
                raise RuntimeError(f"Assistant session {slot} is unavailable")
            worker = VoiceWorkerClient(
                slot=slot,
                session_string=session["session_string"],
                api_id=config.API_ID,
                api_hash=config.API_HASH,
                logger=logger,
            )
            worker.set_event_handler(
                lambda event, current=worker: self._on_worker_event(
                    current.slot,
                    current,
                    event,
                )
            )
            try:
                await worker.start()
            except Exception:
                await worker.stop()
                raise
            self.clients[slot] = worker
            return worker

    def remap_slots(self, mapping: dict[int, int]) -> None:
        """Apply compact public session IDs to worker proxies."""
        self.clients = {
            mapping.get(slot, slot): worker
            for slot, worker in self.clients.items()
        }
        self._client_locks = {
            mapping.get(slot, slot): lock
            for slot, lock in self._client_locks.items()
        }
        for slot, worker in self.clients.items():
            worker.relabel(slot)
        for old_slot, task in tuple(self._restart_tasks.items()):
            new_slot = mapping.get(old_slot, old_slot)
            if new_slot == old_slot:
                continue
            task.cancel()
            self._restart_tasks.pop(old_slot, None)

    async def boot(self) -> None:
        startup_limit = asyncio.Semaphore(4)

        async def start_worker(slot, ub):
            try:
                async with startup_limit:
                    await self.add_client(slot, ub)
                return None
            except Exception:
                logger.exception(
                    "Voice client for assistant session %s could not start", slot
                )
                return slot

        failed_slots = [
            slot
            for slot in await asyncio.gather(*(
                start_worker(slot, ub)
                for slot, ub in list(userbot.clients.items())
            ))
            if slot is not None
        ]
        for slot in failed_slots:
            # A voice-worker startup failure is transient and must not disable
            # an otherwise valid Telegram assistant session. Keep the account
            # available and recover the isolated voice process in background.
            running = self._restart_tasks.get(slot)
            if running is not None and not running.done():
                continue
            task = supervisor.spawn_once(
                f"voice-worker-recovery:{slot}",
                self._recover_worker(slot),
            )
            self._restart_tasks[slot] = task
            task.add_done_callback(
                lambda done, worker_slot=slot: self._restart_tasks.pop(
                    worker_slot,
                    None,
                )
            )
        if self.clients:
            logger.info(
                "Started %s isolated voice worker(s): "
                "audio=%s, video=%s/%sfps.",
                len(self.clients),
                config.AUDIO_QUALITY,
                config.VIDEO_QUALITY,
                config.VIDEO_FPS,
            )
        else:
            logger.warning(
                "No voice assistant is active; continuing in bot-only mode."
            )
