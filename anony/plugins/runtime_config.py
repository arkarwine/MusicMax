# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import asyncio
from dataclasses import dataclass
from html import escape
from time import monotonic

from pyrogram import enums, filters, types
from pyrogram.errors import BadRequest

from anony import app, config, db, lang, logger
from anony.helpers import buttons, feedback
from anony.ui import callbacks
from anony.ui.keyboards import home_row


@dataclass(frozen=True, slots=True)
class SettingSpec:
    label: str
    category: str
    description: str
    accepted: str
    example: str
    boolean: bool = False


@dataclass(slots=True)
class ConfigView:
    rich: str
    fallback: str
    markup: types.InlineKeyboardMarkup


@dataclass(slots=True)
class PendingEdit:
    prompt_id: int
    key: str
    category: str
    created_at: float
    timeout_task: asyncio.Task | None = None


CATEGORIES = {
    "playback": ("🎧", "Playback", "Playback limits, media and controls"),
    "messages": ("💬", "Messages", "Play-card copy and external action"),
    "automation": ("⚡", "Automation", "Hands-free behavior and defaults"),
    "appearance": ("🖼️", "Appearance", "Artwork used across bot surfaces"),
}

SETTINGS = {
    "duration_limit": SettingSpec(
        "Track limit", "playback", "Maximum length accepted for one track.",
        "1–1440 minutes", "60",
    ),
    "queue_limit": SettingSpec(
        "Queue limit", "playback", "Maximum queued tracks per chat.",
        "1–1000 tracks", "20",
    ),
    "playlist_limit": SettingSpec(
        "Playlist limit", "playback", "Maximum tracks imported at once.",
        "1–1000 tracks", "20",
    ),
    "thumb_gen": SettingSpec(
        "Generated artwork", "playback",
        "Create a track-specific thumbnail for play cards.",
        "on or off", "on", True,
    ),
    "video_play": SettingSpec(
        "Video playback", "playback", "Allow video streams when requested.",
        "on or off", "on", True,
    ),
    "play_image": SettingSpec(
        "Play cover", "playback",
        "Override the first play-card image; generated artwork remains second.",
        "HTTP(S), @username, or - to disable",
        "https://example.com/cover.jpg",
    ),
    "play_controls_layout": SettingSpec(
        "Play controls", "playback",
        "Choose control order, rows and omitted controls.",
        "loop, stop, pause, skip, replay; comma = row, | = new row, - = hide",
        "pause,skip|stop",
    ),
    "play_button_text": SettingSpec(
        "Button text", "messages",
        "Play-card link label; both text and link are required.",
        "up to 64 characters, or - to disable", "Open channel",
    ),
    "play_button_url": SettingSpec(
        "Button link", "messages",
        "Play-card button destination; both text and link are required.",
        "HTTP(S), @username, or - to disable", "@anonxmusic",
    ),
    "play_message_template_en": SettingSpec(
        "English template", "messages",
        "Markdown template for English play cards.",
        "Markdown with title, link, duration, requester and source placeholders",
        "# Now playing",
    ),
    "play_message_template_my": SettingSpec(
        "Burmese template", "messages",
        "Markdown template for Burmese play cards.",
        "Markdown with title, link, duration, requester and source placeholders",
        "# Now playing",
    ),
    "auto_leave": SettingSpec(
        "Auto leave", "automation",
        "Leave the voice chat after playback becomes idle.",
        "on or off", "off", True,
    ),
    "auto_end": SettingSpec(
        "Auto end", "automation",
        "End an idle group voice chat when permitted.",
        "on or off", "off", True,
    ),
    "lang_code": SettingSpec(
        "Default language", "automation",
        "Language used by chats without a saved preference.",
        "en or my", "en",
    ),
    "support_channel": SettingSpec(
        "Channel", "automation", "Primary updates or support channel.",
        "HTTP(S) or @username", "@anonxmusic",
    ),
    "support_chat": SettingSpec(
        "Support group", "automation", "Community support destination.",
        "HTTP(S) or @username", "@anonxsupport",
    ),
    "default_thumb": SettingSpec(
        "Default artwork", "appearance",
        "Fallback image when a track has no artwork.",
        "complete HTTP(S) URL", "https://example.com/default.jpg",
    ),
    "ping_img": SettingSpec(
        "Stats artwork", "appearance", "Image used by status and stats cards.",
        "complete HTTP(S) URL", "https://example.com/stats.jpg",
    ),
    "start_img": SettingSpec(
        "Start artwork", "appearance", "Optional image on the start screen.",
        "complete HTTP(S) URL, or - to disable",
        "https://example.com/start.jpg",
    ),
}

