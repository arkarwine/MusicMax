# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

import asyncio
from dataclasses import dataclass
from html import escape
from time import monotonic

from pyrogram import enums, filters, types
from pyrogram.errors import BadRequest

from anony import app, config, lang, logger, supervisor, themes
from anony.helpers import buttons, feedback
from anony.ui import callbacks
from anony.core.rich_messages import themed_emoji_token
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
    "playback": ("🎧", "Playback", "Music limits, video and player controls"),
    "messages": ("💬", "Play card", "Now-playing text and optional link button"),
    "start": ("🏠", "Start menu", "Welcome buttons, order and labels"),
    "automation": ("⚡", "Behavior", "Automatic actions, language and community links"),
    "appearance": ("🖼️", "Images", "Pictures shown across the bot"),
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
        "Markdown with image, title, link, duration, requester and source placeholders",
        "# Now playing",
    ),
    "play_message_template_my": SettingSpec(
        "Burmese template", "messages",
        "Markdown template for Burmese play cards.",
        "Markdown with image, title, link, duration, requester and source placeholders",
        "# Now playing",
    ),
    "start_buttons_layout": SettingSpec(
        "Start buttons", "start",
        "Choose start-menu button order, rows and hidden buttons.",
        "add, help, language, stats, trending, support, channel, owner; comma = row, | = new row, - = hide",
        "add|help,language,stats|support,channel|owner",
    ),
    "start_add_text": SettingSpec(
        "Add button", "start", "Custom Add to Group button label.",
        "up to 64 characters, or - for default", "➕ Add to Group",
    ),
    "start_help_text": SettingSpec(
        "Help button", "start", "Custom Help button label.",
        "up to 64 characters, or - for default", "Help",
    ),
    "start_language_text": SettingSpec(
        "Language button", "start", "Custom Language button label.",
        "up to 64 characters, or - for default", "Language",
    ),
    "start_stats_text": SettingSpec(
        "Stats button", "start", "Custom Stats button label.",
        "up to 64 characters, or - for default", "Stats",
    ),
    "start_trending_text": SettingSpec(
        "Trending button", "start", "Custom Trending button label.",
        "up to 64 characters, or - for default", "Trending",
    ),
    "start_support_text": SettingSpec(
        "Support button", "start", "Custom Support button label.",
        "up to 64 characters, or - for default", "💬 Support",
    ),
    "start_channel_text": SettingSpec(
        "Channel button", "start", "Custom Channel button label.",
        "up to 64 characters, or - for default", "📣 Cʜᴀɴɴᴇʟ",
    ),
    "start_owner_text": SettingSpec(
        "Owner button", "start", "Custom Owner button label.",
        "up to 64 characters, or - for default", "👤 Owner",
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
MEDIA_KEYS = frozenset({"play_image", "start_img", "default_thumb", "ping_img"})
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
    if key in overrides:
        return "Custom"
    return "Theme" if key in themes.active.config else "Environment"


def _header(icon: str, title: str) -> str:
    return (
        '<table><tr><th align="center">'
        f"{icon} {escape(_small_caps_title(title))}"
        "</th></tr></table>"
    )


def _overview_markup(has_overrides: bool) -> types.InlineKeyboardMarkup:
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
    actions = [buttons.ikb(
        text="🔄 Refresh",
        callback_data=callbacks.runtime_config("home", "root"),
    )]
    if has_overrides:
        actions.append(buttons.ikb(
            text="↩️ Reset all",
            callback_data=callbacks.runtime_config("confirm_all", "all"),
        ))
    rows.append(actions)
    rows.append([buttons.ikb(
        text="😀 Emoji style",
        callback_data=callbacks.runtime_config("emoji", "root"),
    )])
    rows.append([buttons.ikb(
        text="🎨 Themes", callback_data=callbacks.theme("home", "root")
    )])
    rows.append(home_row("⬅️ Home", callbacks.HELP_HOME))
    return buttons.ikm(rows)


async def _overview_view() -> ConfigView:
    overrides = await themes.config_overrides()
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
        _header("⚙️", "Bot settings")
        + f"<blockquote>Active theme · {escape(themes.active.name)}</blockquote>"
        + '<table bordered striped>' + "".join(rows) + "</table>"
        + "<blockquote>Changes apply immediately · Saved across restarts</blockquote>"
    )
    fallback = (
        f"⚙️ <b>{_small_caps_title('Bot settings')}</b>\n\n"
        f"<blockquote>Active theme · {escape(themes.active.name)}</blockquote>\n\n"
        + "\n".join(fallback_rows)
        + "\n\n<blockquote>Changes apply immediately · "
        "Saved across restarts</blockquote>"
    )
    return ConfigView(rich, fallback, _overview_markup(bool(overrides)))


