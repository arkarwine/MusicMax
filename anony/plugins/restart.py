# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import os
import sys
import shutil
from html import escape

from pyrogram import enums, filters, types

from anony import app, db, lang, stop


@app.on_message(filters.command(["logs"]) & app.sudoers)
@lang.language()
async def _logs(_, m: types.Message):
    sent = await m.reply_text(m.lang["log_fetch"])
    if not os.path.exists("log.txt"):
        return await sent.edit_text(m.lang["log_not_found"])
    await sent.edit_media(
        media=types.InputMediaDocument(
            media="log.txt",
            caption=m.lang["log_sent"].format(app.name),
        )
    )


@app.on_message(filters.command(["logger"]) & app.sudoers)
@lang.language()
async def _logger(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(m.lang["logger_usage"].format(m.command[0]))
    if m.command[1] not in ("on", "off"):
        return await m.reply_text(m.lang["logger_usage"].format(m.command[0]))

    if m.command[1] == "on":
        if not app.logger:
            return await m.reply_text(m.lang["logger_no_chat"])
        await db.set_logger(True)
        await m.reply_text(
            m.lang["logger_on"] + m.lang["logger_destination"].format(app.logger)
        )
    else:
        await db.set_logger(False)
        await m.reply_text(m.lang["logger_off"])


@app.on_message(filters.command(["setlog"]) & app.sudoers)
@lang.language()
async def _setlog(_, m: types.Message):
    """Set, replace, or clear the persistent log destination at runtime."""
    argument = m.command[1] if len(m.command) > 1 else None
    if argument and argument.lower() in {"off", "disable", "clear"}:
        previous = app.logger
        await db.set_logger(False)
        await db.set_log_chat(None)
        app.logger = None
        return await m.reply_text(m.lang["setlog_cleared"].format(previous or "none"))

    if argument:
        try:
            target = argument if argument.startswith("@") else int(argument)
        except ValueError:
            return await m.reply_text(m.lang["setlog_usage"])
    else:
        target = m.chat.id

    try:
        chat = await app.get_chat(target)
        if chat.type not in {
            enums.ChatType.GROUP,
            enums.ChatType.SUPERGROUP,
            enums.ChatType.CHANNEL,
        }:
            return await m.reply_text(m.lang["setlog_group_only"])

        member = await app.get_chat_member(chat.id, app.id)
        if member.status not in {
            enums.ChatMemberStatus.ADMINISTRATOR,
            enums.ChatMemberStatus.OWNER,
        }:
            return await m.reply_text(m.lang["setlog_admin_required"].format(chat.id))

        if chat.id != m.chat.id:
            await app.send_message(chat.id, m.lang["setlog_ready"].format(m.from_user.mention))
    except Exception as ex:
        return await m.reply_text(
            m.lang["setlog_failed"].format(
                type(ex).__name__, escape(str(ex)[:500]) or "No details provided"
            )
        )

    previous = app.logger
    app.logger = chat.id
    await db.set_log_chat(chat.id)
    await db.set_logger(True)
    await m.reply_text(
        m.lang["setlog_success"].format(
            escape(chat.title or "Untitled chat"),
            chat.id,
            previous or "none",
        )
    )


@app.on_message(filters.command(["restart"]) & app.sudoers)
@lang.language()
async def _restart(_, m: types.Message):
    sent = await m.reply_text(m.lang["restarting"])

    for directory in ["cache", "downloads"]:
        shutil.rmtree(directory, ignore_errors=True)

    await sent.edit_text(m.lang["restarted"])
    await stop("sudo restart")

    try:
        os.remove("log.txt")
    except Exception:
        pass

    os.execl(sys.executable, sys.executable, "-m", "anony")
