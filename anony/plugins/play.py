# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from contextlib import suppress
from pathlib import Path
from html import escape
from time import monotonic

from pyrogram import filters, types

from anony import (
    anon,
    app,
    config,
    db,
    lang,
    logger,
    queue,
    supervisor,
    tg,
    thumb,
    userbot,
    yt,
)
from anony.helpers import Track, buttons, feedback, utils
from anony.helpers._play import checkUB, ensure_assistant


async def _download_with_status(sent, text: str, video_id: str, video: bool):
    """Download immediately while keeping the optional status edit off-path."""
    download_task = asyncio.create_task(
        yt.download(video_id, video=video),
        name=f"play-download:{video_id}",
    )
    status_task = None
    try:
        try:
            return await asyncio.wait_for(
                asyncio.shield(download_task),
                timeout=0.35,
            )
        except asyncio.TimeoutError:
            status_task = asyncio.create_task(
                sent.edit_text(text),
                name=f"play-download-status:{video_id}",
            )
            return await download_task
    finally:
        if status_task is not None:
            if not status_task.done():
                status_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await status_task


def playlist_to_queue(chat_id: int, tracks: list) -> str:
    text = "<blockquote expandable>"
    for track in tracks:
        pos = queue.add(chat_id, track)
        text += f"<b>{pos}.</b> {escape(track.title or 'Unknown track')}\n"
    text = text[:1948] + "</blockquote>"
    return text

@app.on_message(
    filters.command(["play", "playforce", "vplay", "vplayforce"])
    & filters.group
    & ~app.bl_users
)
@lang.language()
@checkUB
async def play_hndlr(
    _,
    m: types.Message,
    force: bool = False,
    m3u8: bool = False,
    video: bool = False,
    url: str = None,
) -> None:
    pipeline_started = monotonic()
    lookup_finished = pipeline_started
    assistant_seconds = 0.0
    download_seconds = 0.0
    cache_state = "n/a"
    source_kind = "reply" if m.reply_to_message else "text"
    sent = await m.reply_text(m.lang["play_searching"])
    file = None
    mention = m.from_user.mention
    media = tg.get_media(m.reply_to_message) if m.reply_to_message else None
    tracks = []

    if media:
        setattr(sent, "lang", m.lang)
        file = await tg.download(m.reply_to_message, sent)

    elif m3u8:
        source_kind = "stream"
        file = await tg.process_m3u8(url, sent.id, video)

    elif url:
        source_kind = "link"
        if "playlist" in url:
            await sent.edit_text(m.lang["playlist_fetch"])
            tracks = await yt.playlist(
                config.PLAYLIST_LIMIT, mention, url, video
            )

            if not tracks:
                return await feedback.error_edit(sent, m.lang["playlist_error"])

            file = tracks[0]
            tracks.remove(file)
            file.message_id = sent.id
        else:
            file = await yt.search(url, sent.id, video=video)

        if not file:
            return await feedback.error_edit(
                sent,
                m.lang["play_not_found"].format(config.SUPPORT_CHAT),
            )

    elif len(m.command) >= 2:
        query = " ".join(
            argument
            for argument in m.command[1:]
            if argument not in {"-f", "-v", "-a"}
        )
        if not query:
            return await feedback.error_edit(sent, m.lang["play_usage"])
        file = await yt.search(query, sent.id, video=video)
        if not file:
            return await feedback.error_edit(
                sent,
                m.lang["play_not_found"].format(config.SUPPORT_CHAT),
            )

    if not file:
        return await feedback.error_edit(sent, m.lang["play_usage"])
    lookup_finished = monotonic()

    if file.duration_sec > config.DURATION_LIMIT:
        return await feedback.error_edit(
            sent,
            m.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60),
        )

    assigned = db.assistant.get(m.chat.id)
    if (
        m.chat.id in db.active_calls
        and assigned is not None
        and not userbot.is_accepting(assigned)
    ):
        return await feedback.warning_edit(sent, m.lang["play_session_locked"])

    if m.chat.id not in db.active_calls:
        assistant_started = monotonic()
        if not await ensure_assistant(m):
            return
        assistant_seconds = monotonic() - assistant_started

    if await db.is_logger():
        await utils.play_log(m, sent.link, file.title, file.duration)

    file.user = mention
    if force:
        queue.force_add(m.chat.id, file)
        await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
        if not await db.get_call(m.chat.id):
            await db.save_playback(m.chat.id, "waiting", file.time)
    else:
        position = queue.add(m.chat.id, file)
        await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
        if not await db.get_call(m.chat.id):
            await db.save_playback(m.chat.id, "waiting", file.time)

        active = await db.get_call(m.chat.id)
        if position != 0 or active:
            text = m.lang["play_queued"].format(
                position,
                escape(file.url or "", quote=True),
                escape(file.title or m.lang["unknown_track"]),
                escape(file.duration or "--:--"),
                m.from_user.mention,
            )
            if not active:
                text += "\n\n" + m.lang["recovery_waiting"]
            await sent.edit_text(
                text,
                reply_markup=(
                    buttons.play_queued(m.chat.id, file.id, m.lang["play_now"])
                    if active
                    else buttons.recovery(m.chat.id, m.lang["resume_queue"])
                ),
            )
            if tracks:
                added = playlist_to_queue(m.chat.id, tracks)
                await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
                await app.send_message(
                    chat_id=m.chat.id,
                    text=m.lang["playlist_queued"].format(len(tracks)) + added,
                )
            return

    artwork_task = (
        supervisor.spawn_once(f"artwork:{m.chat.id}", thumb.generate(file))
        if config.THUMB_GEN and isinstance(file, Track)
        else None
    )
    if not file.file_path:
        fname = f"downloads/{file.id}.{'mp4' if video else 'webm'}"
        cached_file = Path(fname) if Path(fname).exists() else None
        if cached_file is None and not video:
            cached_file = next(
                iter(sorted(Path("downloads").glob(f"{file.id}.*"))),
                None,
            )
        if cached_file is not None:
            cache_state = "hit"
            file.file_path = str(cached_file)
        else:
            cache_state = "miss"
            download_started = monotonic()
            file.file_path = await _download_with_status(
                sent,
                m.lang["play_downloading"],
                file.id,
                video,
            )
            download_seconds = monotonic() - download_started
    else:
        cache_state = "provided"

    delivery_started = monotonic()
    played = await anon.play_media(
        chat_id=m.chat.id,
        message=sent,
        media=file,
        artwork_task=artwork_task,
    )
    total_seconds = monotonic() - pipeline_started
    logger.info(
        "Play pipeline chat=%s source=%s cache=%s result=%s "
        "lookup=%.2fs assistant=%.2fs download=%.2fs delivery=%.2fs "
        "total=%.2fs",
        m.chat.id,
        source_kind,
        cache_state,
        "started" if played else "failed",
        lookup_finished - pipeline_started,
        assistant_seconds,
        download_seconds,
        monotonic() - delivery_started,
        total_seconds,
    )
    if not tracks:
        return
    added = playlist_to_queue(m.chat.id, tracks)
    await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(len(tracks)) + added,
    )
