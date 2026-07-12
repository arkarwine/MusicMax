# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from html import escape

from pyrogram import errors, filters, types

from anony import app, db, lang, logger
from anony.core.custom_emoji import localized_text, render_custom_emoji_text

_RANKS = (
    '<tg-emoji emoji-id="5408894951440279259">1️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5411585799990830248">2️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5409189019261103031">3️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5411500398861118321">4️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5409338071806146386">5️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5409194048667807708">6️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5411284026998681990">7️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5411120178291311191">8️⃣</tg-emoji>',
    '<tg-emoji emoji-id="5411457934519461707">9️⃣</tg-emoji>',
)


async def _trending_text(_lang: dict) -> str:
    tracks = await db.get_trending_tracks(days=30, limit=9)
    if not tracks:
        return _lang["trending_empty"]

    rows = [_lang["trending_title"]]
    for index, track in enumerate(tracks, start=1):
        title = escape(track["title"] or _lang["unknown_track"])
        url = track.get("url")
        if url and str(url).startswith(("https://", "http://")):
            title = f'<a href="{escape(url, quote=True)}">{title}</a>'
        rows.append(
            _lang["trending_item"].format(
                render_custom_emoji_text(_RANKS[index - 1]),
                title,
                track["plays"],
            )
        )
    return localized_text("\n".join(rows))


@app.on_message(filters.command(["trending"]) & ~app.bl_users)
@lang.language()
async def _trending(_, message: types.Message):
    try:
        await message.reply_text(
            await _trending_text(message.lang),
            disable_web_page_preview=True,
            disable_notification=True,
        )
    except Exception:
        logger.exception("Could not build the trending list")
        await message.reply_text(message.lang["trending_failed"])


@app.on_callback_query(filters.regex(r"^trending view$") & ~app.bl_users)
@lang.language()
async def _trending_callback(_, query: types.CallbackQuery):
    try:
        await query.answer(query.lang["trending_fetching"])
    except errors.QueryIdInvalid:
        pass
    try:
        await app.send_message(
            query.message.chat.id,
            await _trending_text(query.lang),
            disable_web_page_preview=True,
            disable_notification=True,
        )
    except Exception:
        logger.exception("Could not build the callback trending list")
        await app.send_message(
            query.message.chat.id,
            query.lang["trending_failed"],
            disable_notification=True,
        )
