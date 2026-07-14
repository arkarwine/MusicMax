# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import asyncio
from pathlib import Path
from html import escape

from pyrogram import filters, types

from anony import anon, app, config, db, lang, queue, tg, thumb, yt
from anony.helpers import Track, buttons, feedback, utils
from anony.helpers._play import checkUB


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
    sent = await m.reply_text(m.lang["play_searching"])
    file = None
    mention = m.from_user.mention
    media = tg.get_media(m.reply_to_message) if m.reply_to_message else None
    tracks = []

    if media:
        setattr(sent, "lang", m.lang)
        file = await tg.download(m.reply_to_message, sent)

    elif m3u8:
        file = await tg.process_m3u8(url, sent.id, video)

    elif url:
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

    if file.duration_sec > config.DURATION_LIMIT:
        return await feedback.error_edit(
            sent,
            m.lang["play_duration_limit"].format(config.DURATION_LIMIT // 60),
        )

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
        asyncio.create_task(thumb.generate(file))
        if config.THUMB_GEN and isinstance(file, Track)
        else None
    )
    if not file.file_path:
        fname = f"downloads/{file.id}.{'mp4' if video else 'webm'}"
        if Path(fname).exists():
            file.file_path = fname
        else:
            await sent.edit_text(m.lang["play_downloading"])
            file.file_path = await yt.download(file.id, video=video)

    await anon.play_media(
        chat_id=m.chat.id,
        message=sent,
        media=file,
        artwork_task=artwork_task,
    )
    if not tracks:
        return
    added = playlist_to_queue(m.chat.id, tracks)
    await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
    await app.send_message(
        chat_id=m.chat.id,
        text=m.lang["playlist_queued"].format(len(tracks)) + added,
    )
