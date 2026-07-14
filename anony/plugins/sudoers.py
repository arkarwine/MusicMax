# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


from pyrogram import filters, types

from anony import app, db, lang
from anony.helpers import utils


@app.on_message(filters.command(["addsudo", "delsudo", "rmsudo"]) & filters.user(app.owner))
@lang.language()
async def _sudo(_, m: types.Message):
    user = await utils.extract_user(m)
    if not user:
        return await m.reply_text(m.lang["user_not_found"])
    if user.id == app.owner:
        return await m.reply_text(m.lang["sudo_owner_protected"])

    if m.command[0] == "addsudo":
        if user.id in app.sudoers:
            return await m.reply_text(m.lang["sudo_already"].format(user.mention))

        app.sudoers.add(user.id)
        await db.add_sudo(user.id)
        await app.register_sudo_commands([user.id])
        await m.reply_text(m.lang["sudo_added"].format(user.mention))
    else:
        if user.id not in app.sudoers:
            return await m.reply_text(m.lang["sudo_not"].format(user.mention))

        app.sudoers.discard(user.id)
        await db.del_sudo(user.id)
        try:
            await app.delete_bot_commands(
                scope=types.BotCommandScopeChat(chat_id=user.id)
            )
        except Exception:
            pass
        await m.reply_text(m.lang["sudo_removed"].format(user.mention))


o_mention = None

@app.on_message(filters.command(["listsudo", "sudolist"]) & app.sudoers)
@lang.language()
async def _listsudo(_, m: types.Message):
    global o_mention
    sent = await m.reply_text(m.lang["sudo_fetching"])

    if not o_mention:
        o_mention = (await app.get_users(app.owner)).mention
    rows = [(m.lang["sudo_list_owner"], o_mention)]
    sudoers = await db.get_sudoers()

    for user_id in sudoers:
        try:
            user = (await app.get_users(user_id)).mention
            rows.append((m.lang["sudo_list_member"], user))
        except Exception:
            continue

    lines = [
        f'{m.lang["sudo_list_role"]} · {m.lang["sudo_list_account"]}'
    ]
    for index, (role, account) in enumerate(rows):
        branch = "└" if index == len(rows) - 1 else "├"
        lines.append(f"{branch} {role}: {account}")
    txt = (
        "<b>Sudo access</b>\n\n<blockquote>"
        + "\n".join(lines)
        + "</blockquote>"
    )
    await sent.edit_text(txt)
