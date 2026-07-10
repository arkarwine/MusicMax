# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pathlib import Path

from pyrogram import enums, errors, filters, types

from anony import app, db, lang, queue, userbot, yt
from anony.helpers import admin_check


def _mark(ready: bool) -> str:
    return "✅" if ready else "⚠️"


@app.on_message(filters.command(["setup"]) & filters.group & ~app.bl_users)
@lang.language()
@admin_check
async def _setup(_, m: types.Message):
    bot_member = await app.get_chat_member(m.chat.id, app.id)
    bot_admin = bot_member.status in {
        enums.ChatMemberStatus.OWNER,
        enums.ChatMemberStatus.ADMINISTRATOR,
    }
    can_invite = bot_member.status == enums.ChatMemberStatus.OWNER or bool(
        bot_member.privileges and bot_member.privileges.can_invite_users
    )

    assistant_ready = False
    try:
        assistant = await db.get_client(m.chat.id)
        member = await app.get_chat_member(m.chat.id, assistant.id)
        assistant_ready = member.status in {
            enums.ChatMemberStatus.OWNER,
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.MEMBER,
        }
    except (errors.UserNotParticipant, errors.PeerIdInvalid):
        pass

    saved_tracks = len(queue.get_queue(m.chat.id))
    text = m.lang["setup_admin"].format(
        _mark(bot_admin),
        _mark(can_invite),
        _mark(assistant_ready),
        saved_tracks,
    )
    if not can_invite or not assistant_ready:
        text += m.lang["setup_action_needed"]
    else:
        text += m.lang["setup_ready"]
    await m.reply_text(text, disable_notification=True)


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
