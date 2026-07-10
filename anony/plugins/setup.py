# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pathlib import Path

from pyrogram import enums, filters, types

from anony import app, db, lang, queue, userbot, yt
from anony.helpers import admin_check
from anony.helpers._play import assistant_membership


async def build_setup_text(m: types.Message) -> str:
    bot_member = await app.get_chat_member(m.chat.id, app.id)
    bot_admin = bot_member.status in {
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.ADMINISTRATOR,
    }
    can_invite = bot_member.status == enums.ChatMemberStatus.OWNER or bool(
        bot_member.privileges and bot_member.privileges.can_invite_users
    )

    try:
        _, membership = await assistant_membership(m.chat.id, m.chat.username)
        assistant_ready = membership == "ready"
    except Exception:
        assistant_ready = False

    lines = [
        m.lang["setup_bot_ready"] if bot_admin else m.lang["setup_bot_missing"],
        (
            m.lang["setup_invite_ready"]
            if can_invite
            else m.lang["setup_invite_missing"]
        ),
        (
            m.lang["setup_assistant_ready"]
            if assistant_ready
            else m.lang["setup_assistant_missing"]
        ),
    ]
    text = m.lang["setup_admin"].format("\n".join(lines), len(queue.get_queue(m.chat.id)))
    return text + (
        m.lang["setup_ready"]
        if bot_admin and can_invite and assistant_ready
        else m.lang["setup_action_needed"]
    )


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