BOOLEAN_KEYS = tuple(key for key, spec in SETTINGS.items() if spec.boolean)
TEMPLATE_KEYS = (
    "play_message_template_en",
    "play_message_template_my",
)
LABELS = {key: spec.label for key, spec in SETTINGS.items()}
_PENDING_EDITS: dict[int, PendingEdit] = {}
_CONFIG_LOCK = asyncio.Lock()
EDIT_TIMEOUT = 300

_SMALL_CAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ",
    "f": "ꜰ", "g": "ɢ", "h": "ʜ", "i": "ɪ", "j": "ᴊ",
    "k": "ᴋ", "l": "ʟ", "m": "ᴍ", "n": "ɴ", "o": "ᴏ",
    "p": "ᴘ", "q": "q", "r": "ʀ", "s": "ꜱ", "t": "ᴛ",
    "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x", "y": "ʏ",
    "z": "ᴢ",
}


def _small_caps_title(value: str) -> str:
    words = []
    for word in value.split(" "):
        if not word:
            words.append(word)
            continue
        words.append(
            word[0].upper()
            + "".join(_SMALL_CAPS.get(char.lower(), char) for char in word[1:])
        )
    return " ".join(words)


def _category_keys(category: str) -> tuple[str, ...]:
    return tuple(
        key for key, spec in SETTINGS.items() if spec.category == category
    )


def _short_value(key: str, limit: int = 34) -> str:
    value = config.runtime_display(key) or "disabled"
    if key == "duration_limit" and value.isdigit():
        value = f"{value} min"
    if key == "play_controls_layout" and value != "disabled":
        value = value.replace(",", " · ").replace("|", " / ")
    if len(value) > limit:
        return value[: limit - 1].rstrip() + "…"
    return value


def _source(key: str, overrides: dict[str, str]) -> str:
    return "Custom" if key in overrides else "Default"


def _header(icon: str, title: str) -> str:
    return (
        '<table><tr><th align="center">'
        f"{icon} {escape(_small_caps_title(title))}"
        "</th></tr></table>"
    )


def _overview_markup() -> types.InlineKeyboardMarkup:
    rows = []
    category_items = list(CATEGORIES.items())
    for index in range(0, len(category_items), 2):
        row = []
        for key, (icon, label, _) in category_items[index:index + 2]:
            row.append(buttons.ikb(
                text=f"{icon} {label}",
                callback_data=callbacks.runtime_config("category", key),
            ))
        rows.append(row)
    rows.append([
        buttons.ikb(
            text="🔄 Refresh",
            callback_data=callbacks.runtime_config("home", "root"),
        ),
        buttons.ikb(
            text="↩️ Reset all",
            callback_data=callbacks.runtime_config("confirm_all", "all"),
        ),
    ])
    rows.append(home_row("⬅️ Home", callbacks.HELP_HOME))
    return buttons.ikm(rows)


async def _overview_view() -> ConfigView:
    overrides = await db.get_runtime_config()
    rows = ["<tr><th>Section</th><th>Settings</th><th>Custom</th></tr>"]
    fallback_rows = []
    for category, (icon, label, _) in CATEGORIES.items():
        keys = _category_keys(category)
        custom = sum(key in overrides for key in keys)
        rows.append(
            f"<tr><td>{icon} {escape(label)}</td>"
            f'<td align="center">{len(keys)}</td>'
            f'<td align="center">{custom}</td></tr>'
        )
        fallback_rows.append(
            f"{icon} <b>{label}</b> · {custom}/{len(keys)} custom"
        )
    rich = (
        _header("⚙️", "Runtime configuration")
        + '<table bordered striped>' + "".join(rows) + "</table>"
        + "<blockquote>Changes apply immediately · Custom values are saved</blockquote>"
    )
    fallback = (
        f"⚙️ <b>{_small_caps_title('Runtime configuration')}</b>\n\n"
        + "\n".join(fallback_rows)
        + "\n\n<blockquote>Changes apply immediately · "
        "Custom values are saved</blockquote>"
    )
    return ConfigView(rich, fallback, _overview_markup())


