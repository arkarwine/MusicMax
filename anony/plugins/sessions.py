# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import asyncio
from dataclasses import dataclass
from html import escape
from math import ceil
import re

from pyrogram import Client, enums, errors, filters, types

from anony import app, config, db, lang, logger, userbot
from anony.helpers import buttons, feedback, navigate

PAGE_SIZE = 6


@dataclass
class AddFlow:
    prompt_id: int
    page: int
    stage: str
    client: Client | None = None
    phone: str = ""
    phone_code_hash: str = ""
    timeout_task: asyncio.Task | None = None


_add_flows: dict[int, AddFlow] = {}


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
                style=enums.ButtonStyle.DEFAULT,
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
        [buttons.ikb(
            text="➕ Add assistant",
            callback_data=f"session add {page}",
        )],
        [buttons.ikb(text="⬅️ Home", callback_data="help home")],
    ])
    return buttons.ikm(rows)


async def _dashboard(page: int = 0) -> tuple[str, types.InlineKeyboardMarkup]:
    sessions = await db.get_assistant_sessions()
    active = len(userbot.clients)
    text = (
        f"🤖 <b>Assistants</b> · {active} active / {len(sessions)} total\n\n"
        "Choose an account."
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


def _detail(session: dict, page: int = 0) -> tuple[str, types.InlineKeyboardMarkup]:
    slot = session["slot"]
    active = slot in userbot.clients
    calls = len(db.active_chats_for_assistant(slot))
    state = "Active" if active else "Disabled"
    source = " · startup" if session["source"] == "environment" else ""
    text = (
        f"<b>{_identity(session)}</b>\n"
        f"Session {slot} · {state}{source}\n"
        f"<code>{session['user_id'] or 'Unknown'}</code> · {calls} active calls"
    )
    rows = []
    if active:
        rows.append([
            buttons.ikb(
                text="🔄 Restart", callback_data=f"session restart {slot} {page}"
            ),
            buttons.ikb(
                text="⏸ Disable",
                callback_data=f"session disable {slot} {page}",
                style=enums.ButtonStyle.DANGER,
            ),
        ])
    else:
        rows.append([
            buttons.ikb(
                text="▶️ Enable",
                callback_data=f"session enable {slot} {page}",
                style=enums.ButtonStyle.DEFAULT,
            )
        ])
    if session["source"] != "environment":
        rows.append([buttons.ikb(
            text="🗑 Remove",
            callback_data=f"session remove {slot} {page}",
            style=enums.ButtonStyle.DANGER,
        )])
    rows.append([buttons.ikb(
        text="⬅️ Assistants", callback_data=f"session page {page}"
    )])
    return text, buttons.ikm(rows)


def _remove_confirmation(
    session: dict, page: int = 0
) -> tuple[str, types.InlineKeyboardMarkup]:
    slot = session["slot"]
    return (
        lang.languages["en"]["session_remove_confirm"].format(
            slot, _identity(session)
        ),
        buttons.ikm([[
            buttons.ikb(
                text="🗑 Remove permanently",
                callback_data=f"session confirm_remove {slot} {page}",
                style=enums.ButtonStyle.DANGER,
            ),
            buttons.ikb(
                text="⬅️ Keep session",
                callback_data=f"session view {slot} {page}",
            ),
        ]]),
    )


async def _show_detail(
    query: types.CallbackQuery, slot: int, page: int = 0
) -> None:
    session = await db.get_assistant_session(slot)
    if not session:
        await query.answer(query.lang["session_not_found"], show_alert=True)
        text, markup = await _dashboard()
        await navigate(query, text, markup)
        return
    text, markup = _detail(session, page)
    await navigate(query, text, markup)


def _add_method_view(page: int) -> tuple[str, types.InlineKeyboardMarkup]:
    return (
        "➕ <b>Add an assistant</b>\n\nChoose how you want to sign in.",
        buttons.ikm([
            [
                buttons.ikb(
                    text="📱 Phone number",
                    callback_data=f"session add_phone {page}",
                ),
                buttons.ikb(
                    text="🔑 Session string",
                    callback_data=f"session add_string {page}",
                ),
            ],
            [buttons.ikb(
                text="⬅️ Assistants", callback_data=f"session page {page}"
            )],
        ]),
    )


def _detach_add_flow(user_id: int) -> AddFlow | None:
    flow = _add_flows.pop(user_id, None)
    if not flow:
        return None
    if flow.timeout_task and flow.timeout_task is not asyncio.current_task():
        flow.timeout_task.cancel()
    return flow


async def _disconnect_auth_client(client: Client | None) -> None:
    if not client:
        return
    try:
        if client.is_connected:
            await asyncio.wait_for(client.disconnect(), timeout=3)
    except (Exception, asyncio.TimeoutError):
        logger.warning("Temporary phone authentication client did not disconnect cleanly")


async def _clear_add_flow(user_id: int) -> None:
    flow = _detach_add_flow(user_id)
    if not flow:
        return
    if not flow.client:
        return
    await _disconnect_auth_client(flow.client)


async def _expire_add_flow(user_id: int, chat_id: int) -> None:
    await asyncio.sleep(300)
    flow = _add_flows.get(user_id)
    if not flow:
        return
    prompt_id = flow.prompt_id
    page = flow.page
    await _clear_add_flow(user_id)
    try:
        prompt = await app.get_messages(chat_id, prompt_id)
        await prompt.edit_text(
            lang.languages["en"]["session_add_expired"],
            reply_markup=_add_failure_markup(page),
        )
    except Exception:
        pass


async def _send_add_prompt(
    chat_id: int,
    user_id: int,
    page: int,
    stage: str,
    text: str,
    placeholder: str,
) -> None:
    await _clear_add_flow(user_id)
    prompt = await app.send_message(
        chat_id,
        text,
        reply_markup=types.ForceReply(
            selective=True,
            placeholder=placeholder,
        ),
    )
    flow = AddFlow(prompt.id, page, stage)
    _add_flows[user_id] = flow
    flow.timeout_task = asyncio.create_task(
        _expire_add_flow(user_id, chat_id)
    )


async def _replace_force_prompt(
    flow: AddFlow,
    prompt: types.Message,
    chat_id: int,
    text: str,
    placeholder: str,
) -> types.Message:
    """Force Reply only activates on a newly sent message, never an edit."""
    next_prompt = await app.send_message(
        chat_id,
        text,
        reply_markup=types.ForceReply(
            selective=True,
            placeholder=placeholder,
        ),
    )
    flow.prompt_id = next_prompt.id
    try:
        await prompt.delete()
    except Exception:
        pass
    return next_prompt


def _add_failure_markup(page: int) -> types.InlineKeyboardMarkup:
    return buttons.ikm([[
        buttons.ikb(text="🔄 Try again", callback_data=f"session add {page}"),
        buttons.ikb(text="⬅️ Assistants", callback_data=f"session page {page}"),
    ]])


async def _activate_session_string(
    session_string: str,
    prompt: types.Message,
    page: int,
    labels: dict,
    *,
    verified: bool = False,
) -> None:
    chat_id = prompt.chat.id
    try:
        await prompt.delete()
    except Exception:
        pass
    status = await app.send_message(chat_id, labels["session_adding"])
    try:
        slot, client = await userbot.add_session(
            session_string,
            keep_on_failure=verified,
        )
    except Exception as exc:
        saved = next(
            (
                item
                for item in await db.get_assistant_sessions()
                if item["session_string"] == session_string
            ),
            None,
        )
        logger.exception(
            "Assistant session activation failed after %s authentication",
            "verified phone" if verified else "session-string",
        )
        if verified and saved:
            detail, markup = _detail(saved, page)
            await status.edit_text(
                labels["session_saved_inactive"].format(
                    saved["slot"],
                    escape(type(exc).__name__),
                    escape(str(exc)[:700] or "No details"),
                )
                + "\n\n"
                + detail,
                reply_markup=markup,
            )
            return
        await status.edit_text(
            labels["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            ),
            reply_markup=_add_failure_markup(page),
        )
        return
    session = await db.get_assistant_session(slot)
    text, markup = _detail(session, page)
    await status.edit_text(
        labels["session_added_short"].format(
            slot,
            f"@{escape(client.username)}" if client.username else escape(client.name),
        ) + "\n\n" + text,
        reply_markup=markup,
    )


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
    if action == "page":
        try:
            page = int(data[2]) if len(data) > 2 else 0
        except ValueError:
            return await query.answer(query.lang["play_expired"])
        await _clear_add_flow(query.from_user.id)
        text, markup = await _dashboard(page)
        return await navigate(query, text, markup)
    if action == "add":
        try:
            page = int(data[2]) if len(data) > 2 else 0
        except ValueError:
            return await query.answer(query.lang["play_expired"])
        await _clear_add_flow(query.from_user.id)
        text, markup = _add_method_view(page)
        return await navigate(query, text, markup)
    if action in {"add_phone", "add_string"}:
        try:
            page = int(data[2]) if len(data) > 2 else 0
        except ValueError:
            return await query.answer(query.lang["play_expired"])
        await query.answer()
        if action == "add_phone":
            await _send_add_prompt(
                query.message.chat.id,
                query.from_user.id,
                page,
                "phone",
                query.lang["session_phone_prompt"],
                query.lang["session_phone_placeholder"],
            )
            return
        await _send_add_prompt(
            query.message.chat.id,
            query.from_user.id,
            page,
            "string",
            query.lang["session_add_prompt"],
            query.lang["session_add_placeholder"],
        )
        return

    try:
        slot = int(data[2])
    except (IndexError, ValueError):
        return await query.answer(query.lang["play_expired"], show_alert=True)
    try:
        page = int(data[3]) if len(data) > 3 else 0
    except ValueError:
        return await query.answer(query.lang["play_expired"])
    if action == "view":
        return await _show_detail(query, slot, page)

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
        text, markup = _remove_confirmation(session, page)
        return await navigate(query, text, markup)

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
            text, markup = await _dashboard(page)
            await navigate(query, text, markup)
            return
        else:
            return await query.answer(query.lang["play_expired"], show_alert=True)
    except Exception as exc:
        detail, markup = _detail(session, page)
        return await query.edit_message_text(
            detail
            + "\n\n<blockquote expandable><b>Action failed</b>\n"
            + f"{escape(type(exc).__name__)} · "
            + f"{escape(str(exc)[:700] or 'No details')}</blockquote>",
            reply_markup=markup,
        )
    await _show_detail(query, slot, page)


@app.on_message(
    filters.command(["cancel"]) & filters.private & app.sudoers,
    group=1,
)
@lang.language()
async def _cancel_session_add(_, message: types.Message):
    flow = _add_flows.get(message.from_user.id)
    if not flow:
        return
    prompt_id = flow.prompt_id
    page = flow.page
    await _clear_add_flow(message.from_user.id)
    try:
        await message.delete()
    except Exception:
        pass
    prompt = await app.get_messages(message.chat.id, prompt_id)
    await prompt.edit_text(
        message.lang["session_add_cancelled"],
        reply_markup=_add_failure_markup(page),
    )


@app.on_message(filters.private & filters.text & app.sudoers, group=2)
@lang.language()
async def _session_add_reply(_, message: types.Message):
    if message.text.startswith("/"):
        return
    flow = _add_flows.get(message.from_user.id)
    reply = message.reply_to_message
    if not flow or not reply or reply.id != flow.prompt_id:
        return
    value = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass

    if flow.stage == "string":
        _add_flows.pop(message.from_user.id, None)
        return await _activate_session_string(
            value, reply, flow.page, message.lang
        )

    if flow.stage == "phone":
        digits = re.sub(r"\D", "", value)
        if not 7 <= len(digits) <= 15:
            return await _replace_force_prompt(
                flow,
                reply,
                message.chat.id,
                message.lang["session_phone_invalid"],
                message.lang["session_phone_placeholder"],
            )
        phone = f"+{digits}"
        client = Client(
            name=f"AnonyAuth{message.from_user.id}",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            in_memory=True,
        )
        try:
            await client.connect()
            sent = await client.send_code(phone)
        except Exception as exc:
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception:
                pass
            _add_flows.pop(message.from_user.id, None)
            return await reply.edit_text(
                message.lang["session_phone_failed"].format(
                    type(exc).__name__, escape(str(exc)[:500] or "No details")
                ),
                reply_markup=_add_failure_markup(flow.page),
            )
        flow.client = client
        flow.phone = phone
        flow.phone_code_hash = sent.phone_code_hash
        flow.stage = "code"
        return await _replace_force_prompt(
            flow,
            reply,
            message.chat.id,
            message.lang["session_code_prompt"].format(phone),
            message.lang["session_code_placeholder"],
        )

    if flow.stage == "code":
        code = re.sub(r"\D", "", value)
        try:
            signed_in = await flow.client.sign_in(
                flow.phone, flow.phone_code_hash, code
            )
            if not isinstance(signed_in, types.User):
                raise RuntimeError("This phone number has no Telegram account")
        except errors.SessionPasswordNeeded:
            flow.stage = "password"
            return await _replace_force_prompt(
                flow,
                reply,
                message.chat.id,
                message.lang["session_password_prompt"],
                message.lang["session_password_placeholder"],
            )
        except errors.PhoneCodeInvalid as exc:
            return await _replace_force_prompt(
                flow,
                reply,
                message.chat.id,
                message.lang["session_code_invalid"].format(
                    escape(str(exc)[:300] or type(exc).__name__)
                ),
                message.lang["session_code_placeholder"],
            )
        except errors.PhoneCodeExpired as exc:
            await _clear_add_flow(message.from_user.id)
            return await reply.edit_text(
                message.lang["session_phone_failed"].format(
                    type(exc).__name__, escape(str(exc)[:500] or "Code expired")
                ),
                reply_markup=_add_failure_markup(flow.page),
            )
        except Exception as exc:
            await _clear_add_flow(message.from_user.id)
            return await reply.edit_text(
                message.lang["session_phone_failed"].format(
                    type(exc).__name__, escape(str(exc)[:500] or "No details")
                ),
                reply_markup=_add_failure_markup(flow.page),
            )

    elif flow.stage == "password":
        try:
            await flow.client.check_password(value)
        except errors.PasswordHashInvalid:
            return await _replace_force_prompt(
                flow,
                reply,
                message.chat.id,
                message.lang["session_password_invalid"],
                message.lang["session_password_placeholder"],
            )
        except Exception as exc:
            await _clear_add_flow(message.from_user.id)
            return await reply.edit_text(
                message.lang["session_phone_failed"].format(
                    type(exc).__name__, escape(str(exc)[:500] or "No details")
                ),
                reply_markup=_add_failure_markup(flow.page),
            )

    try:
        session_string = await flow.client.export_session_string()
    except Exception as exc:
        await _clear_add_flow(message.from_user.id)
        return await reply.edit_text(
            message.lang["session_phone_failed"].format(
                type(exc).__name__, escape(str(exc)[:500] or "No details")
            ),
            reply_markup=_add_failure_markup(flow.page),
        )
    flow = _detach_add_flow(message.from_user.id) or flow
    try:
        await _activate_session_string(
            session_string,
            reply,
            flow.page,
            message.lang,
            verified=True,
        )
    finally:
        await _disconnect_auth_client(flow.client)


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
        text, markup = _add_method_view(0)
        return await message.reply_text(text, reply_markup=markup)
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
