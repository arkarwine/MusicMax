# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import buttons, can_manage_vc, feedback


@app.on_message(filters.command(["pause"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _pause(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        return await feedback.error(m, m.lang["not_playing"])

    if not await db.playing(m.chat.id):
        return await feedback.send(m, m.lang["play_already_paused"])

    await anon.pause(m.chat.id)
    media = queue.get_current(m.chat.id)
    if media and media.message_id:
        try:
            await app.edit_message_reply_markup(
                m.chat.id,
                media.message_id,
                reply_markup=buttons.controls(m.chat.id, playing=False),
            )
        except Exception:
            pass
    await feedback.send(m, m.lang["play_paused"].format(m.from_user.mention))
