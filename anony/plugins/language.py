# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import enums, filters, types

from anony import app, db, lang
from anony.helpers import admin_check, buttons, can_configure_group, feedback


@app.on_message(filters.command(["lang", "language"]) & ~app.bl_users)
@lang.language()
async def _lang(_, m: types.Message):
    if m.chat.type in {enums.ChatType.GROUP, enums.ChatType.SUPERGROUP}:
        return await m.reply_text(
            m.lang["settings_open_private"],
            reply_markup=buttons.settings_link(m.lang, m.chat.id),
        )
    current = await db.get_lang(m.chat.id)
    keyboard = buttons.lang_markup(current)
    await m.reply_text(m.lang["lang_choose"], reply_markup=keyboard)


@app.on_callback_query(filters.regex(r"^lang(?:_change|uage)") & ~app.bl_users)
@lang.language()
@admin_check
async def _lang_cb(_, query: types.CallbackQuery):
    data = query.data.split()
    if not data:
        return await query.answer(query.lang["play_expired"], show_alert=False)
    if data[0] == "language":
        current = await db.get_lang(query.message.chat.id)
        keyboard = buttons.lang_markup(current)
        return await query.edit_message_text(
            query.lang["lang_choose"], reply_markup=keyboard
        )

    if len(data) < 2 or data[1] not in lang.get_languages():
        return await query.answer(query.lang["play_expired"], show_alert=False)

    _lang = data[1]
    current = await db.get_lang(query.message.chat.id)
    if current == _lang:
        return await feedback.toast(
            query, query.lang["lang_same"].format(current)
        )

    await db.set_lang(query.message.chat.id, _lang)
    selected = lang.languages[_lang]
    await feedback.toast(query, selected["lang_changed"].format(_lang))
    await query.edit_message_text(
        selected["lang_choose"],
        reply_markup=buttons.lang_markup(_lang),
    )


@app.on_callback_query(filters.regex(r"^settings_lang ") & ~app.bl_users)
@lang.language()
async def _group_lang_cb(_, query: types.CallbackQuery):
    data = query.data.split()
    try:
        chat_id = int(data[1])
        code = data[2]
    except (IndexError, ValueError):
        return await feedback.toast(query, query.lang["play_expired"])
    if code not in lang.get_languages():
        return await feedback.toast(query, query.lang["play_expired"])
    if not await can_configure_group(chat_id, query.from_user.id):
        return await query.answer(
            query.lang["settings_not_allowed"], show_alert=True
        )
    await db.set_lang(chat_id, code)
    selected = lang.languages[code]
    await feedback.toast(query, selected["lang_changed"].format(code))
    await query.edit_message_text(
        selected["lang_choose"],
        reply_markup=buttons.group_lang_markup(code, chat_id, selected),
    )