def _emoji_names() -> list[str]:
    return sorted(themes.ui().get("emojis", {}).get("registry", {}))


def _emoji_target(token: str) -> str:
    return f"e{_emoji_names().index(token)}"


def _emoji_from_target(target: str) -> str | None:
    if not target.startswith("e") or not target[1:].isdigit():
        return None
    names = _emoji_names()
    index = int(target[1:])
    return names[index] if index < len(names) else None


def _emoji_usage(token: str) -> list[str]:
    placements = themes.ui().get("emojis", {}).get("placements", {})
    return [
        f"{group}.{name}"
        for group, mappings in placements.items()
        for name, assigned in mappings.items()
        if assigned == token
    ]


async def _emoji_view(page: int = 0) -> ConfigView:
    emojis = themes.ui().get("emojis", {})
    registry = emojis.get("registry", {})
    names = _emoji_names()
    page_size = 18
    page_count = max(1, (len(names) + page_size - 1) // page_size)
    page = max(0, min(page, page_count - 1))
    visible = names[page * page_size:(page + 1) * page_size]
    custom = sum(bool(token.get("custom_emoji_id")) for token in registry.values())
    assigned = sum(
        len(mappings) for mappings in emojis.get("placements", {}).values()
    )
    source = "Override" if await themes.emoji_overridden() else "Theme"
    rich = (
        _header("😀", "Emoji style")
        + "<table bordered striped>"
        + "<tr><th>Property</th><th>Value</th></tr>"
        + f'<tr><td>Mode</td><td align="center">{escape(emojis.get("mode", "custom").title())}</td></tr>'
        + f'<tr><td>Tokens</td><td align="center">{len(registry)}</td></tr>'
        + f'<tr><td>Custom</td><td align="center">{custom}</td></tr>'
        + f'<tr><td>Placements</td><td align="center">{assigned}</td></tr>'
        + f'<tr><td>Source</td><td align="center">{source}</td></tr>'
        + f'<tr><td>Page</td><td align="center">{page + 1} / {page_count}</td></tr>'
        + "</table>"
        + "<blockquote>Custom emoji are hidden if Telegram rejects them.</blockquote>"
    )
    fallback = (
        f"😀 <b>{_small_caps_title('Emoji style')}</b>\n\n"
        f"Mode · {emojis.get('mode', 'custom').title()}\n"
        f"Tokens · {len(registry)}\nCustom · {custom}\n"
        f"Placements · {assigned}\nSource · {source}\n\n"
        "<blockquote>Custom emoji are hidden if Telegram rejects them.</blockquote>"
    )
    rows = []
    if themes.editable:
        rows.append([
            buttons.ikb(
                text="Native", callback_data=callbacks.runtime_config("emode", "native")
            ),
            buttons.ikb(
                text="Custom", callback_data=callbacks.runtime_config("emode", "custom")
            ),
            buttons.ikb(
                text="None", callback_data=callbacks.runtime_config("emode", "none")
            ),
        ])
    else:
        rows.append([buttons.ikb(
            text="🧬 Clone to customize",
            callback_data=callbacks.theme("clone", themes.active_id),
        )])
    for index in range(0, len(visible), 3):
        rows.append([
            buttons.ikb(
                text=f"{registry[name]['native']} {name}",
                callback_data=callbacks.runtime_config("etoken", f"e{position}"),
            )
            for position, name in enumerate(visible[index:index + 3], start=page * page_size + index)
        ])
    if page_count > 1:
        rows.append([
            buttons.ikb(
                text="‹",
                callback_data=callbacks.runtime_config(
                    "emoji", f"p{max(0, page - 1)}"
                ),
            ),
            buttons.ikb(
                text=f"{page + 1} / {page_count}",
                callback_data=callbacks.runtime_config("emoji", f"p{page}"),
            ),
            buttons.ikb(
                text="›",
                callback_data=callbacks.runtime_config(
                    "emoji", f"p{min(page_count - 1, page + 1)}"
                ),
            ),
        ])
    if themes.editable and await themes.emoji_overridden():
        rows.append([buttons.ikb(
            text="↩️ Restore theme emoji",
            callback_data=callbacks.runtime_config("ereset", "all"),
        )])
    rows.append([buttons.ikb(
        text="⬅️ Overview", callback_data=callbacks.runtime_config("home", "root")
    )])
    return ConfigView(rich, fallback, buttons.ikm(rows))


async def _emoji_token_view(token_name: str) -> ConfigView:
    token = themes.ui()["emojis"]["registry"][token_name]
    custom_id = token.get("custom_emoji_id") or "not set"
    usage = _emoji_usage(token_name)
    preview = themed_emoji_token(token_name) or "Hidden"
    usage_text = ", ".join(usage[:6]) or "Unused"
    if len(usage) > 6:
        usage_text += f" · +{len(usage) - 6} more"
    rich = (
        _header(token["native"], token_name.replace("_", " ").replace("-", " "))
        + "<table bordered striped>"
        + "<tr><th>Property</th><th>Value</th></tr>"
        + f'<tr><td>Preview</td><td align="center">{preview}</td></tr>'
        + f'<tr><td>Native</td><td align="center">{escape(token["native"])}</td></tr>'
        + f'<tr><td>Custom ID</td><td align="center"><code>{escape(custom_id)}</code></td></tr>'
        + f'<tr><td>Hidden</td><td align="center">{"Yes" if token.get("hidden") else "No"}</td></tr>'
        + "</table>"
        + f"<blockquote>{escape(usage_text)}</blockquote>"
    )
    fallback = (
        f"{token['native']} <b>{escape(token_name)}</b>\n\n"
        f"Preview · {preview}\nNative · {escape(token['native'])}\n"
        f"Custom ID · <code>{escape(custom_id)}</code>\n"
        f"Hidden · {'Yes' if token.get('hidden') else 'No'}\n\n"
        f"<blockquote>{escape(usage_text)}</blockquote>"
    )
    target = _emoji_target(token_name)
    rows = []
    if themes.editable:
        rows.extend([
            [
                buttons.ikb(
                    text="Change native",
                    callback_data=callbacks.runtime_config("enative", target),
                ),
                buttons.ikb(
                    text="Set custom",
                    callback_data=callbacks.runtime_config("ecustom", target),
                ),
            ],
            [
                buttons.ikb(
                    text="Show" if token.get("hidden") else "Hide",
                    callback_data=callbacks.runtime_config("ehide", target),
                ),
                buttons.ikb(
                    text="Clear custom",
                    callback_data=callbacks.runtime_config("eclear", target),
                ),
            ],
        ])
    rows.append([buttons.ikb(
        text="⬅️ Emoji style",
        callback_data=callbacks.runtime_config(
            "emoji", f"p{_emoji_names().index(token_name) // 18}"
        ),
    )])
    return ConfigView(rich, fallback, buttons.ikm(rows))

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
    overrides = await themes.config_overrides()
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
            text="↩️ Use default",
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
    overrides = await themes.config_overrides()
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
    overrides = await themes.config_overrides()
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
        "theme or environment defaults immediately.</blockquote>"
    )
    fallback = (
        "↩️ <b>Reset all settings?</b>\n\n"
        "<blockquote>This removes every runtime override and restores "
        "theme or environment defaults immediately.</blockquote>"
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


def _setting_media_value(message: types.Message, key: str) -> str | None:
    if key not in MEDIA_KEYS:
        return None
    if message.photo:
        return message.photo.file_id
    document = message.document
    if (
        document
        and document.mime_type
        and document.mime_type.startswith("image/")
    ):
        return document.file_id
    return None


async def _validate_and_store(key: str, raw_value: str) -> str:
    async with _CONFIG_LOCK:
        return str(await themes.set_config(key, raw_value))


async def _restore_setting(key: str) -> None:
    async with _CONFIG_LOCK:
        await themes.reset_config(key)


async def _toggle_setting(key: str) -> None:
    async with _CONFIG_LOCK:
        raw_value = "off" if config.runtime_display(key) == "on" else "on"
        await themes.set_config(key, raw_value)


async def _restore_all() -> None:
    async with _CONFIG_LOCK:
        await themes.reset_all_config()


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
                    text="⚙️ Open settings",
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
    pending.timeout_task = supervisor.spawn_once(
        f"config-prompt:{user_id}", _expire_edit(user_id, chat_id, prompt.id)
    )


async def _prompt_emoji_edit(
    chat_id: int,
    user_id: int,
    token_name: str,
    kind: str,
    *,
    error: str | None = None,
) -> None:
    await _clear_pending(user_id)
    token = themes.ui()["emojis"]["registry"][token_name]
    custom = kind == "custom"
    accepted = (
        "Send one Telegram custom emoji."
        if custom
        else "Send one native Unicode emoji."
    )
    prefix = f"⚠️ {escape(error)}\n\n" if error else ""
    prompt = await app.send_message(
        chat_id,
        prefix
        + f"😀 <b>Change {escape(token_name)}</b>\n\n"
        + f"Current native · {escape(token['native'])}\n"
        + accepted
        + "\n\nReply within 5 minutes. Reply with cancel to stop.",
        reply_markup=types.ForceReply(
            placeholder="Send a custom emoji" if custom else "Send one emoji"
        ),
    )
    pending = PendingEdit(
        prompt.id,
        f"emoji:{kind}:{token_name}",
        "emoji",
        monotonic(),
    )
    _PENDING_EDITS[user_id] = pending
    pending.timeout_task = supervisor.spawn_once(
        f"config-prompt:{user_id}", _expire_edit(user_id, chat_id, prompt.id)
    )


def _message_custom_emoji_id(message: types.Message) -> str | None:
    for entity in message.entities or []:
        if entity.type == enums.MessageEntityType.CUSTOM_EMOJI:
            value = getattr(entity, "custom_emoji_id", None)
            if value:
                return str(value)
    return None


async def _handle_emoji_reply(
    message: types.Message,
    pending: PendingEdit,
) -> None:
    _, kind, token_name = pending.key.split(":", 2)
    try:
        async with _CONFIG_LOCK:
            if kind == "native":
                value = str(message.text or "").strip()
                if not value:
                    raise ValueError("Send one native Unicode emoji.")
                await themes.update_emoji_token(token_name, native=value)
            else:
                custom_id = _message_custom_emoji_id(message)
                if not custom_id:
                    raise ValueError("Send a Telegram custom emoji, not plain text.")
                await themes.update_emoji_token(
                    token_name, custom_emoji_id=custom_id
                )
    except (TypeError, ValueError) as exc:
        return await _prompt_emoji_edit(
            message.chat.id,
            message.from_user.id,
            token_name,
            kind,
            error=str(exc),
        )
    except Exception:
        logger.exception("Could not update emoji token %s", token_name)
        return await message.reply_text(
            "⚠️ The emoji could not be saved. No change was applied."
        )
    await _send_view(message, await _emoji_token_view(token_name))


async def open_runtime_config(message: types.Message) -> None:
    if not message.from_user or message.from_user.id not in app.sudoers:
        await message.reply_text("🔒 Bot settings are sudo-only.")
        return
    if message.chat.type != enums.ChatType.PRIVATE:
        await message.reply_text(
            "🔐 Open bot settings privately.",
            reply_markup=buttons.ikm([[
                buttons.ikb(
                    text="⚙️ Open settings",
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
            "🔎 That setting doesn't exist. Open /config to choose a setting."
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
                "🔎 That setting doesn't exist. Open /config to choose a setting."
            )
        await _restore_setting(key)
    except Exception:
        logger.exception("Could not restore runtime setting %s", key)
        return await message.reply_text(
            "⚠️ The setting could not be restored. Please try again."
        )
    await _send_view(message, await _setting_view(key))


@app.on_message(filters.private & filters.reply & app.sudoers, group=3)
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
    if pending.category == "emoji":
        return await _handle_emoji_reply(message, pending)
    raw_value = _setting_input_text(message, pending.key)
    if not raw_value:
        raw_value = _setting_media_value(message, pending.key) or ""
    if not raw_value:
        return await _prompt_edit(
            message.chat.id,
            message.from_user.id,
            pending.key,
            error="Send a text value or a supported image.",
        )
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
    if action == "emoji" and (
        target == "root" or target.startswith("p") and target[1:].isdigit()
    ):
        await query.answer()
        page = int(target[1:]) if target.startswith("p") else 0
        return await _edit_view(query, await _emoji_view(page))
    token_name = _emoji_from_target(target)
    if action == "etoken" and token_name:
        await query.answer()
        return await _edit_view(query, await _emoji_token_view(token_name))
    if action in {"enative", "ecustom"} and token_name:
        await query.answer("Reply with the new emoji")
        return await _prompt_emoji_edit(
            query.message.chat.id,
            query.from_user.id,
            token_name,
            "native" if action == "enative" else "custom",
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
        if action == "emode" and target in {"native", "custom", "none"}:
            emojis = themes.ui()["emojis"]
            emojis["mode"] = target
            async with _CONFIG_LOCK:
                await themes.set_emojis(emojis)
            await feedback.toast(query, "Emoji mode updated")
            return await _edit_view(query, await _emoji_view())
        if action == "ehide" and token_name:
            token = themes.ui()["emojis"]["registry"][token_name]
            async with _CONFIG_LOCK:
                await themes.update_emoji_token(
                    token_name, hidden=not token.get("hidden", False)
                )
            await feedback.toast(query, "Emoji visibility updated")
            return await _edit_view(query, await _emoji_token_view(token_name))
        if action == "eclear" and token_name:
            async with _CONFIG_LOCK:
                await themes.update_emoji_token(
                    token_name, custom_emoji_id=None
                )
            await feedback.toast(query, "Custom emoji cleared")
            return await _edit_view(query, await _emoji_token_view(token_name))
        if action == "ereset" and target == "all":
            async with _CONFIG_LOCK:
                await themes.reset_emojis()
            await feedback.toast(query, "Theme emoji restored")
            return await _edit_view(query, await _emoji_view())
    except Exception:
        logger.exception("Bot settings action failed: %s", action)
        return await query.answer(
            "The change could not be saved. Nothing was changed.",
            show_alert=True,
        )
    await query.answer("This control has expired.", show_alert=True)
