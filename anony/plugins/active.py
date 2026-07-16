# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from html import escape
import os

from pyrogram import filters, types

from anony import app, db, lang, queue


@app.on_message(filters.command(["ac", "activevc"]) & app.sudoers)
@lang.language()
async def _activevc(_, m: types.Message):
    if not db.active_calls:
        return await m.reply_text(m.lang["vc_empty"])

    if m.command[0] == "ac":
        return await m.reply_text(m.lang["vc_count"].format(len(db.active_calls)))

    sent = await m.reply_text(m.lang["vc_fetching"])
    rows = []
    plain_rows = []

    for i, chat in enumerate(db.active_calls):
        playing = queue.get_current(chat)
        title = (
            playing.title[:25]
            if playing and playing.title
            else m.lang["vc_no_track"]
        )
        branch = "└" if i == len(db.active_calls) - 1 else "├"
        rows.append(
            f"{branch} {i + 1} | <code>{chat}</code> | {escape(title)}"
        )
        plain_rows.append(f"{i + 1}. {chat} | {title}")

    table_source = (
        f'<blockquote># · {m.lang["vc_table_chat"]} · '
        f'{m.lang["vc_table_track"]}\n' + "\n".join(rows) + "</blockquote>"
    )
    message = m.lang["vc_list"] + "\n\n" + table_source
    if len(message) < 4000:
        return await sent.edit_text(message)

    with open("activevc.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(plain_rows))
    await sent.edit_media(
        media=types.InputMediaDocument(
            media="activevc.txt",
            caption=m.lang["vc_list"],
        )
    )
    os.remove("activevc.txt")
