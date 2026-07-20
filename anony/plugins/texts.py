# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic

from __future__ import annotations

from html import escape
from string import Formatter

from pyrogram import filters, types

from anony import app, db, lang, logger


MAX_TEXT_LENGTH = 2000


def _fields(value: str) -> set[str]:
    fields = set()
    for _, field, format_spec, conversion in Formatter().parse(value):
        if field is None:
            continue
        if format_spec or conversion:
            raise ValueError("format specifiers are not supported")
        fields.add(field)
    return fields


def _validate_text(lang_code: str, key: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Text cannot be empty.")
    if len(value) > MAX_TEXT_LENGTH:
        raise ValueError(f"Text must be {MAX_TEXT_LENGTH} characters or less.")
    if lang_code not in lang.languages:
        raise ValueError("Unknown language. Use en or my.")
    if key not in lang.languages[lang_code]:
        raise ValueError("Unknown text key. Use /texts to search keys.")

    try:
        new_fields = _fields(value)
    except ValueError as exc:
        raise ValueError("Text contains malformed braces.") from exc
    current_fields = _fields(str(lang.languages[lang_code][key]))
    if new_fields != current_fields:
        expected = ", ".join(sorted(current_fields)) or "none"
        actual = ", ".join(sorted(new_fields)) or "none"
        raise ValueError(
            f"Placeholder mismatch. Expected: {expected}. Received: {actual}."
        )
    return value


async def _reload() -> dict[str, dict[str, str]]:
    overrides = await db.get_text_overrides()
    lang.apply_text_overrides(overrides)
    return overrides


def _usage() -> str:
    return (
        "📝 <b>Text settings</b>\n\n"
        "<blockquote>"
        "├ <code>/texts [en|my] [search]</code>\n"
        "├ <code>/text &lt;en|my&gt; &lt;key&gt;</code>\n"
        "├ <code>/settext &lt;en|my&gt; &lt;key&gt; &lt;text&gt;</code>\n"
        "├ reply with <code>/settext &lt;en|my&gt; &lt;key&gt;</code>\n"
        "├ <code>/resettext &lt;en|my&gt; &lt;key&gt;</code>\n"
        "└ <code>/reloadtexts</code>"
        "</blockquote>"
    )


@app.on_message(filters.command(["texts"]) & app.sudoers)
@lang.language()
async def _texts(_, message: types.Message):
    lang_code = message.command[1].lower() if len(message.command) > 1 else "en"
    query = " ".join(message.command[2:]).lower() if len(message.command) > 2 else ""
    if lang_code not in lang.languages:
        return await message.reply_text("⚠️ Unknown language. Use en or my.")

    overrides = await db.get_text_overrides()
    keys = sorted(lang.languages[lang_code])
    if query:
        keys = [
            key for key in keys
            if query in key.lower()
            or query in str(lang.languages[lang_code][key]).lower()
        ]
    shown = keys[:30]
    lines = [
        "📝 <b>Text settings</b>",
        "",
        f"<blockquote>├ Language: <code>{lang_code}</code>",
        f"├ Matches: <b>{len(keys)}</b>",
        f"└ Custom: <b>{len(overrides.get(lang_code, {}))}</b></blockquote>",
        "",
        "<blockquote expandable>",
    ]
    for key in shown:
        marker = "✦" if key in overrides.get(lang_code, {}) else "·"
        lines.append(f"{marker} <code>{escape(key)}</code>")
    if len(keys) > len(shown):
        lines.append(f"… {len(keys) - len(shown)} more")
    lines.append("</blockquote>")
    lines.append(f"\nUse <code>/text {lang_code} key</code> to inspect one text.")
    await message.reply_text("\n".join(lines))


@app.on_message(filters.command(["text"]) & app.sudoers)
@lang.language()
async def _text(_, message: types.Message):
    if len(message.command) < 3:
        return await message.reply_text(_usage())
    lang_code, key = message.command[1].lower(), message.command[2]
    if lang_code not in lang.languages or key not in lang.languages[lang_code]:
        return await message.reply_text("🔎 Text key not found.")

    overrides = await db.get_text_overrides()
    custom = overrides.get(lang_code, {}).get(key)
    value = custom if custom is not None else str(lang.languages[lang_code][key])
    source = "Custom" if custom is not None else "Default"
    await message.reply_text(
        "📝 <b>Text</b>\n\n"
        f"<blockquote>├ Language: <code>{lang_code}</code>\n"
        f"├ Key: <code>{escape(key)}</code>\n"
        f"└ Source: <b>{source}</b></blockquote>\n\n"
        f"<pre>{escape(value)}</pre>"
    )


@app.on_message(filters.command(["settext"]) & app.sudoers)
@lang.language()
async def _set_text(_, message: types.Message):
    if len(message.command) < 3:
        return await message.reply_text(_usage())
    lang_code, key = message.command[1].lower(), message.command[2]

    parts = message.text.split(maxsplit=3) if message.text else []
    value = parts[3] if len(parts) > 3 else ""
    if not value and message.reply_to_message:
        value = (
            message.reply_to_message.text
            or message.reply_to_message.caption
            or ""
        )
    if not value:
        return await message.reply_text(
            "⚠️ Send text after the command, or reply to a message with the text."
        )
    try:
        value = _validate_text(lang_code, key, value)
        await db.set_text_override(lang_code, key, value)
        await _reload()
    except ValueError as exc:
        return await message.reply_text(f"⚠️ {escape(str(exc))}")
    except Exception:
        logger.exception("Could not save text override %s.%s", lang_code, key)
        return await message.reply_text(
            "⚠️ Text could not be saved. No change was applied."
        )
    await message.reply_text(
        "✅ <b>Text updated</b>\n\n"
        f"<blockquote>├ Language: <code>{lang_code}</code>\n"
        f"└ Key: <code>{escape(key)}</code></blockquote>"
    )


@app.on_message(filters.command(["resettext"]) & app.sudoers)
@lang.language()
async def _reset_text(_, message: types.Message):
    if len(message.command) < 3:
        return await message.reply_text(_usage())
    lang_code, key = message.command[1].lower(), message.command[2]
    if lang_code not in lang.languages or key not in lang.languages[lang_code]:
        return await message.reply_text("🔎 Text key not found.")
    await db.reset_text_override(lang_code, key)
    await _reload()
    await message.reply_text(
        "↩️ <b>Text restored</b>\n\n"
        f"<blockquote>├ Language: <code>{lang_code}</code>\n"
        f"└ Key: <code>{escape(key)}</code></blockquote>"
    )


@app.on_message(filters.command(["reloadtexts"]) & app.sudoers)
@lang.language()
async def _reload_texts(_, message: types.Message):
    overrides = await _reload()
    count = sum(len(values) for values in overrides.values())
    await message.reply_text(
        "🔄 <b>Texts reloaded</b>\n\n"
        f"<blockquote>└ Custom texts: <b>{count}</b></blockquote>"
    )
