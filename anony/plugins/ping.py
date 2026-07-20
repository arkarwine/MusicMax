# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import time
import psutil

from pyrogram import filters, types
from anony import app, anon, boot, config, db, lang, userbot
from anony.helpers import buttons


@app.on_message(filters.private & filters.command(["__watchdog_probe"]), group=-20)
async def _watchdog_probe(_, m: types.Message):
    assistant_ids = {
        getattr(client, "id", None) for client in userbot.clients.values()
    }
    sender_id = getattr(getattr(m, "from_user", None), "id", None)
    if sender_id not in assistant_ids:
        return
    nonce = m.command[1] if len(getattr(m, "command", [])) > 1 else ""
    await db.set_runtime_health_values({
        "assistant_probe_seen_at": int(time.time()),
        "assistant_probe_seen_nonce": nonce,
        "assistant_probe_seen_sender": sender_id,
    })


@app.on_message(filters.command(["alive", "ping"]) & ~app.bl_users)
@lang.language()
async def _ping(_, m: types.Message):
    start = time.time()
    sent = await m.reply_text(m.lang["pinging"])
    elapsed = int(time.time() - boot)
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{hours:02d}h:{minutes:02d}m:{seconds:02d}s"
    if days:
        uptime = f"{days} days, {uptime}"
    latency = round((time.time() - start) * 1000, 2)
    caption = m.lang["ping_user"].format(latency, uptime)
    if m.from_user and m.from_user.id in app.sudoers:
        caption += m.lang["ping_sudo_detail"].format(
            psutil.cpu_percent(interval=0),
            psutil.virtual_memory().percent,
            psutil.disk_usage("/").percent,
            await anon.ping(),
            len(db.active_calls),
        )
    await sent.edit_media(
        media=types.InputMediaPhoto(
            media=config.PING_IMG,
            caption=caption,
        ),
        reply_markup=buttons.ping_markup(m.lang["support"]),
    )
