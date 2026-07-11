# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import asyncio
from html import escape
from pyrogram import enums, filters, types

from anony import app, config, db, lang
from anony.helpers import buttons, can_configure_group, utils


async def open_group_settings(message: types.Message, chat_id: int) -> None:
    if message.chat.type != enums.ChatType.PRIVATE:
        return
    if not await can_configure_group(chat_id, message.from_user.id):
        await message.reply_text(message.lang["settings_not_allowed"])
        return
    try:
        chat = await app.get_chat(chat_id)
    except Exception:
        await message.reply_text(message.lang["settings_unavailable"])
        return

    selected = await lang.get_lang(chat_id)
    await message.reply_text(
        selected["start_settings"].format(escape(chat.title or "Group")),
        reply_markup=buttons.settings_markup(
            selected,
            await db.get_play_mode(chat_id),
            await db.get_cmd_delete(chat_id),
            await db.get_feedback_cleanup(chat_id),
            await db.get_default_video(chat_id),
            await db.get_lang(chat_id),
            chat_id,
        ),
    )


@app.on_message(filters.command(["help"]) & filters.private & ~app.bl_users)
@lang.language()
async def _help(_, m: types.Message):
    await m.reply_text(
        text=m.lang["help_menu"],
        reply_markup=buttons.help_markup(
            m.lang,
            sudo=bool(m.from_user and m.from_user.id in app.sudoers),
        ),
        quote=True,
    )


@app.on_message(filters.command(["start"]))
@lang.language()
async def start(_, message: types.Message):
    if message.from_user.id in app.bl_users and message.from_user.id not in db.notified:
        db.notified.append(message.from_user.id)
        return await message.reply_text(
            message.lang["bl_user_notify"].format(config.SUPPORT_CHAT)
        )

    if len(message.command) > 1 and message.command[1] == "help":
        return await _help(_, message)

    if len(message.command) > 1 and message.command[1].startswith("settings_"):
        try:
            chat_id = int(message.command[1].removeprefix("settings_"))
        except ValueError:
            return await message.reply_text(message.lang["settings_unavailable"])
        return await open_group_settings(message, chat_id)

    if len(message.command) > 1 and message.command[1] == "sessions":
        from anony.plugins.sessions import open_sessions

        return await open_sessions(message)

    private = message.chat.type == enums.ChatType.PRIVATE
    _text = (
        message.lang["start_pm"].format(
            escape(message.from_user.first_name or "there"),
            escape(app.name),
        )
        if private
        else message.lang["start_gp"].format(escape(app.name))
    )

    key = buttons.start_key(
        message.lang,
        private,
        chat_id=message.chat.id,
    )
    await message.reply_photo(
        photo=config.START_IMG,
        caption=_text,
        reply_markup=key,
        quote=not private,
    )

    if private:
        if await db.is_user(message.from_user.id):
            return
        await utils.send_log(message)
        await db.add_user(message.from_user.id)
    else:
        if await db.is_chat(message.chat.id):
            return
        await utils.send_log(message, True)
        await db.add_chat(message.chat.id)


@app.on_message(filters.command(["playmode", "settings"]) & filters.group & ~app.bl_users)
@lang.language()
async def settings(_, message: types.Message):
    await message.reply_text(
        text=message.lang["settings_open_private"],
        reply_markup=buttons.settings_link(message.lang, message.chat.id),
        quote=True,
    )


@app.on_message(filters.new_chat_members, group=7)
@lang.language()
async def _new_member(_, message: types.Message):
    if not any(member.id == app.id for member in message.new_chat_members):
        return

    if message.chat.type != enums.ChatType.SUPERGROUP:
        return await message.chat.leave()

    await asyncio.sleep(3)
    if not await db.is_chat(message.chat.id):
        await utils.send_log(message, True)
        await db.add_chat(message.chat.id)
    from anony.plugins.setup import build_setup_text

    setup_text, ready = await build_setup_text(message)
    await message.reply_text(
        message.lang["welcome_group"] + "\n\n" + setup_text,
        reply_markup=buttons.setup_markup(message.lang, ready, message.chat.id),
        disable_notification=True,
    )
