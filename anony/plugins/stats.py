# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
from datetime import datetime, timezone
from html import escape

from pyrogram import errors, filters, types

from anony import anon, app, boot, db, lang, logger, userbot
from anony.helpers import buttons
from anony.helpers._stats_card import stats_card


def _uptime() -> str:
    elapsed = max(int(time.time() - boot), 0)
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours:02d}h {minutes:02d}m"
    return f"{minutes:02d}m"


async def _stats_data() -> dict:
    users = len(await db.get_users())
    groups = len(await db.get_chats())
    activity = await db.get_stream_activity(24)
    assistants = len(set(userbot.clients) & set(anon.clients))
    bot_ready = bool(getattr(app, "is_connected", False))
    database_ready = db.connection is not None
    if bot_ready and database_ready and assistants:
        status = "Ready"
    elif bot_ready and database_ready:
        status = "Getting ready"
    else:
        status = "Taking a break"
    return {
        "bot_name": app.name,
        "users": users,
        "groups": groups,
        "chats": users + groups,
        "streams_24h": activity["streams"],
        "active_chats_24h": activity["active_chats"],
        "assistants": assistants,
        "uptime": _uptime(),
        "status": status,
        "days": await db.get_analytics(7),
        "updated": datetime.now(timezone.utc).strftime("%d %b · %H:%M"),
    }


async def _build_stats() -> tuple:
    data = await _stats_data()
    return await stats_card.generate(data), data


def _compact(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def _stats_caption(_lang: dict, data: dict) -> str:
    return _lang["stats_caption"].format(
        escape(str(data["bot_name"])),
        _compact(data["chats"]),
        _compact(data["streams_24h"]),
        _compact(data["active_chats_24h"]),
        data["assistants"],
        escape(data["uptime"]),
        _lang[
            {
                "Ready": "stats_status_ready",
                "Getting ready": "stats_status_needs_assistant",
            }.get(data["status"], "stats_status_unavailable")
        ],
        _compact(
            sum(
                int(day.get("users_added", 0)) + int(day.get("groups_added", 0))
                for day in data["days"]
            )
        ),
        _compact(sum(int(day.get("plays", 0)) for day in data["days"])),
        "🟢" if data["status"] == "Ready" else "🟠",
    )


def _stats_markup(_lang: dict) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        [[buttons.ikb(text=_lang["stats_refresh"], callback_data="stats refresh")]]
    )


@app.on_message(filters.command(["stats"]) & ~app.bl_users)
@lang.language()
async def _stats(_, message: types.Message):
    try:
        photo, data = await _build_stats()
        await message.reply_photo(
            photo=photo,
            caption=_stats_caption(message.lang, data),
            disable_notification=True,
            reply_markup=_stats_markup(message.lang),
        )
    except Exception:
        logger.exception("Could not generate the analytics report")
        await message.reply_text(message.lang["stats_failed"])


@app.on_callback_query(filters.regex(r"^stats view$") & ~app.bl_users)
@lang.language()
async def _stats_callback(_, query: types.CallbackQuery):
    try:
        await query.answer(query.lang["stats_fetching"])
    except errors.QueryIdInvalid:
        pass
    try:
        photo, data = await _build_stats()
        await app.send_photo(
            chat_id=query.message.chat.id,
            photo=photo,
            caption=_stats_caption(query.lang, data),
            disable_notification=True,
            reply_markup=_stats_markup(query.lang),
        )
    except Exception:
        logger.exception("Could not generate the callback analytics report")
        await app.send_message(
            query.message.chat.id,
            query.lang["stats_failed"],
            disable_notification=True,
        )


@app.on_callback_query(filters.regex(r"^stats refresh$") & ~app.bl_users)
@lang.language()
async def _stats_refresh(_, query: types.CallbackQuery):
    try:
        await query.answer(query.lang["stats_refreshing"])
    except errors.QueryIdInvalid:
        pass
    try:
        photo, data = await _build_stats()
        await query.message.edit_media(
            types.InputMediaPhoto(
                media=photo,
                caption=_stats_caption(query.lang, data),
            ),
            reply_markup=_stats_markup(query.lang),
        )
    except errors.MessageNotModified:
        return
    except Exception:
        logger.exception("Could not refresh the analytics report")
        await app.send_message(
            query.message.chat.id,
            query.lang["stats_failed"],
            disable_notification=True,
        )
