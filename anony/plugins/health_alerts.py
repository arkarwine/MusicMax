# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.

from pyrogram import filters, types

from anony import app, db, lang


@app.on_message(filters.command(["healthalerts"]) & app.sudoers)
@lang.language()
async def _health_alerts(_, m: types.Message):
    if len(m.command) != 2 or m.command[1].lower() not in {"on", "off"}:
        enabled = await db.health_alerts_enabled(m.from_user.id)
        state = m.lang["health_alerts_on" if enabled else "health_alerts_off"]
        return await m.reply_text(m.lang["health_alerts_usage"].format(state))

    enabled = m.command[1].lower() == "on"
    await db.set_health_alerts(m.from_user.id, enabled)
    await m.reply_text(
        m.lang["health_alerts_enabled" if enabled else "health_alerts_disabled"],
        disable_notification=True,
    )
