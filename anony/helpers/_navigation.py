# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from pyrogram import errors, types

from anony import app


async def navigate(
    query: types.CallbackQuery,
    text: str,
    reply_markup: types.InlineKeyboardMarkup,
    *,
    send_new: bool = False,
):
    """Navigate in place unless the destination needs a fresh message."""
    try:
        await query.answer()
    except errors.QueryIdInvalid:
        pass

    if send_new or query.message.caption is not None:
        chat_id = query.message.chat.id
        return await app.send_message(
            chat_id,
            text,
            reply_markup=reply_markup,
            disable_notification=True,
        )
    return await query.edit_message_text(text, reply_markup=reply_markup)
