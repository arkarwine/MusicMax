# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import can_manage_vc, feedback


@app.on_message(filters.command(["skip", "next"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        if not queue.get_current(m.chat.id):
            return await feedback.send(m, m.lang["not_playing"], error=True)
        queue.get_next(m.chat.id)
        if queue.get_current(m.chat.id):
            await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
            await db.mark_playback_waiting(m.chat.id)
        else:
            await db.clear_playback(m.chat.id)
        return await feedback.send(m, m.lang["recovery_skipped"])

    await anon.play_next(m.chat.id)
    await feedback.send(m, m.lang["play_skipped"].format(m.from_user.mention))
