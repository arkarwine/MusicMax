# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from html import escape

from pyrogram import enums, filters, types

from anony import app, config, db, lang
from anony.helpers import buttons, feedback

BOOLEAN_KEYS = ("auto_leave", "auto_end", "thumb_gen", "video_play")
LABELS = {
    "duration_limit": "Track limit (minutes)",
    "queue_limit": "Queue limit",
    "playlist_limit": "Playlist limit",
    "support_channel": "Channel",
    "support_chat": "Support group",
    "auto_leave": "Auto leave",
    "auto_end": "Auto end",
    "thumb_gen": "Generated artwork",
    "video_play": "Video playback",
    "lang_code": "Default language",
    "default_thumb": "Default artwork",
    "ping_img": "Stats artwork",
    "start_img": "Start artwork",
}


async def _runtime_view() -> tuple[str, types.InlineKeyboardMarkup]:
    overrides = await db.get_runtime_config()
    lines = []
    for key in config.RUNTIME_FIELDS:
        marker = " •" if key in overrides else ""
        lines.append(
            f"<b>{LABELS[key]}</b>{marker}\n"
            f"<code>{escape(config.runtime_display(key))}</code>"
        )
    text = (
        "⚙️ <b>Runtime configuration</b>\n\n"
        + "\n\n".join(lines)
        + "\n\n<blockquote>• runtime override\n"
        "Use <code>/setconfig key value</code> to change a value.\n"
        "Use <code>/resetconfig key</code> to restore its environment default.</blockquote>"
    )
    rows = []
    for index in range(0, len(BOOLEAN_KEYS), 2):
        row = []
        for key in BOOLEAN_KEYS[index : index + 2]:
            row.append(buttons.ikb(
                text=f"{LABELS[key]} · {config.runtime_display(key).title()}",
                callback_data=f"runtime_config toggle {key}",
            ))
        rows.append(row)
    rows.append([buttons.ikb(text="⬅️ Home", callback_data="help home")])
    return text, buttons.ikm(rows)


async def open_runtime_config(message: types.Message) -> None:
    if not message.from_user or message.from_user.id not in app.sudoers:
        await message.reply_text("🔒 Runtime configuration is sudo-only.")
        return
    if message.chat.type != enums.ChatType.PRIVATE:
        await message.reply_text(
            "🔐 Open runtime configuration privately.",
            reply_markup=buttons.ikm([[
                buttons.ikb(
                    text="⚙️ Open configuration",
                    url=f"https://t.me/{app.username}?start=runtime_config",
                )
            ]]),
        )
        return
    text, markup = await _runtime_view()
    await message.reply_text(text, reply_markup=markup, disable_notification=True)


@app.on_message(filters.command(["config", "runtimeconfig"]) & app.sudoers)
@lang.language()
async def _config(_, message: types.Message):
    await open_runtime_config(message)


@app.on_message(filters.command(["setconfig"]) & app.sudoers)
@lang.language()
async def _set_config(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_runtime_config(message)
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        return await message.reply_text(
            "Usage: <code>/setconfig key value</code>\n"
            f"Keys: <code>{', '.join(config.RUNTIME_FIELDS)}</code>"
        )
    key, raw_value = parts[1].lower(), parts[2]
    try:
        stored = config.set_runtime(key, raw_value)
    except KeyError:
        return await message.reply_text("🔎 That runtime setting doesn't exist.")
    except (TypeError, ValueError) as exc:
        return await message.reply_text(f"⚠️ {escape(str(exc))}")
    await db.set_runtime_config(key, stored)
    text, markup = await _runtime_view()
    await message.reply_text(
        f"✅ <b>{LABELS[key]} updated immediately.</b>\n\n{text}",
        reply_markup=markup,
    )


@app.on_message(filters.command(["resetconfig"]) & app.sudoers)
@lang.language()
async def _reset_config(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_runtime_config(message)
    if len(message.command) < 2:
        return await message.reply_text("Usage: <code>/resetconfig key</code>")
    key = message.command[1].lower()
    if key == "all":
        for item in config.RUNTIME_FIELDS:
            config.reset_runtime(item)
            await db.reset_runtime_config(item)
        label = "All runtime settings"
    else:
        try:
            config.reset_runtime(key)
        except KeyError:
            return await message.reply_text("🔎 That runtime setting doesn't exist.")
        await db.reset_runtime_config(key)
        label = LABELS[key]
    text, markup = await _runtime_view()
    await message.reply_text(
        f"↩️ <b>{label} restored.</b>\n\n{text}",
        reply_markup=markup,
    )


@app.on_callback_query(filters.regex(r"^runtime_config ") & app.sudoers)
@lang.language()
async def _runtime_config_callback(_, query: types.CallbackQuery):
    data = query.data.split()
    if len(data) != 3 or data[1] != "toggle" or data[2] not in BOOLEAN_KEYS:
        return await query.answer("This control has expired.")
    key = data[2]
    stored = config.set_runtime(
        key,
        "off" if config.runtime_display(key) == "on" else "on",
    )
    await db.set_runtime_config(key, stored)
    await feedback.toast(query, "✅ Updated immediately")
    text, markup = await _runtime_view()
    await query.edit_message_text(text, reply_markup=markup)
