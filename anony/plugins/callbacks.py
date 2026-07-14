# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from html import escape

from pyrogram import enums, errors, filters, types

from anony import anon, app, db, lang, queue, tg, yt
from anony.helpers import (
    admin_check,
    buttons,
    can_configure_group,
    can_manage_vc,
    feedback,
    navigate,
)
from anony.helpers._play import recover_playback


@app.on_callback_query(filters.regex("cancel_dl") & ~app.bl_users)
@lang.language()
async def cancel_dl(_, query: types.CallbackQuery):
    await query.answer()
    await tg.cancel(query)


@app.on_callback_query(filters.regex("controls") & ~app.bl_users)
@lang.language()
@can_manage_vc
async def _controls(_, query: types.CallbackQuery):
    args = query.data.split()
    if len(args) < 3 or args[1] not in {
        "status", "loop", "pause", "resume", "skip", "force", "replay", "stop",
    }:
        return await query.answer(query.lang["play_expired"], show_alert=False)
    action, chat_id = args[1], int(args[2])
    qaction = len(args) == 4
    user = query.from_user.mention

    if not await db.get_call(chat_id):
        if action == "resume" and queue.get_current(chat_id):
            await query.answer(query.lang["processing"], show_alert=False)
            query.message.lang = query.lang
            await recover_playback(query.message)
            return
        try:
            return await query.answer(query.lang["not_playing"], show_alert=True)
        except errors.QueryIdInvalid:
            try:
                await query.message.delete()
            except Exception:
                pass
            return

    if action == "status":
        return await query.answer()

    if action == "loop":
        enabled = await db.get_loop(chat_id) == -1
        await db.set_loop(chat_id, 0 if enabled else -1)
        return await feedback.toast(
            query,
            query.lang["loop_off"] if enabled else query.lang["loop_forever"],
        )

    if action == "pause":
        if not await db.playing(chat_id):
            return await query.answer(
                query.lang["play_already_paused"], show_alert=True
            )
        await feedback.toast(query, query.lang["pausing"])
        await anon.pause(chat_id)
        if qaction:
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["paused"], False)
            )
        status = query.lang["paused"]

    elif action == "resume":
        if await db.playing(chat_id):
            return await query.answer(query.lang["play_not_paused"], show_alert=True)
        await feedback.toast(query, query.lang["resuming"])
        await anon.resume(chat_id)
        if qaction:
            return await query.edit_message_reply_markup(
                reply_markup=buttons.queue_markup(chat_id, query.lang["playing"], True)
            )

    elif action == "skip":
        await feedback.toast(query, query.lang["skipping"])
        await anon.play_next(chat_id)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    elif action == "force":
        if len(args) < 4:
            return await query.answer(query.lang["play_expired"], show_alert=False)
        pos, media = queue.check_item(chat_id, args[3])
        if not media or pos == -1:
            return await query.edit_message_text(query.lang["play_expired"])

        current = queue.get_current(chat_id)
        if not current:
            return await query.answer(query.lang["not_playing"], show_alert=False)
        await feedback.toast(query, query.lang["playing_now"])
        m_id = current.message_id
        queue.force_add(chat_id, media, remove=pos)
        await db.save_queue(chat_id, queue.get_queue(chat_id))
        try:
            await app.delete_messages(
                chat_id=chat_id, message_ids=[m_id, media.message_id], revoke=True
            )
            media.message_id = None
        except Exception:
            pass

        msg = await app.send_message(chat_id=chat_id, text=query.lang["play_next"])
        if not media.file_path:
            media.file_path = await yt.download(media.id, video=media.video)
        media.message_id = msg.id
        return await anon.play_media(chat_id, msg, media)

    elif action == "replay":
        media = queue.get_current(chat_id)
        if not media:
            return await query.answer(query.lang["not_playing"], show_alert=False)
        await feedback.toast(query, query.lang["replaying"])
        media.user = user
        await anon.replay(chat_id)
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    elif action == "stop":
        await feedback.toast(query, query.lang["stopping"])
        await anon.stop(chat_id)
        status = query.lang["stopped"]

    keyboard = buttons.controls(
        chat_id,
        status=status if action != "resume" else None,
        remove=action == "stop",
        playing=action != "pause",
    )
    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except (
        errors.MessageIdInvalid, errors.MessageNotModified,
        errors.QueryIdInvalid,
    ):
        return