def _category_markup(
    category: str,
    overrides: dict[str, str],
) -> types.InlineKeyboardMarkup:
    rows = []
    keys = _category_keys(category)
    for index in range(0, len(keys), 2):
        row = []
        for key in keys[index:index + 2]:
            marker = " •" if key in overrides else ""
            row.append(buttons.ikb(
                text=f"{SETTINGS[key].label}{marker}",
                callback_data=callbacks.runtime_config("view", key),
            ))
        rows.append(row)
    rows.append([
        buttons.ikb(
            text="🔄 Refresh",
            callback_data=callbacks.runtime_config("category", category),
        ),
        buttons.ikb(
            text="⬅️ Overview",
            callback_data=callbacks.runtime_config("home", "root"),
        ),
    ])
    return buttons.ikm(rows)


async def _category_view(category: str) -> ConfigView:
    icon, label, description = CATEGORIES[category]
    overrides = await db.get_runtime_config()
    rows = ["<tr><th>Setting</th><th>Value</th><th>Source</th></tr>"]
    fallback_rows = []
    for key in _category_keys(category):
        value = _short_value(key)
        source = _source(key, overrides)
        rows.append(
            f"<tr><td>{escape(SETTINGS[key].label)}</td>"
            f'<td align="center"><code>{escape(value)}</code></td>'
            f'<td align="center">{source}</td></tr>'
        )
        fallback_rows.append(
            f"<b>{SETTINGS[key].label}</b> · "
            f"<code>{escape(value)}</code> · {source}"
        )
    rich = (
        _header(icon, label)
        + f"<blockquote>{escape(description)}</blockquote>"
        + '<table bordered striped>' + "".join(rows) + "</table>"
    )
    fallback = (
        f"{icon} <b>{escape(label)}</b>\n"
        f"<blockquote>{escape(description)}</blockquote>\n\n"
        + "\n".join(fallback_rows)
    )
    return ConfigView(
        rich,
        fallback,
        _category_markup(category, overrides),
    )


def _setting_markup(
    key: str,
    category: str,
    overrides: dict[str, str],
) -> types.InlineKeyboardMarkup:
    spec = SETTINGS[key]
    rows = []
    if spec.boolean:
        enabled = config.runtime_display(key) == "on"
        rows.append([buttons.ikb(
            text="⏸ Turn off" if enabled else "▶️ Turn on",
            callback_data=callbacks.runtime_config("toggle", key),
        )])
    else:
        rows.append([buttons.ikb(
            text="✏️ Change value",
            callback_data=callbacks.runtime_config("edit", key),
        )])
    if key in TEMPLATE_KEYS:
        rows.append([buttons.ikb(
            text="📄 View template",
            callback_data=callbacks.runtime_config("template", key),
        )])
    if key in overrides:
        rows.append([buttons.ikb(
            text="↩️ Restore default",
            callback_data=callbacks.runtime_config("reset", key),
        )])
    rows.append([
        buttons.ikb(
            text=f"⬅️ {CATEGORIES[category][1]}",
            callback_data=callbacks.runtime_config("category", category),
        ),
        buttons.ikb(
            text="⚙️ Overview",
            callback_data=callbacks.runtime_config("home", "root"),
        ),
    ])
    return buttons.ikm(rows)


