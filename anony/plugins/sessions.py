# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from html import escape
from math import ceil

from pyrogram import enums, filters, types

from anony import app, db, lang, userbot
from anony.helpers import buttons, feedback

PAGE_SIZE = 6
_add_prompts: dict[int, int] = {}


async def _find_session(reference: str) -> dict | None:
    sessions = await db.get_assistant_sessions()
    normalized = reference.removeprefix("@").lower()
    try:
        number = int(reference)
    except ValueError:
        number = None
    return next(
        (
            session
            for session in sessions
            if (
                number is not None
                and (session["slot"] == number or session["user_id"] == number)
            )
            or (session["username"] or "").lower() == normalized
        ),
        None,
    )


def _identity(session: dict) -> str:
    if session["username"]:
        return f"@{escape(session['username'])}"
    return escape(session["display_name"] or f"Session {session['slot']}")


def _dashboard_markup(sessions: list[dict], page: int) -> types.InlineKeyboardMarkup:
    pages = max(1, ceil(len(sessions) / PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    visible = sessions[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    rows = []
    for session in visible:
        active = session["slot"] in userbot.clients
        rows.append([
            buttons.ikb(
                text=f"{'●' if active else '○'}  {session['slot']} · "
                f"{session['username'] or session['display_name'] or 'Unknown'}",
                callback_data=f"session view {session['slot']} {page}",
                style=(
                    enums.ButtonStyle.SUCCESS
                    if active
                    else enums.ButtonStyle.DEFAULT
                ),
            )
        ])
    if pages > 1:
        rows.append([
            buttons.ikb(
                text="‹",
                callback_data=f"session page {max(0, page - 1)}",
            ),
            buttons.ikb(text=f"{page + 1} / {pages}", callback_data="session noop"),
            buttons.ikb(
                text="›",
                callback_data=f"session page {min(pages - 1, page + 1)}",
            ),
        ])
    rows.extend([
        [
            buttons.ikb(
                text="＋ Add session",
                callback_data="session add",
                style=enums.ButtonStyle.SUCCESS,
            ),
            buttons.ikb(text="↻ Refresh", callback_data=f"session page {page}"),
        ],
        [buttons.ikb(
            text="Close", callback_data="session close", style=enums.ButtonStyle.DANGER
        )],
    ])
    return buttons.ikm(rows)


async def _dashboard(page: int = 0) -> tuple[str, types.InlineKeyboardMarkup]:
    sessions = await db.get_assistant_sessions()
    active = len(userbot.clients)
    text = (
        "<b>Assistant sessions</b>\n\n"
        f"<blockquote><b>{active}</b> active · "
        f"<b>{len(sessions) - active}</b> disabled · "
        f"<b>{len(sessions)}</b> total</blockquote>\n\n"
        "Choose an account to inspect or manage it."
    )
    return text, _dashboard_markup(sessions, page)


async def open_sessions(message: types.Message, page: int = 0) -> None:
    if not message.from_user or message.from_user.id not in app.sudoers:
        await message.reply_text(message.lang["session_not_allowed"])
        return
    if message.chat.type != enums.ChatType.PRIVATE:
        await message.reply_text(
            message.lang["sessions_open_private"],
            reply_markup=buttons.ikm([[
                buttons.ikb(
                    text=message.lang["open_sessions"],
                    url=f"https://t.me/{app.username}?start=sessions",
                )
            ]]),
        )
        return
    text, markup = await _dashboard(page)
    await message.reply_text(text, reply_markup=markup, disable_notification=True)


def _detail(session: dict) -> tuple[str, types.InlineKeyboardMarkup]:
    slot = session["slot"]
    active = slot in userbot.clients
    calls = len(db.active_chats_for_assistant(slot))
    state = "Active" if active else "Disabled"
    source = "Startup session" if session["source"] == "environment" else "Runtime"
    text = (
        f"<b>Session {slot}</b>  {'●' if active else '○'}\n\n"
        f"<b>Account</b>  {_identity(session)}\n"
        f"<b>User ID</b>  <code>{session['user_id'] or 'Unknown'}</code>\n"
        f"<b>Status</b>  {state}\n"
        f"<b>Type</b>  {source}\n"
        f"<b>Active calls</b>  {calls}"
    )
    rows = []
    if active:
        rows.append([
            buttons.ikb(text="Restart", callback_data=f"session restart {slot}"),
            buttons.ikb(
                text="Disable",
                callback_data=f"session disable {slot}",
                style=enums.ButtonStyle.DANGER,
            ),
        ])
    else:
        rows.append([
            buttons.ikb(
                text="Enable",
                callback_data=f"session enable {slot}",
                style=enums.ButtonStyle.SUCCESS,
            )
        ])
    utility = []
    if session["user_id"]:
        utility.append(buttons.ikb(text="Copy ID", copy_text=str(session["user_id"])))
    if session["source"] != "environment":
        utility.append(buttons.ikb(
            text="Remove",
            callback_data=f"session remove {slot}",
            style=enums.ButtonStyle.DANGER,
        ))
    if utility:
        rows.append(utility)
    rows.append([
        buttons.ikb(text="‹ Sessions", callback_data="session page 0"),
        buttons.ikb(text="↻", callback_data=f"session view {slot} 0"),
    ])
    return text, buttons.ikm(rows)


def _remove_confirmation(session: dict) -> tuple[str, types.InlineKeyboardMarkup]:
    slot = session["slot"]
    return (
        lang.languages["en"]["session_remove_confirm"].format(
            slot, _identity(session)
        ),
        buttons.ikm([[
            buttons.ikb(
                text="Remove permanently",
                callback_data=f"session confirm_remove {slot}",
                style=enums.ButtonStyle.DANGER,
            ),
            buttons.ikb(text="Cancel", callback_data=f"session view {slot} 0"),
        ]]),
    )


async def _show_detail(query: types.CallbackQuery, slot: int) -> None:
    session = await db.get_assistant_session(slot)
    if not session:
        await query.answer(query.lang["session_not_found"], show_alert=True)
        text, markup = await _dashboard()
        await query.edit_message_text(text, reply_markup=markup)
        return
    text, markup = _detail(session)
    await query.edit_message_text(text, reply_markup=markup)


@app.on_message(filters.command(["sessions"]) & app.sudoers)
@lang.language()
async def _sessions(_, message: types.Message):
    await open_sessions(message)


@app.on_message(filters.command(["session"]) & app.sudoers)
@lang.language()
async def _session(_, message: types.Message):
    if len(message.command) < 2:
        return await open_sessions(message)
    session = await _find_session(message.command[1])
    if not session:
        return await message.reply_text(message.lang["session_not_found"])
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_sessions(message)
    text, markup = _detail(session)
    await message.reply_text(text, reply_markup=markup, disable_notification=True)


@app.on_callback_query(filters.regex(r"^session(?: |$)") & app.sudoers)
@lang.language()
async def _session_callback(_, query: types.CallbackQuery):
    data = query.data.split()
    action = data[1] if len(data) > 1 else "noop"
    if action == "noop":
        return await query.answer()
    if action == "close":
        await query.answer()
        return await query.message.delete()
    if action == "page":
        page = int(data[2]) if len(data) > 2 else 0
        text, markup = await _dashboard(page)
        return await query.edit_message_text(text, reply_markup=markup)
    if action == "add":
        await query.answer("Send the session string in the private prompt.")
        prompt = await app.send_message(
            query.message.chat.id,
            query.lang["session_add_prompt"],
            reply_markup=types.ForceReply(
                selective=True,
                placeholder=query.lang["session_add_placeholder"],
            ),
        )
        _add_prompts[query.from_user.id] = prompt.id
        return

    try:
        slot = int(data[2])
    except (IndexError, ValueError):
        return await query.answer(query.lang["play_expired"], show_alert=True)
    if action == "view":
        await query.answer()
        return await _show_detail(query, slot)

    session = await db.get_assistant_session(slot)
    if not session:
        return await query.answer(query.lang["session_not_found"], show_alert=True)
    if action == "confirm_remove" and session["source"] == "environment":
        return await query.answer(
            query.lang["session_environment_managed"], show_alert=True
        )
    if action == "remove":
        if session["source"] == "environment":
            return await query.answer(
                query.lang["session_environment_managed"], show_alert=True
            )
        text, markup = _remove_confirmation(session)
        return await query.edit_message_text(text, reply_markup=markup)

    await feedback.toast(query, query.lang["session_working"])
    try:
        if action == "enable":
            await userbot.enable_session(slot)
        elif action == "disable":
            await userbot.disable_session(slot)
        elif action == "restart":
            await userbot.restart_session(slot)
        elif action == "confirm_remove":
            await userbot.disable_session(slot, delete=True)
            text, markup = await _dashboard()
            await query.edit_message_text(text, reply_markup=markup)
            return
        else:
            return await query.answer(query.lang["play_expired"], show_alert=True)
    except Exception as exc:
        detail, markup = _detail(session)
        return await query.edit_message_text(
            detail
            + "\n\n<blockquote expandable><b>Action failed</b>\n"
            + f"{escape(type(exc).__name__)} · "
            + f"{escape(str(exc)[:700] or 'No details')}</blockquote>",
            reply_markup=markup,
        )
    await _show_detail(query, slot)


@app.on_message(filters.private & filters.text & app.sudoers, group=2)
@lang.language()
async def _session_secret_reply(_, message: types.Message):
    if message.text.startswith("/"):
        return
    prompt_id = _add_prompts.get(message.from_user.id)
    reply = message.reply_to_message
    if not prompt_id or not reply or reply.id != prompt_id:
        return
    _add_prompts.pop(message.from_user.id, None)
    session_string = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    await reply.edit_text(message.lang["session_adding"])
    try:
        slot, client = await userbot.add_session(session_string)
    except Exception as exc:
        return await reply.edit_text(
            message.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            ),
            reply_markup=buttons.ikm([[
                buttons.ikb(text="‹ Sessions", callback_data="session page 0")
            ]]),
        )
    session = await db.get_assistant_session(slot)
    text, markup = _detail(session)
    await reply.edit_text(
        message.lang["session_added_short"].format(
            slot,
            f"@{escape(client.username)}" if client.username else escape(client.name),
        ) + "\n\n" + text,
        reply_markup=markup,
    )


async def _require_session(message: types.Message) -> dict | None:
    if len(message.command) < 2:
        await open_sessions(message)
        return None
    session = await _find_session(message.command[1])
    if not session:
        await message.reply_text(message.lang["session_not_found"])
    return session


async def _command_action(message: types.Message, action: str) -> None:
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_sessions(message)
    session = await _require_session(message)
    if not session:
        return
    try:
        if action == "enable":
            await userbot.enable_session(session["slot"])
        elif action == "disable":
            await userbot.disable_session(session["slot"])
        elif action == "restart":
            await userbot.restart_session(session["slot"])
        else:
            return
    except Exception as exc:
        return await message.reply_text(
            message.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    if message.chat.type == enums.ChatType.PRIVATE:
        current = await db.get_assistant_session(session["slot"])
        text, markup = _detail(current)
        await message.reply_text(text, reply_markup=markup)
    else:
        await open_sessions(message)


@app.on_message(filters.command(["addsession"]) & app.sudoers)
@lang.language()
async def _add_session(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_sessions(message)
    if len(message.command) < 2:
        prompt = await message.reply_text(
            message.lang["session_add_prompt"],
            reply_markup=types.ForceReply(
                selective=True,
                placeholder=message.lang["session_add_placeholder"],
            ),
        )
        _add_prompts[message.from_user.id] = prompt.id
        return
    # Keep command compatibility while removing the secret immediately.
    session_string = message.command[1].strip()
    try:
        await message.delete()
    except Exception:
        pass
    status = await app.send_message(message.chat.id, message.lang["session_adding"])
    try:
        slot, _ = await userbot.add_session(session_string)
    except Exception as exc:
        return await status.edit_text(
            message.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    session = await db.get_assistant_session(slot)
    text, markup = _detail(session)
    await status.edit_text(text, reply_markup=markup)


@app.on_message(filters.command(["enablesession"]) & app.sudoers)
@lang.language()
async def _enable_session(_, message: types.Message):
    await _command_action(message, "enable")


@app.on_message(filters.command(["disablesession"]) & app.sudoers)
@lang.language()
async def _disable_session(_, message: types.Message):
    await _command_action(message, "disable")


@app.on_message(filters.command(["restartsession"]) & app.sudoers)
@lang.language()
async def _restart_session(_, message: types.Message):
    await _command_action(message, "restart")


@app.on_message(filters.command(["removesession", "delsession"]) & app.sudoers)
@lang.language()
async def _remove_session(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_sessions(message)
    session = await _require_session(message)
    if not session:
        return
    if session["source"] == "environment":
        return await message.reply_text(message.lang["session_environment_managed"])
    text, markup = _remove_confirmation(session)
    await message.reply_text(text, reply_markup=markup)
