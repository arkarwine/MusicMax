"""Stable builders for Telegram callback data.

These helpers centralize existing callback strings. They intentionally do not
parse callbacks or perform any handler, permission, or feature logic.
"""

MAX_CALLBACK_BYTES = 64

CANCEL_DOWNLOAD = "cancel_dl"
LANGUAGE_ROOT = "language"
LANGUAGE_ROOT_NEW = "language new"
HELP_HOME = "help home"


def build(namespace: str, *parts: object) -> str:
    """Join scalar callback tokens and enforce Telegram's byte limit."""
    tokens = [str(namespace), *(str(part) for part in parts if part is not None)]
    invalid_token = any(
        not token or any(char.isspace() for char in token)
        for token in tokens
    )
    if not tokens[0] or invalid_token:
        raise ValueError("callback tokens must be non-empty and contain no whitespace")
    data = " ".join(tokens)
    if len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        raise ValueError("callback data exceeds Telegram's 64-byte limit")
    return data


def controls(action: str, chat_id: int, context: object | None = None) -> str:
    return build("controls", action, chat_id, context)


def help(destination: str | None = None) -> str:
    return build("help", destination)


def language_change(code: str) -> str:
    return build("lang_change", code)


def settings(chat_id: int, action: str | None = None) -> str:
    return build("settings", chat_id, action)


def settings_language(chat_id: int, code: str) -> str:
    return build("settings_lang", chat_id, code)


def session(action: str, *parts: object) -> str:
    return build("session", action, *parts)


def runtime_config(action: str, key: str) -> str:
    return build("runtime_config", action, key)


def theme(action: str, theme_id: str) -> str:
    return build("theme", action, theme_id)


def stats(action: str) -> str:
    return build("stats", action)


def trending(action: str = "view") -> str:
    return build("trending", action)


def setup(action: str = "check") -> str:
    return build("setup", action)
