# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import anon, app, db, lang, queue
from anony.helpers import buttons, can_manage_vc, feedback


@app.on_message(filters.command(["end", "stop"]) & filters.group & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _stop(_, m: types.Message):
    if len(m.command) > 1:
        return

    call = await db.get_call(m.chat.id)
    if not call and not queue.get_current(m.chat.id):
        return await feedback.error(m, m.lang["not_playing"])

    media = queue.get_current(m.chat.id)
    message_id = media.message_id if media else 0
    if call:
        await anon.stop(m.chat.id)
    else:
        queue.clear(m.chat.id)
        await db.set_loop(m.chat.id, 0)
        await db.clear_playback(m.chat.id)
    if message_id:
        try:
            await app.edit_message_reply_markup(
                m.chat.id,
                message_id,
                reply_markup=buttons.controls(
                    m.chat.id,
                    status=m.lang["stopped"],
                    remove=True,
                ),
            )
        except Exception:
            pass
    await feedback.send(m, m.lang["play_stopped"].format(m.from_user.mention))
