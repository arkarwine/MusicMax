"""Sudo-only Telegram management for global data-driven themes."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from html import escape
from time import monotonic

from pyrogram import enums, filters, types
from pyrogram.errors import BadRequest

from anony import app, themes
from anony.core.themes import MAX_THEME_BYTES, Theme, ThemeError
from anony.helpers import buttons
from anony.ui import callbacks


@dataclass(slots=True)
class PendingAction:
    prompt_id: int
    action: str
    target: str
    expires: float


@dataclass(slots=True)
class PendingImport:
    document: dict
    expires: float


_PENDING: dict[int, PendingAction] = {}
_IMPORTS: dict[int, PendingImport] = {}
_FLOW_TTL = 300


def _header(title: str) -> str:
    return (
        '<table><tr><th align="center">'
        f"🎨 {escape(title)}"
        "</th></tr></table>"
    )


def _theme_label(theme: Theme) -> str:
    marker = " ✓" if theme.id == themes.active_id else ""
    lock = "🔒 " if theme.builtin else "🎨 "
    return f"{lock}{theme.name}{marker}"


def _dashboard_markup() -> types.InlineKeyboardMarkup:
    rows = []
    items = sorted(
        themes.themes.values(), key=lambda item: (not item.builtin, item.name.lower())
    )
    for index in range(0, len(items), 2):
        rows.append([
            buttons.ikb(
                text=_theme_label(theme),
                callback_data=callbacks.theme("view", theme.id),
            )
            for theme in items[index:index + 2]
        ])
    rows.extend([
        [
            buttons.ikb(
                text="➕ New from defaults",
                callback_data=callbacks.theme("create", "defaults"),
            ),
            buttons.ikb(
                text="🧬 Clone active",
                callback_data=callbacks.theme("clone", themes.active_id),
            ),
        ],
        [
            buttons.ikb(
                text="📥 Import JSON",
                callback_data=callbacks.theme("import", "json"),
            ),
            buttons.ikb(
                text="🔄 Refresh",
                callback_data=callbacks.theme("home", "root"),
            ),
        ],
    ])
    return buttons.ikm(rows)


def _dashboard() -> tuple[str, types.InlineKeyboardMarkup]:
    builtin_count = sum(item.builtin for item in themes.themes.values())
    custom_count = len(themes.themes) - builtin_count
    text = (
        _header("Themes")
        + "<table bordered striped>"
        + "<tr><th>Property</th><th>Value</th></tr>"
        + f"<tr><td>Active</td><td>{escape(themes.active.name)}</td></tr>"
        + f"<tr><td>Built-in</td><td>{builtin_count}</td></tr>"
        + f"<tr><td>Custom</td><td>{custom_count}</td></tr>"
        + "</table>"
        + "<blockquote>One global theme · Changes apply immediately</blockquote>"
    )
    return text, _dashboard_markup()


async def _detail(theme_id: str) -> tuple[str, types.InlineKeyboardMarkup]:
    theme = themes.themes[theme_id]
    resolved = await themes.resolved(theme_id)
    source = "Built-in · read-only" if theme.builtin else "Custom · editable"
    text = (
        _header(theme.name)
        + "<table bordered striped>"
        + "<tr><th>Property</th><th>Value</th></tr>"
        + f"<tr><td>Status</td><td>{'Active' if theme_id == themes.active_id else 'Available'}</td></tr>"
        + f"<tr><td>Source</td><td>{source}</td></tr>"
        + f"<tr><td>Version</td><td>{escape(theme.version)}</td></tr>"
        + f"<tr><td>Config</td><td>{len(resolved.config)} values</td></tr>"
        + f"<tr><td>Locale overrides</td><td>{sum(map(len, resolved.locales.values()))}</td></tr>"
        + f"<tr><td>Emoji mode</td><td>{escape(resolved.ui.get('emojis', {}).get('mode', 'custom').title())}</td></tr>"
        + f"<tr><td>Emoji tokens</td><td>{len(resolved.ui.get('emojis', {}).get('registry', {}))}</td></tr>"
        + "</table>"
        + f"<blockquote>{escape(theme.description)}</blockquote>"
        + f"<code>{escape(theme.id)}</code> · {escape(theme.author)}"
    )
    rows = []
    if theme_id != themes.active_id:
        rows.append([buttons.ikb(
            text="▶️ Activate",
            callback_data=callbacks.theme("activate", theme_id),
            style=enums.ButtonStyle.SUCCESS,
        )])
    rows.append([buttons.ikb(
        text="🧬 Clone",
        callback_data=callbacks.theme("clone", theme_id),
    )])
    if not theme.builtin:
        rows.append([
            buttons.ikb(
                text="📤 Export",
                callback_data=callbacks.theme("export", theme_id),
            ),
            buttons.ikb(
                text="✏️ Rename",
                callback_data=callbacks.theme("rename", theme_id),
            ),
        ])
        if theme_id != themes.active_id:
            rows.append([buttons.ikb(
                text="🗑️ Delete",
                callback_data=callbacks.theme("delete", theme_id),
                style=enums.ButtonStyle.DANGER,
            )])
    rows.append([buttons.ikb(
        text="⬅️ Themes",
        callback_data=callbacks.theme("home", "root"),
    )])
    return text, buttons.ikm(rows)


async def _activation_preview(
    theme_id: str,
) -> tuple[str, types.InlineKeyboardMarkup]:
    current = await themes.export(themes.active_id)
    target = await themes.export(theme_id)
    config_changes = sum(
        current["config"].get(key) != target["config"].get(key)
        for key in themes.config.RUNTIME_FIELDS
    )
    ui_changes = int(current["ui"] != target["ui"])
    current_emojis = current["ui"].get("emojis", {})
    target_emojis = target["ui"].get("emojis", {})
    token_names = set(current_emojis.get("registry", {})) | set(
        target_emojis.get("registry", {})
    )
    emoji_changes = int(
        current_emojis.get("mode") != target_emojis.get("mode")
    ) + sum(
        current_emojis.get("registry", {}).get(name)
        != target_emojis.get("registry", {}).get(name)
        for name in token_names
    )
    placement_groups = set(current_emojis.get("placements", {})) | set(
        target_emojis.get("placements", {})
    )
    emoji_changes += sum(
        current_emojis.get("placements", {}).get(group)
        != target_emojis.get("placements", {}).get(group)
        for group in placement_groups
    )
    locale_changes = sum(
        current["locales"].get(code, {}) != target["locales"].get(code, {})
        for code in set(current["locales"]) | set(target["locales"])
    )
    target_theme = themes.themes[theme_id]
    text = (
        _header("Activate theme?")
        + f"<blockquote>{escape(themes.active.name)} → {escape(target_theme.name)}</blockquote>"
        + "<table bordered striped>"
        + "<tr><th>Section</th><th>Changes</th></tr>"
        + f"<tr><td>Configuration</td><td>{config_changes}</td></tr>"
        + f"<tr><td>Presentation</td><td>{ui_changes}</td></tr>"
        + f"<tr><td>Emoji</td><td>{emoji_changes}</td></tr>"
        + f"<tr><td>Locales</td><td>{locale_changes}</td></tr>"
        + "</table>"
    )
    markup = buttons.ikm([[
        buttons.ikb(
            text="Activate",
            callback_data=callbacks.theme("confirm", theme_id),
            style=enums.ButtonStyle.SUCCESS,
        ),
        buttons.ikb(
            text="Cancel",
            callback_data=callbacks.theme("view", theme_id),
        ),
    ]])
    return text, markup


async def _send(message: types.Message, text: str, markup) -> None:
    await message.reply_text(text, reply_markup=markup, disable_notification=True)


async def _edit(query: types.CallbackQuery, text: str, markup) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as exc:
        if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
            raise


async def open_themes(message: types.Message) -> None:
    if not message.from_user or message.from_user.id not in app.sudoers:
        return await message.reply_text("🔒 Theme management is sudo-only.")
    if message.chat.type != enums.ChatType.PRIVATE:
        return await message.reply_text("🔐 Open /themes privately.")
    text, markup = _dashboard()
    await _send(message, text, markup)


async def _prompt(
    chat_id: int, user_id: int, action: str, target: str, text: str,
    placeholder: str,
) -> None:
    old = _PENDING.pop(user_id, None)
    if old:
        try:
            old_prompt = await app.get_messages(chat_id, old.prompt_id)
            await old_prompt.delete()
        except Exception:
            pass
    prompt = await app.send_message(
        chat_id,
        text + "\n\nReply within 5 minutes. Reply with cancel to stop.",
        reply_markup=types.ForceReply(placeholder=placeholder),
    )
    _PENDING[user_id] = PendingAction(
        prompt.id, action, target, monotonic() + _FLOW_TTL
    )


async def _read_json(message: types.Message) -> dict:
    if not message.document:
        raise ThemeError("Reply with a JSON document")
    if message.document.file_size and message.document.file_size > MAX_THEME_BYTES:
        raise ThemeError("Theme file must be 256 KB or smaller")
    if message.document.file_name and not message.document.file_name.lower().endswith(
        ".json"
    ):
        raise ThemeError("Theme document must use the .json extension")
    stream = await message.download(in_memory=True)
    if stream is None:
        raise ThemeError("Theme document could not be downloaded")
    raw = stream.getvalue()
    if len(raw) > MAX_THEME_BYTES:
        raise ThemeError("Theme file must be 256 KB or smaller")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ThemeError("Theme document is not valid UTF-8 JSON") from exc
    themes.validate(document)
    return document


async def _import_preview(message: types.Message, document: dict) -> None:
    theme = themes.validate(document)
    if themes.is_builtin(theme.id):
        raise ThemeError("A runtime theme cannot replace a built-in theme")
    _IMPORTS[message.from_user.id] = PendingImport(
        document, monotonic() + _FLOW_TTL
    )
    replacing = theme.id in themes.themes
    text = (
        _header("Import theme")
        + "<table bordered striped>"
        + "<tr><th>Property</th><th>Value</th></tr>"
        + f"<tr><td>Name</td><td>{escape(theme.name)}</td></tr>"
        + f"<tr><td>ID</td><td><code>{escape(theme.id)}</code></td></tr>"
        + f"<tr><td>Config</td><td>{len(theme.config)}</td></tr>"
        + f"<tr><td>UI sections</td><td>{len(theme.ui)}</td></tr>"
        + f"<tr><td>Locales</td><td>{len(theme.locales)}</td></tr>"
        + "</table>"
    )
    action = "replace" if replacing else "install"
    label = "Replace theme" if replacing else "Install theme"
    markup = buttons.ikm([[
        buttons.ikb(
            text=label,
            callback_data=callbacks.theme(action, theme.id),
            style=(
                enums.ButtonStyle.DANGER
                if replacing else enums.ButtonStyle.SUCCESS
            ),
        ),
        buttons.ikb(
            text="Cancel", callback_data=callbacks.theme("home", "root")
        ),
    ]])
    await _send(message, text, markup)


async def _export(chat_id: int, theme_id: str) -> None:
    document = await themes.export(theme_id)
    payload = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    stream = io.BytesIO(payload)
    stream.name = f"{theme_id}.theme.json"
    await app.send_document(
        chat_id,
        stream,
        caption=f"🎨 <b>{escape(document['name'])}</b> · Theme export",
        disable_notification=True,
    )


@app.on_message(filters.command(["themes", "theme"]) & app.sudoers)
async def _themes_command(_, message: types.Message):
    await open_themes(message)


@app.on_message(filters.command(["importtheme"]) & app.sudoers)
async def _import_theme_command(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_themes(message)
    source = message.reply_to_message
    if source and source.document:
        try:
            return await _import_preview(message, await _read_json(source))
        except ThemeError as exc:
            return await message.reply_text(f"⚠️ {escape(str(exc))}")
    await _prompt(
        message.chat.id, message.from_user.id, "import", "json",
        "📥 <b>Import theme</b>\n\nReply with a theme JSON document.",
        "Attach a JSON document",
    )


@app.on_message(filters.command(["exporttheme"]) & app.sudoers)
async def _export_theme_command(_, message: types.Message):
    if message.chat.type != enums.ChatType.PRIVATE:
        return await open_themes(message)
    theme_id = message.command[1] if len(message.command) > 1 else themes.active_id
    if theme_id not in themes.themes:
        return await message.reply_text("⚠️ Theme not found.")
    await _export(message.chat.id, theme_id)


@app.on_message(filters.private & filters.reply & app.sudoers, group=4)
async def _theme_reply(_, message: types.Message):
    pending = _PENDING.get(message.from_user.id)
    reply = message.reply_to_message
    if not pending or not reply or reply.id != pending.prompt_id:
        return
    _PENDING.pop(message.from_user.id, None)
    if pending.expires < monotonic():
        return await message.reply_text("⌛ This theme request expired.")
    if message.text and message.text.strip().lower() == "cancel":
        return await message.reply_text("Cancelled.")
    try:
        if pending.action == "import":
            return await _import_preview(message, await _read_json(message))
        if not message.text:
            raise ThemeError("Reply with a theme name")
        name = message.text.strip()
        if pending.action in {"create", "clone"}:
            theme = await themes.create(
                name,
                clone_id=(pending.target if pending.action == "clone" else None),
            )
        elif pending.action == "rename":
            theme = await themes.rename(pending.target, name)
        else:
            raise ThemeError("This theme request expired")
    except ThemeError as exc:
        return await message.reply_text(f"⚠️ {escape(str(exc))}")
    text, markup = await _detail(theme.id)
    await _send(message, text, markup)


@app.on_callback_query(filters.regex(r"^theme ") & app.sudoers)
async def _theme_callback(_, query: types.CallbackQuery):
    parts = query.data.split()
    if len(parts) != 3:
        return await query.answer("This control expired.", show_alert=True)
    action, target = parts[1], parts[2]
    if action == "home":
        await query.answer()
        return await _edit(query, *_dashboard())
    if action == "view" and target in themes.themes:
        await query.answer()
        return await _edit(query, *(await _detail(target)))
    if action == "activate" and target in themes.themes:
        await query.answer()
        return await _edit(query, *(await _activation_preview(target)))
    if action == "confirm" and target in themes.themes:
        try:
            await themes.activate(target)
        except Exception as exc:
            return await query.answer(
                f"Activation failed: {type(exc).__name__}", show_alert=True
            )
        await query.answer("Theme activated")
        return await _edit(query, *(await _detail(target)))
    if action in {"create", "clone", "rename", "import"}:
        if action in {"clone", "rename"} and target not in themes.themes:
            return await query.answer("Theme not found.", show_alert=True)
        labels = {
            "create": ("Create theme", "Theme name"),
            "clone": ("Clone theme", "Name for the clone"),
            "rename": ("Rename theme", "New theme name"),
            "import": ("Import theme", "Attach a JSON document"),
        }
        await query.answer("Reply to the new prompt")
        return await _prompt(
            query.message.chat.id, query.from_user.id, action, target,
            f"🎨 <b>{labels[action][0]}</b>", labels[action][1],
        )
    if action == "export" and target in themes.themes:
        await query.answer("Exporting theme")
        return await _export(query.message.chat.id, target)
    if action == "delete" and target in themes.themes:
        theme = themes.themes[target]
        markup = buttons.ikm([[
            buttons.ikb(
                text="Delete",
                callback_data=callbacks.theme("confirm_delete", target),
                style=enums.ButtonStyle.DANGER,
            ),
            buttons.ikb(
                text="Cancel", callback_data=callbacks.theme("view", target)
            ),
        ]])
        await query.answer()
        return await _edit(
            query,
            _header("Delete theme?")
            + f"<blockquote>{escape(theme.name)} will be removed permanently.</blockquote>",
            markup,
        )
    if action == "confirm_delete" and target in themes.themes:
        try:
            await themes.delete(target)
        except ThemeError as exc:
            return await query.answer(str(exc), show_alert=True)
        await query.answer("Theme deleted")
        return await _edit(query, *_dashboard())
    if action in {"install", "replace"}:
        pending = _IMPORTS.get(query.from_user.id)
        if not pending or pending.expires < monotonic():
            return await query.answer("Import preview expired.", show_alert=True)
        try:
            theme = await themes.install(
                pending.document, replace_existing=(action == "replace")
            )
        except ThemeError as exc:
            return await query.answer(str(exc), show_alert=True)
        _IMPORTS.pop(query.from_user.id, None)
        await query.answer("Theme installed")
        return await _edit(query, *(await _detail(theme.id)))
    await query.answer("This control expired.", show_alert=True)
