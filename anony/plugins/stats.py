# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import os
import platform
import sys
from html import escape

import psutil
from pyrogram import __version__, enums, filters, types
from pytgcalls import __version__ as pytgver

from anony import app, db, lang, userbot
from anony.helpers import buttons, navigate
from anony.plugins import all_modules


async def _stats_text(user_id: int) -> str:
    groups = len(await db.get_chats())
    users = len(await db.get_users())
    text = (
        f"📊 <b>{escape(app.name)} reach</b>\n\n"
        f"<blockquote>👥 <b>{users}</b> users · "
        f"💬 <b>{groups}</b> groups\n"
        f"🎧 <b>{len(db.active_calls)}</b> playing · "
        f"🤖 <b>{len(userbot.clients)}</b> assistants</blockquote>"
    )
    if user_id not in app.sudoers:
        return text

    process = psutil.Process(os.getpid())
    storage = psutil.disk_usage("/")
    return text + lang.languages["en"]["stats_sudo"].format(
        len(all_modules),
        platform.system(),
        f"{process.memory_info().rss / 1024**2:.2f}",
        round(psutil.virtual_memory().total / (1024.0**3)),
        process.cpu_percent(),
        psutil.cpu_count(),
        f"{storage.used / (1024.0**3):.2f}",
        f"{storage.total / (1024.0**3):.2f}",
        sys.version.split()[0],
        __version__,
        pytgver,
    )


def _stats_markup(private: bool) -> types.InlineKeyboardMarkup | None:
    if not private:
        return None
    return buttons.ikm([[
        buttons.ikb(text="⬅️ Home", callback_data="help home")
    ]])


@app.on_message(filters.command(["stats"]) & ~app.bl_users)
@lang.language()
async def _stats(_, message: types.Message):
    await message.reply_text(
        await _stats_text(message.from_user.id),
        reply_markup=_stats_markup(message.chat.type == enums.ChatType.PRIVATE),
        disable_notification=True,
    )


@app.on_callback_query(filters.regex(r"^stats view$") & ~app.bl_users)
@lang.language()
async def _stats_callback(_, query: types.CallbackQuery):
    await navigate(
        query,
        await _stats_text(query.from_user.id),
        _stats_markup(True),
    )