async def _setting_view(key: str) -> ConfigView:
    spec = SETTINGS[key]
    overrides = await db.get_runtime_config()
    current = _short_value(key, 120)
    source = _source(key, overrides)
    rich = (
        _header("⚙️", spec.label)
        + "<table bordered striped>"
        + "<tr><th>Property</th><th>Value</th></tr>"
        + f'<tr><td>Current</td><td align="center"><code>{escape(current)}</code></td></tr>'
        + f'<tr><td>Source</td><td align="center">{source}</td></tr>'
        + f'<tr><td>Key</td><td align="center"><code>{key}</code></td></tr>'
        + "</table>"
        + f"<blockquote>{escape(spec.description)}</blockquote>"
        + f"<b>Accepted</b> · {escape(spec.accepted)}<br>"
        + f"<b>Example</b> · <code>{escape(spec.example)}</code>"
    )
    fallback = (
        f"⚙️ <b>{escape(spec.label)}</b>\n\n"
        f"<b>Current</b> · <code>{escape(current)}</code>\n"
        f"<b>Source</b> · {source}\n"
        f"<b>Key</b> · <code>{key}</code>\n\n"
        f"<blockquote>{escape(spec.description)}</blockquote>\n"
        f"<b>Accepted</b> · {escape(spec.accepted)}\n"
        f"<b>Example</b> · <code>{escape(spec.example)}</code>"
    )
    return ConfigView(
        rich,
        fallback,
        _setting_markup(key, spec.category, overrides),
    )


def _effective_template(key: str) -> tuple[str, str]:
    lang_code = "my" if key.endswith("_my") else "en"
    configured = config.play_message_template(lang_code)
    if configured:
        return configured, "Runtime override"
    return lang.languages[lang_code]["play_message_template"], "Built-in default"


async def _template_view(key: str) -> ConfigView:
    spec = SETTINGS[key]
    overrides = await db.get_runtime_config()
    template, source = _effective_template(key)
    if key not in overrides and config.play_message_template(
        "my" if key.endswith("_my") else "en"
    ):
        source = "Environment"
    encoded = escape(template)
    rich = (
        _header("📄", spec.label)
        + f"<blockquote>{source} · {len(template)} characters</blockquote>"
        + f"<pre>{encoded}</pre>"
    )
    fallback = (
        f"📄 <b>{escape(_small_caps_title(spec.label))}</b>\n"
        f"<blockquote>{source} · {len(template)} characters</blockquote>\n\n"
        f"<pre>{encoded}</pre>"
    )
    rows = [[
        buttons.ikb(
            text="✏️ Change template",
            callback_data=callbacks.runtime_config("edit", key),
        )
    ]]
    if key in overrides:
        rows.append([buttons.ikb(
            text="↩️ Restore default",
            callback_data=callbacks.runtime_config("reset", key),
        )])
    rows.append([
        buttons.ikb(
            text="⬅️ Details",
            callback_data=callbacks.runtime_config("view", key),
        ),
        buttons.ikb(
            text="💬 Messages",
            callback_data=callbacks.runtime_config("category", "messages"),
        ),
    ])
    return ConfigView(rich, fallback, buttons.ikm(rows))


def _reset_all_view() -> ConfigView:
    rich = (
        _header("↩️", "Reset all settings?")
        + "<blockquote>This removes every runtime override and restores "
        "environment defaults immediately.</blockquote>"
    )
    fallback = (
        "↩️ <b>Reset all settings?</b>\n\n"
        "<blockquote>This removes every runtime override and restores "
        "environment defaults immediately.</blockquote>"
    )
    markup = buttons.ikm([[
        buttons.ikb(
            text="Reset all",
            callback_data=callbacks.runtime_config("reset_all", "all"),
            style=enums.ButtonStyle.DANGER,
        ),
        buttons.ikb(
            text="Cancel",
            callback_data=callbacks.runtime_config("home", "root"),
        ),
    ]])
    return ConfigView(rich, fallback, markup)


async def _send_view(message: types.Message, view: ConfigView) -> None:
    sent = await app.rich_messages.send(
        message.chat.id,
        {"html": view.rich},
        fallback_text=view.fallback,
        reply_markup=view.markup,
        reply_parameters={"message_id": message.id},
        disable_notification=True,
    )
    if sent is None:
        await message.reply_text(
            view.fallback,
            reply_markup=view.markup,
            disable_notification=True,
        )


