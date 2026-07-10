# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pathlib import Path
from html import escape

from pyrogram import enums, filters, types

from anony import app, db, lang, userbot, yt
from anony.helpers import admin_check


async def build_setup_text(m: types.Message) -> str:
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
        return m.lang["setup_ready"]
    return m.lang["setup_required"].format(requirement)


@app.on_message(filters.command(["setup"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _setup(_, m: types.Message):
    await m.reply_text(await build_setup_text(m), disable_notification=True)


@app.on_message(filters.command(["status"]) & app.sudoers)
@lang.language()
async def _status(_, m: types.Message):
    cookie_dir = Path(yt.cookie_dir)
    cookies = len(list(cookie_dir.glob("*.txt"))) if cookie_dir.exists() else 0
    sessions = await db.get_recovery_sessions()
    recovery = await db.get_recovery_report()
    recovery_text = (
        "\n".join(
            f"{item['chat_id']}: {item['stage']} "
            f"(attempts={item['attempts']})"
            + (f" - {item['detail'][:160]}" if item["detail"] else "")
            for item in recovery
        )
        if recovery
        else "none"
    )
    text = m.lang["status_sudo"].format(
        "connected" if db.connection else "disconnected",
        len(userbot.clients),
        cookies,
        "enabled" if await db.is_logger() else "disabled",
        app.logger or "none",
        len(sessions),
        len(db.active_calls),
        escape(recovery_text),
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
