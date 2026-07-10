# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from html import escape

from py_yt import VideosSearch
from pyrogram import types

from anony import app, logger
from anony.helpers import buttons


@app.on_inline_query(~app.bl_users)
async def inline_query_handler(_, query: types.InlineQuery):
    text = query.query.strip().lower()
    if not text:
        return await app.answer_inline_query(
            query.id,
            results=[
                types.InlineQueryResultArticle(
                    title="Search for a song",
                    description="Type a song title, artist, or YouTube link.",
                    input_message_content=types.InputTextMessageContent(
                        "Type a song title, artist, or YouTube link to search."
                    ),
                )
            ],
            cache_time=5,
        )

    try:
        search = VideosSearch(text, limit=15)
        results = (await search.next()).get("result", [])

        answers = []
        for video in results:
            title = video.get("title") or "Unknown title"
            duration = video.get("duration", "N/A")
            views = video.get("viewCount", {}).get("short", "N/A")
            thumbnails = video.get("thumbnails") or [{}]
            thumbnail = (thumbnails[0].get("url") or "").split("?")[0]
            channel = video.get("channel", {}).get("name", "Unknown Channel")
            channellink = video.get("channel", {}).get("link", "https://youtube.com")
            link = video.get("link", "https://youtube.com")
            published = video.get("publishedTime", "N/A")

            description = f"{duration} · {channel} · {views} views"
            caption = (
                f"🎵 <b><a href='{escape(link, quote=True)}'>"
                f"{escape(title[:250])}</a></b>\n"
                f"<blockquote>{escape(duration)} · "
                f"<a href='{escape(channellink, quote=True)}'>"
                f"{escape(channel)}</a> · {escape(views)} views</blockquote>\n"
                f"<i>{escape(published)}</i>"
            )

            answers.append(
                types.InlineQueryResultPhoto(
                    photo_url=thumbnail,
                    title=title,
                    description=description,
                    caption=caption,
                    reply_markup=buttons.yt_key(link),
                )
            )

        if answers:
            await app.answer_inline_query(query.id, results=answers, cache_time=5)
    except Exception:
        logger.exception("Inline search failed for user %s", query.from_user.id)
        await app.answer_inline_query(
            query.id,
            results=[
                types.InlineQueryResultArticle(
                    title="Search is temporarily unavailable",
                    description="Please try again in a moment.",
                    input_message_content=types.InputTextMessageContent(
                        "I couldn't complete that search. Please try again in a moment."
                    ),
                )
            ],
            cache_time=1,
        )
