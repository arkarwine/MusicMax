# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
import signal
import importlib
from dataclasses import fields
from contextlib import suppress
from pathlib import Path

from anony import (anon, app, config, db, lang, logger, queue,
                   stop, thumb, userbot, yt)
from anony.helpers import Media, Track
from anony.plugins import all_modules


async def idle():
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGABRT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)
    await stop_event.wait()


def _restore_item(item: dict) -> Media | Track:
    cls = Track if item["type"] == "track" else Media
    allowed = {field.name for field in fields(cls)}
    payload = {key: value for key, value in item["payload"].items() if key in allowed}
    return cls(**payload)


async def restore_playback() -> None:
    restored = 0
    for session in await db.get_recovery_sessions():
        chat_id = session["chat_id"]
        items = [_restore_item(item) for item in session["items"]]
        if not items:
            await db.clear_playback(chat_id)
            continue

        queue.restore(chat_id, items)
        db.loop[chat_id] = session["loop"]
        assistant_num = session["assistant_num"]
        if assistant_num and assistant_num <= len(userbot.clients):
            db.assistant[chat_id] = assistant_num

        media = items[0]
        media.time = session["position"]
        restored += 1
        if session["state"] == "waiting":
            continue

        _lang = await lang.get_lang(chat_id)
        try:
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
                    await db.mark_playback_waiting(chat_id, media.time)
                    await app.send_message(chat_id, _lang["recovery_file_missing"])
                    continue

            status = await app.send_message(chat_id, _lang["recovery_checking"])
            status.lang = _lang
            from anony.helpers._play import ensure_assistant

            if not await ensure_assistant(status):
                await db.mark_playback_waiting(chat_id, media.time)
                continue

            media.message_id = status.id
            await anon.play_media(
                chat_id,
                status,
                media,
                seek_time=media.time,
                recovering=True,
            )
            if await db.get_call(chat_id) and session["state"] == "paused":
                await anon.pause(chat_id)
        except Exception:
            logger.exception("Could not restore playback for chat %s", chat_id)
            await db.mark_playback_waiting(chat_id, media.time)

    logger.info("Restored %s persisted playback queue(s).", restored)

async def main():
    await db.connect()
    app.logger = await db.get_log_chat()
    await app.boot()
    await userbot.boot()
    await anon.boot()
    await thumb.start()

    for module in all_modules:
        importlib.import_module(f"anony.plugins.{module}")
    logger.info(f"Loaded {len(all_modules)} modules.")

    if config.COOKIES_URL:
        await yt.save_cookies(config.COOKIES_URL)

    sudoers = await db.get_sudoers()
    app.sudoers.update(sudoers)
    app.bl_users.update(await db.get_blacklisted())
    logger.info(f"Loaded {len(app.sudoers)} sudo users.")

    await restore_playback()

    await idle()
    await stop()


if __name__ == "__main__":
    try:
        asyncio.get_event_loop().run_until_complete(main())
    except KeyboardInterrupt:
        pass
