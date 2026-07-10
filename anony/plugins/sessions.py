# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from html import escape

from pyrogram import enums, filters, types

from anony import app, config, db, lang, userbot


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


def _session_line(session: dict) -> str:
    slot = session["slot"]
    active = slot in userbot.clients
    state = "active" if active else "disabled"
    identity = (
        f"@{escape(session['username'])}"
        if session["username"]
        else escape(session["display_name"] or "unknown account")
    )
    calls = len(db.active_chats_for_assistant(slot))
    return (
        f"<code>{slot}</code> · {identity} · {state} · "
        f"{calls} active call{'s' if calls != 1 else ''}"
    )


async def _send_chunks(message: types.Message, heading: str, lines: list[str]) -> None:
    chunks = []
    current = heading
    for line in lines:
        addition = f"\n{line}"
        if len(current) + len(addition) > 3800:
            chunks.append(current)
            current = heading + addition
        else:
            current += addition
    chunks.append(current)
    for index, chunk in enumerate(chunks):
        if index == 0:
            await message.reply_text(chunk, disable_notification=True)
        else:
            await app.send_message(
                message.chat.id, chunk, disable_notification=True
            )


@app.on_message(filters.command(["sessions"]) & app.sudoers)
@lang.language()
async def _sessions(_, m: types.Message):
    sessions = await db.get_assistant_sessions()
    lines = [_session_line(session) for session in sessions]
    await _send_chunks(
        m,
        m.lang["sessions_list"].format(
            len(userbot.clients),
            len(sessions) - len(userbot.clients),
            len(sessions),
        ),
        lines,
    )


@app.on_message(filters.command(["session"]) & app.sudoers)
@lang.language()
async def _session(_, m: types.Message):
    if len(m.command) < 2:
        return await m.reply_text(m.lang["session_usage"])
    session = await _find_session(m.command[1])
    if not session:
        return await m.reply_text(m.lang["session_not_found"])
    await m.reply_text(
        m.lang["session_info"].format(
            session["slot"],
            "active" if session["slot"] in userbot.clients else "disabled",
            escape(session["display_name"] or "unknown"),
            f"@{escape(session['username'])}" if session["username"] else "none",
            session["user_id"] or "unknown",
            session["source"],
            len(db.active_chats_for_assistant(session["slot"])),
        ),
        disable_notification=True,
    )


@app.on_message(filters.command(["addsession"]) & app.sudoers)
@lang.language()
async def _add_session(_, m: types.Message):
    if m.chat.type != enums.ChatType.PRIVATE:
        return await m.reply_text(m.lang["session_private_only"])
    if len(m.command) < 2:
        return await m.reply_text(m.lang["addsession_usage"])

    session_string = m.command[1].strip()
    try:
        await m.delete()
    except Exception:
        pass
    status = await app.send_message(m.chat.id, m.lang["session_adding"])
    try:
        slot, client = await userbot.add_session(session_string)
    except Exception as exc:
        return await status.edit_text(
            m.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    await status.edit_text(
        m.lang["session_added"].format(
            slot,
            f"@{client.username}" if client.username else escape(client.name),
            client.id,
        )
    )


async def _require_session(m: types.Message) -> dict | None:
    if len(m.command) < 2:
        await m.reply_text(m.lang["session_usage"])
        return None
    session = await _find_session(m.command[1])
    if not session:
        await m.reply_text(m.lang["session_not_found"])
    return session


@app.on_message(filters.command(["enablesession"]) & app.sudoers)
@lang.language()
async def _enable_session(_, m: types.Message):
    session = await _require_session(m)
    if not session:
        return
    if session["slot"] in userbot.clients:
        return await m.reply_text(m.lang["session_already_active"])
    status = await m.reply_text(m.lang["session_enabling"].format(session["slot"]))
    try:
        client = await userbot.enable_session(session["slot"])
    except Exception as exc:
        return await status.edit_text(
            m.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    await status.edit_text(
        m.lang["session_enabled"].format(
            session["slot"],
            f"@{client.username}" if client.username else escape(client.name),
        )
    )


@app.on_message(filters.command(["disablesession"]) & app.sudoers)
@lang.language()
async def _disable_session(_, m: types.Message):
    session = await _require_session(m)
    if not session:
        return
    if session["slot"] not in userbot.clients:
        return await m.reply_text(m.lang["session_already_disabled"])
    try:
        await userbot.disable_session(session["slot"])
    except Exception as exc:
        return await m.reply_text(
            m.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    await m.reply_text(m.lang["session_disabled"].format(session["slot"]))


@app.on_message(filters.command(["restartsession"]) & app.sudoers)
@lang.language()
async def _restart_session(_, m: types.Message):
    session = await _require_session(m)
    if not session:
        return
    status = await m.reply_text(m.lang["session_restarting"].format(session["slot"]))
    try:
        client = await userbot.restart_session(session["slot"])
    except Exception as exc:
        return await status.edit_text(
            m.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    await status.edit_text(
        m.lang["session_restarted"].format(
            session["slot"],
            f"@{client.username}" if client.username else escape(client.name),
        )
    )


@app.on_message(filters.command(["removesession", "delsession"]) & app.sudoers)
@lang.language()
async def _remove_session(_, m: types.Message):
    session = await _require_session(m)
    if not session:
        return
    if session["session_string"] in config.SESSIONS:
        return await m.reply_text(m.lang["session_environment_managed"])
    try:
        await userbot.disable_session(session["slot"], delete=True)
    except Exception as exc:
        return await m.reply_text(
            m.lang["session_action_failed"].format(
                type(exc).__name__, escape(str(exc)[:700] or "No details")
            )
        )
    await m.reply_text(m.lang["session_removed"].format(session["slot"]))
