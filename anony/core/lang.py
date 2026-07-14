# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import re
import json
import secrets
from html import escape
from functools import wraps
from pathlib import Path

from pyrogram import enums, errors

from anony import app, db, logger
from anony.core.custom_emoji import localized_text
from anony.core.rich_messages import unicode_heading

lang_codes = {
    "en": "English",
    "my": "မြန်မာဘာသာ",
}


_TITLE_RE = re.compile(
    r"^\s*(?:(?:<tg-emoji\b[^>]*>.*?</tg-emoji\s*>)|[^\w<\n])*\s*"
    r"(?:<u>)?<b>.*?</b>(?:</u>)?",
    re.IGNORECASE | re.DOTALL,
)

_HEADING_MESSAGES = {
    "auth_list": ("heading_playback_access", " · {0}", False),
    "help_menu": ("heading_help", "", False),
    "help_admins": ("heading_controls", "", False),
    "help_auth": ("heading_access", "", False),
    "help_blist": ("heading_safety", "", False),
    "help_lang": ("heading_language", "", False),
    "help_ping": ("heading_bot", "", False),
    "help_play": ("heading_music", "", False),
    "help_queue": ("heading_queue", "", False),
    "help_stats": ("heading_insights", "", False),
    "help_sudo": ("heading_sudo", "", False),
    "lang_choose": ("heading_language", "", True),
    "play_media": ("heading_now_playing", "", False),
    "play_queued": ("heading_added_to_queue", " · #{0}", False),
    "queue_curr": ("heading_queue", "", False),
    "sessions_list": ("heading_sessions", "", False),
    "session_info": ("heading_session", " {0}", False),
    "session_add_prompt": ("heading_add_assistant", "", False),
    "session_phone_prompt": ("heading_phone_number", "", False),
    "session_code_prompt": ("heading_check_telegram", "", False),
    "session_password_prompt": ("heading_two_step", "", False),
    "start_pm": ("heading_welcome", ", {0}", False),
    "start_gp": ("heading_ready_to_play", "", False),
    "start_settings": ("heading_settings", " · {0}", False),
    "trending_title": ("heading_trending", "", False),
    "trending_empty": ("heading_trending", "", False),
    "setup_required": ("heading_setup_required", "", False),
    "setup_ready": ("heading_ready_to_play", "", False),
    "welcome_group": ("heading_welcome", "", False),
    "status_sudo": ("heading_advanced_status", "", False),
    "vc_list": ("heading_active_streams", "", False),
}


def _compose_heading(text: str, heading: str, suffix: str, replace_all: bool):
    match = _TITLE_RE.match(text)
    remainder = text[match.end():] if match else ("" if replace_all else text)
    return localized_text(
        f"<b>{unicode_heading(heading)}{suffix}</b>{remainder}"
    )


class Language:
    """
    Language class for managing multilingual support using JSON language files.
    """

    def __init__(self):
        self.lang_codes = lang_codes
        self.lang_dir = Path("anony/locales")
        self.languages = self.load_files()

    def load_files(self):
        languages = {}
        lang_files = {
            file.stem: file
            for file in self.lang_dir.glob("*.json")
            if file.stem in lang_codes
        }
        for lang_code, lang_file in lang_files.items():
            with open(lang_file, "r", encoding="utf-8") as file:
                languages[lang_code] = {
                    key: localized_text(value)
                    for key, value in json.load(file).items()
                }
        english = languages["en"]
        languages = {
            code: {**english, **translations}
            for code, translations in languages.items()
        }
        for translations in languages.values():
            for key, value in list(translations.items()):
                if key.startswith("heading_"):
                    translations[key] = localized_text(
                        unicode_heading(value)
                    )
            for message_key, definition in _HEADING_MESSAGES.items():
                heading_key, suffix, replace_all = definition
                text = translations.get(message_key)
                heading = translations.get(heading_key)
                if text is None or heading is None:
                    continue
                translations[message_key] = _compose_heading(
                    text, heading, suffix, replace_all
                )

        logger.info(f"Loaded languages: {', '.join(languages.keys())}")
        return languages

    async def get_lang(self, chat_id: int) -> dict:
        lang_code = await db.get_lang(chat_id)
        return self.languages.get(lang_code, self.languages["en"])

    def get_languages(self) -> dict:
        files = {f.stem for f in self.lang_dir.glob("*.json")}
        return {code: self.lang_codes[code] for code in sorted(files)}

    def language(self):
        def decorator(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                fallen = next(
                    (
                        arg
                        for arg in args
                        if hasattr(arg, "chat") or hasattr(arg, "message")
                    ),
                    None,
                )

                if hasattr(fallen, "chat"):
                    chat = fallen.chat
                elif hasattr(fallen, "message"):
                    chat = fallen.message.chat

                if not chat:
                    return

                lang_dict = self.languages["en"]
                try:
                    if chat.id in db.blacklisted:
                        logger.info(f"Chat {chat.id} is blacklisted, leaving...")
                        return await chat.leave()

                    lang_code = await db.get_lang(chat.id)
                    lang_dict = self.languages.get(lang_code, lang_dict)
                    setattr(fallen, "lang", lang_dict)
                    result = await func(*args, **kwargs)
                    if (
                        hasattr(fallen, "command")
                        and fallen.command
                        and chat.type in {
                            enums.ChatType.GROUP,
                            enums.ChatType.SUPERGROUP,
                        }
                        and await db.get_cmd_delete(chat.id)
                    ):
                        try:
                            await fallen.delete()
                        except Exception:
                            pass
                    return result
                except (errors.ChannelPrivate, errors.MessageIdInvalid, errors.MessageNotModified):
                    return
                except (
                    errors.Forbidden, errors.exceptions.Forbidden,
                    errors.ChatWriteForbidden, errors.exceptions.ChatWriteForbidden,
                ):
                    return
                except Exception as ex:
                    if type(ex).__name__ in {"StopPropagation", "ContinuePropagation"}:
                        raise

                    reference = secrets.token_hex(3).upper()
                    user = getattr(fallen, "from_user", None)
                    sudo = bool(user and user.id in app.sudoers)
                    logger.exception(
                        "Update failed [ref=%s handler=%s update=%s chat=%s user=%s]",
                        reference,
                        func.__name__,
                        type(fallen).__name__,
                        getattr(chat, "id", None),
                        getattr(user, "id", None),
                    )

                    if sudo:
                        text = lang_dict["feedback_error_sudo"].format(
                            reference,
                            func.__name__,
                            type(ex).__name__,
                            escape(str(ex)[:700]) or "No details provided",
                        )
                    else:
                        text = lang_dict["feedback_error_user"].format(reference)

                    try:
                        if hasattr(fallen, "reply_text"):
                            sent = await fallen.reply_text(
                                text, quote=True, disable_notification=True
                            )
                            if not sudo:
                                from anony.helpers import feedback

                                await feedback.keep_or_clean(sent, error=True)
                            return sent
                        callback_text = (
                            f"Could not finish that. Reference: {reference}"
                            if not sudo
                            else f"Failed: {type(ex).__name__}. Reference: {reference}"
                        )
                        return await fallen.answer(
                            callback_text,
                            show_alert=sudo,
                        )
                    except Exception:
                        logger.exception(
                            "Could not deliver update failure feedback [ref=%s]",
                            reference,
                        )
                        return

            return wrapper

        return decorator