@app.on_callback_query(filters.regex("help") & ~app.bl_users)
@lang.language()
async def _help(_, query: types.CallbackQuery):
    data = query.data.split()
    if len(data) == 1:
        if query.message.chat.type != enums.ChatType.PRIVATE:
            return await query.answer(
                url=f"https://t.me/{app.username}?start=help"
            )
        return await navigate(
            query,
            query.lang["help_menu"],
            buttons.help_markup(
                query.lang,
                sudo=query.from_user.id in app.sudoers,
            ),
        )
    if data[1] not in {
        "back", "home", "new", "admins", "auth", "blist", "lang",
        "ping", "play", "queue", "stats", "sudo",
    }:
        return await feedback.toast(query, query.lang["play_expired"])

    if data[1] == "new":
        return await navigate(
            query,
            query.lang["help_menu"],
            buttons.help_markup(
                query.lang,
                sudo=query.from_user.id in app.sudoers,
            ),
            send_new=True,
        )

    if data[1] == "back":
        return await navigate(
            query,
            query.lang["help_menu"],
            buttons.help_markup(
                query.lang,
                sudo=query.from_user.id in app.sudoers,
            ),
        )
    if data[1] == "home":
        return await navigate(
            query,
            query.lang["start_pm"].format(
                escape(query.from_user.first_name or "there"),
                escape(app.name),
            ),
            buttons.start_key(
                query.lang,
                private=True,
            ),
            send_new=True,
        )

    if data[1] == "sudo" and query.from_user.id not in app.sudoers:
        return await feedback.toast(query, query.lang["play_expired"])
    await navigate(
        query,
        query.lang[f"help_{data[1]}"],
        buttons.help_markup(
            query.lang,
            True,
            sudo=query.from_user.id in app.sudoers,
        ),
    )


@app.on_callback_query(filters.regex(r"^settings(?: |$)") & ~app.bl_users)
@lang.language()
async def _settings_cb(_, query: types.CallbackQuery):
    cmd = query.data.split()
    if len(cmd) < 2:
        return await feedback.toast(query, query.lang["play_expired"])
    try:
        chat_id = int(cmd[1])
    except ValueError:
        return await feedback.toast(query, query.lang["play_expired"])
    if not await can_configure_group(chat_id, query.from_user.id):
        return await query.answer(
            query.lang["settings_not_allowed"], show_alert=True
        )
    if len(cmd) == 2:
        return await query.answer()

    _admin = await db.get_play_mode(chat_id)
    _delete = await db.get_cmd_delete(chat_id)
    _cleanup = await db.get_feedback_cleanup(chat_id)
    _video = await db.get_default_video(chat_id)
    _language = await db.get_lang(chat_id)

    action = cmd[2]
    if action == "language":
        return await query.edit_message_text(
            query.lang["lang_choose"],
            reply_markup=buttons.group_lang_markup(
                _language, chat_id, query.lang
            ),
        )
    if action == "delete":
        _delete = not _delete
        await db.set_cmd_delete(chat_id, _delete)
    elif action == "play":
        await db.set_play_mode(chat_id, _admin)
        _admin = not _admin
    elif action == "cleanup":
        _cleanup = not _cleanup
        await db.set_feedback_cleanup(chat_id, _cleanup)
    elif action == "video":
        _video = not _video
        await db.set_default_video(chat_id, _video)
    elif action != "back":
        return await feedback.toast(query)
    selected = await lang.get_lang(chat_id)
    await feedback.toast(query, query.lang["setting_saved"])
    try:
        target = await app.get_chat(chat_id)
        title = escape(target.title or "Group")
    except Exception:
        title = "Group"
    await query.edit_message_text(
        selected["start_settings"].format(title),
        reply_markup=buttons.settings_markup(
            selected,
            _admin,
            _delete,
            _cleanup,
            _video,
            _language,
            chat_id,
        )
    )
