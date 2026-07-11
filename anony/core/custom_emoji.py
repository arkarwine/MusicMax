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
_button_fallbacks: dict[int, str] = {}


class LocalizedText(str):
    """A trusted locale/template string that remains compatible with str."""

    def format(self, *args, **kwargs):
        return type(self)(super().format(*args, **kwargs))

    def format_map(self, mapping):
        return type(self)(super().format_map(mapping))

    def __add__(self, other):
        return type(self)(super().__add__(other))

    def __radd__(self, other):
        return type(self)(str(other) + str(self))

    def replace(self, old, new, count=-1):
        return type(self)(super().replace(old, new, count))


def localized_text(text: str) -> LocalizedText:
    return LocalizedText(text)


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
    global _supported, _detected
    _supported = bool(supported)
    _detected = True


def strip_custom_emoji_tags(text: str) -> str:
    """Replace trusted Telegram custom-emoji HTML with its fallback content."""
    if not isinstance(text, str) or "tg-emoji" not in text.lower():
        return text
    return _TAG_RE.sub(lambda match: match.group(3), text)


def render_custom_emoji_text(text: str) -> str:
    if not isinstance(text, str) or custom_emoji_supported():
        return text
    return strip_custom_emoji_tags(text)


def _button_supports_custom_icons() -> bool:
    try:
        return "icon_custom_emoji_id" in inspect.signature(
            types.InlineKeyboardButton
        ).parameters
    except (TypeError, ValueError):
        return False


def custom_emoji_button(text: str, **kwargs) -> types.InlineKeyboardButton:
    """Build a button from a localized label with an optional leading tag."""
    match = _LEADING_TAG_RE.match(text) if isinstance(text, str) else None
    if not match:
        return types.InlineKeyboardButton(
            text=render_custom_emoji_text(text), **kwargs
        )

    fallback = match.group(3)
    remainder = text[match.end():]
    emoji_id = unescape(match.group(2)).strip()
    can_use_icon = (
        custom_emoji_supported()
        and emoji_id.isdecimal()
        and _button_supports_custom_icons()
    )
    if can_use_icon:
        try:
            button = types.InlineKeyboardButton(
                text=remainder,
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
                values["text"] = (
                    _button_fallbacks.get(id(button), "")
                    + values.get("text", "")
                )
            rebuilt.append(types.InlineKeyboardButton(**values))
        rows.append(rebuilt)
    return types.InlineKeyboardMarkup(rows)