async def _edit_view(query: types.CallbackQuery, view: ConfigView) -> None:
    sent = await app.rich_messages.edit(
        query.message.chat.id,
        query.message.id,
        {"html": view.rich},
        fallback_text=view.fallback,
        reply_markup=view.markup,
    )
    if sent is not None:
        return
    try:
        await query.edit_message_text(view.fallback, reply_markup=view.markup)
    except BadRequest as exc:
        if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
            raise


def _setting_input_text(message: types.Message, key: str) -> str:
    text = message.text
    if not text or key not in TEMPLATE_KEYS:
        return str(text or "")
    try:
        markdown = text.markdown
    except Exception:
        logger.debug("Could not reconstruct Markdown entities", exc_info=True)
        return str(text)
    return markdown if isinstance(markdown, str) else str(text)


async def _validate_and_store(key: str, raw_value: str) -> str:
    async with _CONFIG_LOCK:
        attr = config.RUNTIME_FIELDS[key]
        previous = getattr(config, attr)
        stored = config.set_runtime(key, raw_value)
        normalized = getattr(config, attr)
        setattr(config, attr, previous)
        await db.set_runtime_config(key, stored)
        setattr(config, attr, normalized)
        return stored


async def _restore_setting(key: str) -> None:
    async with _CONFIG_LOCK:
        await db.reset_runtime_config(key)
        config.reset_runtime(key)


async def _toggle_setting(key: str) -> None:
    async with _CONFIG_LOCK:
        raw_value = "off" if config.runtime_display(key) == "on" else "on"
        attr = config.RUNTIME_FIELDS[key]
        previous = getattr(config, attr)
        stored = config.set_runtime(key, raw_value)
        normalized = getattr(config, attr)
        setattr(config, attr, previous)
        await db.set_runtime_config(key, stored)
        setattr(config, attr, normalized)


async def _restore_all() -> None:
    async with _CONFIG_LOCK:
        await db.reset_all_runtime_config()
        for key in config.RUNTIME_FIELDS:
            config.reset_runtime(key)


async def _clear_pending(user_id: int) -> PendingEdit | None:
    pending = _PENDING_EDITS.pop(user_id, None)
    if pending and pending.timeout_task is not asyncio.current_task():
        pending.timeout_task.cancel()
    return pending


async def _expire_edit(user_id: int, chat_id: int, prompt_id: int) -> None:
    await asyncio.sleep(EDIT_TIMEOUT)
    pending = _PENDING_EDITS.get(user_id)
    if pending is None or pending.prompt_id != prompt_id:
        return
    _PENDING_EDITS.pop(user_id, None)
    try:
        prompt = await app.get_messages(chat_id, prompt_id)
        await prompt.edit_text(
            "⌛ This configuration request expired.",
            reply_markup=buttons.ikm([[
                buttons.ikb(
                    text="⚙️ Open configuration",
                    callback_data=callbacks.runtime_config("home", "root"),
                )
            ]]),
        )
    except Exception:
        logger.debug("Could not expire configuration prompt", exc_info=True)


async def _prompt_edit(
    chat_id: int,
    user_id: int,
    key: str,
    *,
    error: str | None = None,
) -> None:
    await _clear_pending(user_id)
    spec = SETTINGS[key]
    current = _short_value(key, 80)
    prefix = f"⚠️ {escape(error)}\n\n" if error else ""
    prompt = await app.send_message(
        chat_id,
        prefix
        + f"✏️ <b>Change {escape(spec.label)}</b>\n\n"
        + f"Current · <code>{escape(current)}</code>\n"
        + f"Accepted · {escape(spec.accepted)}\n"
        + f"Example · <code>{escape(spec.example)}</code>\n\n"
        + "Reply with the new value within 5 minutes. "
        + "Reply with cancel to stop.",
        reply_markup=types.ForceReply(
            placeholder=f"New {spec.label.lower()}",
        ),
    )
    pending = PendingEdit(prompt.id, key, spec.category, monotonic())
    _PENDING_EDITS[user_id] = pending
    pending.timeout_task = asyncio.create_task(
        _expire_edit(user_id, chat_id, prompt.id)
    )


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
    await _send_view(message, await _overview_view())


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
        return await _send_view(message, await _overview_view())
    key = parts[1].lower()
    if key not in SETTINGS:
        return await message.reply_text(
            "🔎 That setting doesn't exist. Open /config to browse available settings."
        )
    raw_value = _setting_input_text(message, key).split(maxsplit=2)[2]
    try:
        await _validate_and_store(key, raw_value)
    except (TypeError, ValueError) as exc:
        return await message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Could not persist runtime setting %s", key)
        return await message.reply_text(
            "⚠️ The setting could not be saved. No change was applied."
        )
    await _send_view(message, await _setting_view(key))


