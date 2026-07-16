# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import os
import asyncio
from time import monotonic

from pyrogram import errors, filters, types

from anony import app, db, lang


broadcasting = asyncio.Lock()

@app.on_message(filters.command(["broadcast"]) & app.sudoers)
@lang.language()
async def _broadcast(_, message: types.Message):
    if not message.reply_to_message:
        return await message.reply_text(message.lang["gcast_usage"])

    if broadcasting.locked():
        return await message.reply_text(message.lang["gcast_active"])

    msg = message.reply_to_message
    copy = "-copy" in message.command
    album = None
    if msg.media_group_id:
        album = sorted(
            await app.get_media_group(msg.chat.id, msg.id),
            key=lambda item: item.id,
        )
    group_delivered = user_delivered = 0
    group_failed = user_failed = 0
    groups, users = set(), set()

    if "-nochat" not in message.command:
        groups = set(await db.get_chats())
    if "-user" in message.command:
        users = set(await db.get_users())
    group_targets, user_targets = len(groups), len(users)
    total_targets = group_targets + user_targets
    mode = message.lang[
        "gcast_mode_copy" if copy else "gcast_mode_forward"
    ]
    started = monotonic()
    last_progress_edit = started

    def progress_text() -> str:
        total_delivered = group_delivered + user_delivered
        total_failed = group_failed + user_failed
        return message.lang["gcast_start"].format(
            group_targets,
            group_delivered,
            group_failed,
            user_targets,
            user_delivered,
            user_failed,
            total_targets,
            total_delivered,
            total_failed,
            mode,
        )

    sent = await message.reply_text(
        progress_text()
    )


    chats = list(groups | users)
    failed = None

    async with broadcasting:
        for chat in chats:
            delivered = False
            for attempt in range(2):
                try:
                    if album:
                        if copy:
                            await msg.copy_media_group(chat)
                        else:
                            await app.forward_messages(
                                chat_id=chat,
                                from_chat_id=msg.chat.id,
                                message_ids=[item.id for item in album],
                            )
                    elif copy:
                        await msg.copy(chat, reply_markup=msg.reply_markup)
                    else:
                        await msg.forward(chat)
                    delivered = True
                    break
                except errors.FloodWait as fw:
                    if attempt == 0:
                        await asyncio.sleep(fw.value + 1)
                        continue
                    error = fw
                except Exception as ex:
                    error = ex
                    break

            if delivered:
                if chat in groups:
                    group_delivered += 1
                else:
                    user_delivered += 1
                await asyncio.sleep(0.2)
            else:
                if chat in groups:
                    group_failed += 1
                else:
                    user_failed += 1
                if not failed:
                    failed = open("errors.txt", "w")
                failed.write(f"{chat} - {error}\n")
            processed = (
                group_delivered + user_delivered
                + group_failed + user_failed
            )
            now = monotonic()
            if processed < total_targets and (
                processed % 25 == 0 or now - last_progress_edit >= 5
            ):
                try:
                    await sent.edit_text(progress_text())
                except Exception:
                    pass
                last_progress_edit = now

    total_delivered = group_delivered + user_delivered
    total_failed = group_failed + user_failed
    elapsed = max(monotonic() - started, 0)
    text = message.lang["gcast_end"].format(
        group_targets,
        group_delivered,
        group_failed,
        user_targets,
        user_delivered,
        user_failed,
        total_targets,
        total_delivered,
        total_failed,
        mode,
        f"{elapsed:.1f}s",
    )
    if failed:
        failed.close()
        await message.reply_document(
            document="errors.txt",
            caption=message.lang["gcast_errors"].format(total_failed),
        )
        try:
            os.remove("errors.txt")
        except OSError:
            pass

    await sent.edit_text(text)
