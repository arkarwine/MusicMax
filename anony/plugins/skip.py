# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, db, lang, queue, userbot
from anony.helpers import can_manage_vc, feedback


@app.on_message(filters.command(["skip", "next"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _skip(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        if not queue.get_current(m.chat.id):
            return await feedback.error(m, m.lang["not_playing"])
        queue.get_next(m.chat.id)
        if queue.get_current(m.chat.id):
            await db.save_queue(m.chat.id, queue.get_queue(m.chat.id))
            await db.mark_playback_waiting(m.chat.id)
        else:
            await db.clear_playback(m.chat.id)
        return await feedback.send(m, m.lang["recovery_skipped"])

    assigned = db.assistant.get(m.chat.id)
    if assigned is not None and not userbot.is_accepting(assigned):
        return await feedback.warning(m, m.lang["play_session_locked"])

    await anon.play_next(m.chat.id)
    await feedback.send(m, m.lang["play_skipped"].format(m.from_user.mention))
