# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
from datetime import datetime, timezone

from pyrogram import errors, filters, types

from anony import anon, app, boot, db, lang, logger, userbot
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
    assistants = len(set(userbot.clients) & set(anon.clients))
    bot_ready = bool(getattr(app, "is_connected", False))
    database_ready = db.connection is not None
    if bot_ready and database_ready and assistants:
        status = "Operational"
    elif bot_ready and database_ready:
        status = "Limited"
    else:
        status = "Degraded"
    return {
        "bot_name": app.name,
        "users": users,
        "groups": groups,
        "active_streams": len(db.active_calls),
        "assistants": assistants,
        "uptime": _uptime(),
        "status": status,
        "days": await db.get_analytics(7),
        "updated": datetime.now(timezone.utc).strftime("%d %b · %H:%M"),
    }


async def _build_stats() -> tuple:
    data = await _stats_data()
    return await stats_card.generate(data), data


@app.on_message(filters.command(["stats"]) & ~app.bl_users)
@lang.language()
async def _stats(_, message: types.Message):
    try:
        photo, _ = await _build_stats()
        await message.reply_photo(
            photo=photo,
            caption=message.lang["stats_caption"],
            disable_notification=True,
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
        photo, _ = await _build_stats()
        await app.send_photo(
            chat_id=query.message.chat.id,
            photo=photo,
            caption=query.lang["stats_caption"],
            disable_notification=True,
        )
    except Exception:
        logger.exception("Could not generate the callback analytics report")
        await app.send_message(
            query.message.chat.id,
            query.lang["stats_failed"],
            disable_notification=True,
        )