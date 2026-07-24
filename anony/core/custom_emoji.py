# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import inspect
import re
from html import unescape

from pyrogram import types


_TAG_RE = re.compile(
    r"<tg-emoji\b[^>]*?\bemoji-id\s*=\s*(['\"])(.*?)\1[^>]*>"
    r"(.*?)</tg-emoji\s*>",
    re.IGNORECASE | re.DOTALL,
)
_LEADING_TAG_RE = re.compile(
    r"^\s*<tg-emoji\b[^>]*?\bemoji-id\s*=\s*(['\"])(.*?)\1[^>]*>"
    r"(.*?)</tg-emoji\s*>",
    re.IGNORECASE | re.DOTALL,
)

_supported = False
_detected = False
_button_icons_supported: bool | None = None
_button_fallbacks: dict[int, str] = {}
_themed_custom_ids: set[str] = set()
_BUTTON_LOCALE_ACTIONS = {
    "start_add_button": "start.add",
    "start_support_button": "start.support",
    "start_channel_button": "start.channel",
    "start_owner_button": "start.owner",
    "control_loop": "control.loop",
    "control_stop": "control.stop",
    "control_pause": "control.pause",
    "control_resume": "control.resume",
    "control_skip": "control.skip",
    "control_replay": "control.replay",
    "stats_refresh": "stats.refresh",
    **{f"help_{index}": f"help.{action}" for index, action in enumerate((
        "admins", "auth", "blist", "lang", "ping", "play", "queue", "stats", "sudo",
    ))},
}


class LocalizedText(str):
    """A trusted locale/template string that remains compatible with str."""

    def __new__(cls, value: str, key: str | None = None):
        instance = super().__new__(cls, value)
        instance.locale_key = key
        return instance

    def format(self, *args, **kwargs):
        return type(self)(super().format(*args, **kwargs), self.locale_key)

    def format_map(self, mapping):
        return type(self)(super().format_map(mapping), self.locale_key)

    def __add__(self, other):
        return type(self)(super().__add__(other), self.locale_key)

    def __radd__(self, other):
        return type(self)(str(other) + str(self), self.locale_key)

    def replace(self, old, new, count=-1):
        return type(self)(super().replace(old, new, count), self.locale_key)


def localized_text(text: str, key: str | None = None) -> LocalizedText:
    return LocalizedText(text, key)


def is_localized_text(text) -> bool:
    return isinstance(text, LocalizedText)


def custom_emoji_supported() -> bool:
    return _supported


def get_custom_emoji_supported() -> bool:
    return custom_emoji_supported()


def custom_emoji_capability_detected() -> bool:
    return _detected


def get_custom_emoji_capability_detected() -> bool:
    return custom_emoji_capability_detected()


def set_custom_emoji_supported(supported: bool) -> None:
    global _supported, _detected, _button_icons_supported
    _supported = bool(supported)
    _detected = True
    if not _supported:
        _button_icons_supported = False


def custom_emoji_button_icons_supported() -> bool:
    return _button_icons_supported is not False


def set_custom_emoji_button_icons_supported(supported: bool) -> bool:
    """Set button capability and return whether the state changed."""
    global _button_icons_supported
    changed = _button_icons_supported is not bool(supported)
    _button_icons_supported = bool(supported)
    return changed


def set_themed_custom_emoji_ids(values: set[str]) -> None:
    global _themed_custom_ids
    _themed_custom_ids = {
        str(value) for value in values if str(value).isdecimal()
    }


def _strip_replacement(match: re.Match) -> str:
    return "" if unescape(match.group(2)).strip() in _themed_custom_ids else match.group(3)


def strip_custom_emoji_tags(text: str) -> str:
    """Replace trusted Telegram custom-emoji HTML with its fallback content."""
    if not isinstance(text, str) or "tg-emoji" not in text.lower():
        return text
    return _TAG_RE.sub(_strip_replacement, text)