@app.on_message(filters.command(["resetconfig"]) & app.sudoers)
@lang.language()
async def _reset_config(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_runtime_config(message)
    if len(message.command) < 2:
        return await _send_view(message, await _overview_view())
    key = message.command[1].lower()
    try:
        if key == "all":
            return await _send_view(message, _reset_all_view())
        if key not in SETTINGS:
            return await message.reply_text(
                "🔎 That setting doesn't exist. Open /config to browse available settings."
            )
        await _restore_setting(key)
    except Exception:
        logger.exception("Could not restore runtime setting %s", key)
        return await message.reply_text(
            "⚠️ The setting could not be restored. Please try again."
        )
    await _send_view(message, await _setting_view(key))


@app.on_message(filters.private & filters.reply & app.sudoers, group=2)
async def _runtime_config_reply(_, message: types.Message):
    pending = _PENDING_EDITS.get(message.from_user.id)
    reply = message.reply_to_message
    if pending is None or reply is None or reply.id != pending.prompt_id:
        return
    await _clear_pending(message.from_user.id)
    if message.text and message.text.strip().lower() == "cancel":
        return await message.reply_text(
            "Cancelled.", disable_notification=True
        )
    if not message.text:
        return await _prompt_edit(
            message.chat.id,
            message.from_user.id,
            pending.key,
            error="Send a text value.",
        )
    raw_value = _setting_input_text(message, pending.key)
    try:
        await _validate_and_store(pending.key, raw_value)
    except (TypeError, ValueError) as exc:
        return await _prompt_edit(
            message.chat.id,
            message.from_user.id,
            pending.key,
            error=str(exc),
        )
    except Exception:
        logger.exception("Could not persist runtime setting %s", pending.key)
        return await message.reply_text(
            "⚠️ The setting could not be saved. No change was applied."
        )
    await _send_view(message, await _setting_view(pending.key))


@app.on_callback_query(filters.regex(r"^runtime_config ") & app.sudoers)
@lang.language()
async def _runtime_config_callback(_, query: types.CallbackQuery):
    data = query.data.split()
    if len(data) != 3:
        return await query.answer("This control has expired.", show_alert=True)
    action, target = data[1], data[2]

    if action == "home":
        await query.answer()
        return await _edit_view(query, await _overview_view())
    if action == "category" and target in CATEGORIES:
        await query.answer()
        return await _edit_view(query, await _category_view(target))
    if action == "view" and target in SETTINGS:
        await query.answer()
        return await _edit_view(query, await _setting_view(target))
    if action == "template" and target in TEMPLATE_KEYS:
        await query.answer()
        return await _edit_view(query, await _template_view(target))
    if action == "edit" and target in SETTINGS:
        await query.answer("Reply with the new value")
        return await _prompt_edit(
            query.message.chat.id,
            query.from_user.id,
            target,
        )
    if action == "confirm_all":
        await query.answer()
        return await _edit_view(query, _reset_all_view())

    try:
        if action == "toggle" and target in BOOLEAN_KEYS:
            await _toggle_setting(target)
            await feedback.toast(query, "Updated immediately")
            return await _edit_view(query, await _setting_view(target))
        if action == "reset" and target in SETTINGS:
            await _restore_setting(target)
            await feedback.toast(query, "Default restored")
            return await _edit_view(query, await _setting_view(target))
        if action == "reset_all" and target == "all":
            await _restore_all()
            await feedback.toast(query, "All defaults restored")
            return await _edit_view(query, await _overview_view())
    except Exception:
        logger.exception("Runtime configuration action failed: %s", action)
        return await query.answer(
            "The change could not be saved. Nothing was changed.",
            show_alert=True,
        )
    await query.answer("This control has expired.", show_alert=True)
