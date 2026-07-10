# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import buttons, can_manage_vc
from anony.helpers._play import recover_playback


@app.on_message(filters.command(["resume"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _resume(_, m: types.Message):
    if not await db.get_call(m.chat.id):
        media = queue.get_current(m.chat.id)
        if not media:
            return await m.reply_text(m.lang["not_playing"])
        return await recover_playback(m)

    if await db.playing(m.chat.id):
        return await m.reply_text(m.lang["play_not_paused"])

    await anon.resume(m.chat.id)
    await m.reply_text(
        text=m.lang["play_resumed"].format(m.from_user.mention),
        reply_markup=buttons.controls(m.chat.id),
    )
