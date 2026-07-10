# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import can_manage_vc


@app.on_message(filters.command(["end", "stop"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _stop(_, m: types.Message):
    if len(m.command) > 1:
        return

    call = await db.get_call(m.chat.id)
    if not call and not queue.get_current(m.chat.id):
        return await m.reply_text(m.lang["not_playing"])

    if call:
        await anon.stop(m.chat.id)
    else:
        queue.clear(m.chat.id)
        await db.set_loop(m.chat.id, 0)
        await db.clear_playback(m.chat.id)
    await m.reply_text(m.lang["play_stopped"].format(m.from_user.mention))
