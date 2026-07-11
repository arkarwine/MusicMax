# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pathlib import Path
from pyrogram import enums, filters, types

from anony import app, db, lang, userbot, yt
from anony.helpers import admin_check, buttons, feedback


async def build_setup_text(m: types.Message) -> tuple[str, bool]:
    bot_member = await app.get_chat_member(m.chat.id, app.id)
    bot_admin = bot_member.status in {
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.ADMINISTRATOR,
    }
    can_invite = bot_member.status == enums.ChatMemberStatus.OWNER or bool(
        bot_member.privileges and bot_member.privileges.can_invite_users
    )

    if not bot_admin:
        requirement = m.lang["setup_bot_missing"]
    elif not can_invite:
        requirement = m.lang["setup_invite_missing"]
    else:
        return m.lang["setup_ready"], True
    return m.lang["setup_required"].format(requirement), False


@app.on_message(filters.command(["setup"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _setup(_, m: types.Message):
    text, ready = await build_setup_text(m)
    await m.reply_text(
        text,
        reply_markup=buttons.setup_markup(m.lang, ready, m.chat.id),
        disable_notification=True,
    )


@app.on_callback_query(filters.regex(r"^setup check$") & ~app.bl_users)
@lang.language()
@admin_check
async def _setup_callback(_, query: types.CallbackQuery):
    action = query.data.split()[1]
    query.message.lang = query.lang
    if action == "check":
        text, ready = await build_setup_text(query.message)
        await feedback.toast(query, query.lang["setup_checked"])
        return await query.edit_message_text(
            text,
            reply_markup=buttons.setup_markup(
                query.lang, ready, query.message.chat.id
            ),
        )


@app.on_message(filters.command(["status"]) & app.sudoers)
@lang.language()
async def _status(_, m: types.Message):
    cookie_dir = Path(yt.cookie_dir)
    cookies = len(list(cookie_dir.glob("*.txt"))) if cookie_dir.exists() else 0
    sessions = await db.get_recovery_sessions()
    text = m.lang["status_sudo"].format(
        "connected" if db.connection else "disconnected",
        len(userbot.clients),
        cookies,
        "enabled" if await db.is_logger() else "disabled",
        app.logger or "none",
        len(sessions),
        len(db.active_calls),
    )
    await m.reply_text(text, disable_notification=True)


@app.on_message(filters.command(["backupdb"]) & app.sudoers)
@lang.language()
async def _backupdb(_, m: types.Message):
    sent = await m.reply_text(m.lang["backup_start"], disable_notification=True)
    path = await db.backup()
    await m.reply_document(
        document=str(path),
        caption=m.lang["backup_done"].format(path.name),
        disable_notification=True,
    )
    await sent.delete()