def render_custom_emoji_text(text: str) -> str:
    if not isinstance(text, str):
        return text
    rendered = text if custom_emoji_supported() else strip_custom_emoji_tags(text)
    locale_key = getattr(text, "locale_key", None)
    if locale_key:
        try:
            from anony.core.rich_messages import (
                has_themed_emoji_placement,
                themed_localized_emoji,
            )

            prefix = themed_localized_emoji(locale_key)
            if has_themed_emoji_placement("messages", locale_key):
                match = _LEADING_TAG_RE.match(str(rendered))
                if match:
                    rendered = str(rendered)[match.end():].lstrip()
        except ImportError:
            prefix = ""
        if prefix:
            rendered = prefix + " " + str(rendered).lstrip()
    if isinstance(text, LocalizedText):
        return localized_text(rendered, text.locale_key)
    return rendered


def _button_supports_custom_icons() -> bool:
    try:
        return "icon_custom_emoji_id" in inspect.signature(
            types.InlineKeyboardButton
        ).parameters
    except (TypeError, ValueError):
        return False


def custom_emoji_button(
    text: str,
    *,
    theme_action: str | None = None,
    **kwargs,
) -> types.InlineKeyboardButton:
    """Build a button from a localized label with an optional themed icon."""
    action = theme_action or _BUTTON_LOCALE_ACTIONS.get(
        getattr(text, "locale_key", None)
    )
    themed_placement = False
    if action:
        from anony.core.rich_messages import (
            has_themed_emoji_placement,
            themed_button_emoji,
        )

        themed_placement = has_themed_emoji_placement("buttons", action)
        if themed_placement:
            legacy = _LEADING_TAG_RE.match(str(text))
            if legacy:
                text = str(text)[legacy.end():].lstrip()

        themed = themed_button_emoji(action)
        text = themed + ((" " + str(text).lstrip()) if themed else str(text))
    match = _LEADING_TAG_RE.match(text) if isinstance(text, str) else None
    if not match:
        return types.InlineKeyboardButton(
            text=render_custom_emoji_text(text), **kwargs
        )

    # The themed tag already replaced the locale tag, so its own fallback is
    # the single authoritative Unicode/native value. Retain it for clients or
    # bot accounts that cannot deliver custom button icons.
    fallback = match.group(3)
    remainder = text[match.end():]
    emoji_id = unescape(match.group(2)).strip()
    can_use_icon = (
        custom_emoji_supported()
        and custom_emoji_button_icons_supported()
        and emoji_id.isdecimal()
        and _button_supports_custom_icons()
    )
    if can_use_icon:
        try:
            button = types.InlineKeyboardButton(
                # Telegram still requires non-empty button text when a custom
                # icon is present. INVISIBLE SEPARATOR keeps icon-only controls
                # visually icon-only without duplicating their fallback glyph.
                text=remainder or "\u2063",
                icon_custom_emoji_id=emoji_id,
                **kwargs,
            )
            _button_fallbacks[id(button)] = fallback
            return button
        except (TypeError, ValueError):
            pass

    return types.InlineKeyboardButton(text=fallback + remainder, **kwargs)


def keyboard_has_custom_icons(markup) -> bool:
    return bool(
        markup
        and any(
            getattr(button, "icon_custom_emoji_id", None)
            for row in getattr(markup, "inline_keyboard", [])
            for button in row
        )
    )


def keyboard_without_custom_icons(markup):
    """Rebuild a markup without custom icons while retaining styles/actions."""
    if not keyboard_has_custom_icons(markup):
        return markup

    parameters = inspect.signature(types.InlineKeyboardButton).parameters
    rows = []
    for row in markup.inline_keyboard:
        rebuilt = []
        for button in row:
            values = {
                name: getattr(button, name, None)
                for name in parameters
                if name not in {"self", "icon_custom_emoji_id"}
                and hasattr(button, name)
            }
            emoji_id = getattr(button, "icon_custom_emoji_id", None)
            if emoji_id:
                visible_text = values.get("text", "")
                if visible_text == "\u2063":
                    visible_text = ""
                values["text"] = (
                    _button_fallbacks.get(id(button), "")
                    + visible_text
                )
            rebuilt.append(types.InlineKeyboardButton(**values))
        rows.append(rebuilt)
    return types.InlineKeyboardMarkup(rows)
