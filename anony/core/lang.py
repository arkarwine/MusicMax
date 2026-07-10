# Copyright (c) 2025 AnonymousX1025
# Licensed under the MIT License.
# This file is part of AnonXMusic


import json
import secrets
from html import escape
from functools import wraps
from pathlib import Path

from pyrogram import errors

from anony import app, db, logger

lang_codes = {
    "ar": "العربية",
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "hi": "हिन्दी",
    "ja": "日本語",
    "my": "မြန်မာဘာသာ",
    "pa": "ਪੰਜਾਬੀ",
    "pt": "Português",
    "ru": "Русский",
    "tr": "Türkçe",
    "zh": "中文"
}


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
        lang_files = {file.stem: file for file in self.lang_dir.glob("*.json")}
        for lang_code, lang_file in lang_files.items():
            with open(lang_file, "r", encoding="utf-8") as file:
                languages[lang_code] = json.load(file)
        english = languages["en"]
        languages = {
            code: {**english, **translations}
            for code, translations in languages.items()
        }
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

                if not fallen.from_user:
                    return

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
                    return await func(*args, **kwargs)
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
                            return await fallen.reply_text(
                                text, quote=True, disable_notification=True
                            )
                        callback_text = (
                            f"Could not finish that. Reference: {reference}"
                            if not sudo
                            else f"Failed: {type(ex).__name__}. Reference: {reference}"
                        )
                        return await fallen.answer(callback_text, show_alert=False)
                    except Exception:
                        logger.exception(
                            "Could not deliver update failure feedback [ref=%s]",
                            reference,
                        )
                        return

            return wrapper

        return decorator
