# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from html import escape

from pyrogram import filters, types

from anony import app, config, db, lang, queue, thumb
from anony.helpers import Track, buttons, feedback


@app.on_message(filters.command(["queue", "playing"]) & filters.group & ~app.bl_users)
@lang.language()
async def _queue_func(_, m: types.Message):
    if not await db.get_call(m.chat.id) and not queue.get_current(m.chat.id):
        return await feedback.error(m, m.lang["not_playing"])

    _reply = await m.reply_text(m.lang["queue_fetching"])
    _queue = queue.get_queue(m.chat.id)
    if not _queue:
        await db.remove_call(m.chat.id)
        await db.clear_playback(m.chat.id)
        return await feedback.error_edit(_reply, m.lang["not_playing"])
    _media = _queue[0]
    _thumb = (
        await thumb.generate(_media)
        if isinstance(_media, Track)
        else config.DEFAULT_THUMB
    ) if config.THUMB_GEN else None
    _text = m.lang["queue_curr"].format(
        escape(_media.url or "", quote=True),
        escape((_media.title or m.lang["unknown_track"])[:50]),
        escape(_media.duration or "--:--"),
        _media.user or m.lang["someone"],
    )
    _queue.pop(0)

    if _queue:
        _text += "<blockquote expandable>"
        for i, media in enumerate(_queue, start=1):
            if i == 15:
                break
            _text += m.lang["queue_item"].format(
                i + 1,
                escape(media.title or m.lang["unknown_track"]),
                escape(media.duration or "--:--"),
            )
        _text += "</blockquote>"

    _playing = await db.playing(m.chat.id)
    _buttons = buttons.queue_markup(
            m.chat.id,
            m.lang["playing"] if _playing else m.lang["paused"],
            _playing,
        )
    if _thumb:
        await _reply.edit_media(
            media=types.InputMediaPhoto(
                media=_thumb,
                caption=_text,
            ),
            reply_markup=_buttons,
        )
    else:
        await _reply.edit_text(
            text=_text,
            reply_markup=_buttons,
        )
