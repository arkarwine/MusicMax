"""Bot API 10.2 rich-message transport with safe legacy fallback hooks."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass
from html import unescape
from io import IOBase
from pathlib import Path

import aiohttp


_TAG_RE = re.compile(r"<[^>]+>")
_TG_EMOJI_RE = re.compile(
    r"<tg-emoji\b[^>]*>(.*?)</tg-emoji\s*>", re.I | re.S
)
_LEADING_HEADING_RE = re.compile(
    r"^\s*(?:(?:<tg-emoji\b[^>]*>.*?</tg-emoji\s*>)|[^\w<\n])+\s*"
    r"(?:<u>)?<b>(?P<title>.*?)</b>(?:</u>)?",
    re.I | re.S,
)
_PLAIN_HEADING_RE = re.compile(
    r"^\s*(?:<u>)?<b>(?P<title>.*?)</b>(?:</u>)?", re.I | re.S
)
_UNDERLINE_HEADING_RE = re.compile(
    r"^\s*<u>(?P<title>.*?)</u>", re.I | re.S
)
_SECONDARY_TRACK_RE = re.compile(
    r"\n\n<b>(<a\b[^>]*>.*?</a>)</b>", re.I | re.S
)

_SMALL_CAPS = str.maketrans({
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e",
    "ғ": "f", "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j",
    "ᴋ": "k", "ʟ": "l", "ᴍ": "m", "ɴ": "n", "ᴏ": "o",
    "ᴘ": "p", "ʀ": "r", "s": "s", "ᴛ": "t", "ᴜ": "u",
    "ᴠ": "v", "ᴡ": "w", "x": "x", "ʏ": "y", "ᴢ": "z",
})

_TITLE_RENAMES = {
    "now playing": "Now playing",
    "queue": "Queue",
    "what would you like to do?": "What would you like to do?",
    "choose a language": "Choose a language",
    "assistant sessions": "Assistant sessions",
    "assistants": "Assistant sessions",
    "advanced status": "Advanced status",
    "trending tracks": "Trending tracks",
    "runtime configuration": "Runtime configuration",
    "ready to play": "Ready to play",
    "one thing left": "Setup required",
    "thanks for adding me": "Welcome",
    "new chat log": "New chat log",
    "new user log": "New user log",
    "list of active streams:": "Active streams",
    "playback access": "Playback access",
    "add an assistant": "Add an assistant",
    "phone number": "Phone number",
    "check telegram": "Check Telegram",
    "two-step verification": "Two-step verification",
    "request failed": "Request failed",
    "bot insights": "Bot insights",
    "settings": "Settings",
    "controls": "Controls",
    "access": "Access",
    "safety": "Safety",
    "bot": "Bot",
    "music": "Music",
    "insights": "Insights",
    "sudo": "Sudo",
    "which song would you like?": "Which song would you like?",
    "sign-in failed": "Sign-in failed",
    "log group configured": "Log group configured",
    "log group cleared": "Log group cleared",
    "could not configure the log group": "Could not configure the log group",
    "online": "Online",
    "pong!": "Pong",
}

_PRIMARY = {
    "Now playing", "Queue", "What would you like to do?", "Choose a language",
    "Assistant sessions", "Advanced status", "Trending tracks",
    "Runtime configuration", "Active streams", "Playback access",
    "Bot insights", "Settings", "Welcome",
    "Controls", "Access", "Safety", "Bot", "Music", "Insights", "Sudo",
}
_EXCLUDED = {"usage:", "output:", "owner:", "sudo users:"}


def _plain_title(value: str) -> str:
    value = _TG_EMOJI_RE.sub(r"\1", value)
    value = unescape(_TAG_RE.sub("", value))
    value = unicodedata.normalize("NFKC", value).translate(_SMALL_CAPS)
    value = "".join(
        char for char in value
        if unicodedata.category(char) not in {"So", "Sk"}
        and char not in {"\ufe0f", "\u200d"}
    )
    return " ".join(value.split()).strip()


def _clean_title(value: str, text: str) -> tuple[str, int] | None:
    title = _plain_title(value)
    lowered = title.casefold()
    if not any("a" <= char.lower() <= "z" for char in title):
        return None
    if lowered in _EXCLUDED:
        return None
    if lowered.startswith("queued · #"):
        return f"Added to queue · #{title.split('#', 1)[1]}", 3
    category = re.fullmatch(r"commands in the\s+(.+?)\s+category:", title, re.I)
    if re.fullmatch(r"assistant session\s+\d+", lowered):
        return title, 2
    if lowered.startswith("playback access"):
        return "Playback access", 1
    if lowered.startswith("added ") and lowered.endswith(
        "tracks from the playlist to queue:"
    ):
        return title.rstrip(":"), 3
    if lowered.startswith("remove session ") or lowered == "assistant session added":
        return title, 3
    if category:
        return _plain_title(category.group(1)).title(), 1
    if lowered.startswith("welcome,"):
        return "Welcome" + title[len("Welcome"):], 1
    if lowered.endswith(" play log"):
        return title[:-8] + " play log", 3
    if lowered.endswith(" stats"):
        return title[:-6] + " stats", 1
    renamed = _TITLE_RENAMES.get(lowered)
    if renamed:
        return renamed, 1 if renamed in _PRIMARY else 3
    if re.search(r"\nSession \d+ ·", text):
        return title, 2
    if "Choose how music works in this group." in text:
        return title, 1
    if re.search(r"\n\n<blockquote>\d+ assistants", text):
        return title, 1
    if any(token in lowered for token in (
        "assistant is banned", "session action failed", "assistant saved as session",
        "updated immediately", "restored.", "added to queue",
    )):
        return title.rstrip("."), 3
    return None


def promote_heading(text: str) -> str | None:
    """Convert a recognized English legacy title into native rich HTML."""
    if not isinstance(text, str) or not text:
        return None
    match = _LEADING_HEADING_RE.match(text) or _PLAIN_HEADING_RE.match(text)
    if match is None:
        match = _UNDERLINE_HEADING_RE.match(text)
    if match is None:
        return None
    heading = _clean_title(match.group("title"), text)
    if heading is None:
        return None
    title, level = heading
    rich = f"<h{level}>{title}</h{level}>" + text[match.end():]
    rich = rich.replace("<blockquote expandable>", "<blockquote>")
    if title in {"Now playing", "Queue"} or title.startswith("Added to queue"):
        rich = _SECONDARY_TRACK_RE.sub(r"\n\n<h2>\1</h2>", rich, count=1)
    return rich


def bot_api_dict(value):
    """Serialize Pyrogram objects without their diagnostic `_` type keys."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [bot_api_dict(item) for item in value]
    if isinstance(value, dict):
        return {
            key: bot_api_dict(item)
            for key, item in value.items()
            if key != "_" and item is not None
        }
    return bot_api_dict(json.loads(str(value)))


@dataclass(slots=True)
class RichMedia:
    media: object
    kind: str = "photo"


class RichMessageService:
    def __init__(self, client, token: str, logger, *, enabled: bool = True):
        self.client = client
        self.token = token
        self.logger = logger
        self.enabled = bool(enabled and token)
        self.capable = True
        self.session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session

    @staticmethod
    def _source(media: object) -> object:
        return getattr(media, "media", media)

    def _rich_message(self, content, media: RichMedia | None, stack: ExitStack):
        if isinstance(content, str):
            result: dict = {"html": content}
        elif isinstance(content, list):
            result = {"blocks": list(content)}
        elif isinstance(content, dict) and any(
            key in content for key in ("html", "markdown", "blocks")
        ):
            result = dict(content)
        else:
            raise ValueError("Rich content must contain html, markdown, or blocks")
        files: dict[str, tuple[object, str]] = {}
        if media is None:
            return result, files
        source = self._source(media.media)
        attachment = source
        local_path = None
        if isinstance(source, Path):
            source = str(source)
        if isinstance(source, str) and not source.startswith(("http://", "https://")):
            try:
                candidate = Path(source)
                if candidate.is_file():
                    local_path = candidate
            except OSError:
                local_path = None
        if local_path is not None:
            handle = stack.enter_context(open(local_path, "rb"))
            attachment = "attach://rich_media_0"
            files["rich_media_0"] = (handle, local_path.name)
        elif isinstance(source, IOBase) or hasattr(source, "read"):
            attachment = "attach://rich_media_0"
            files["rich_media_0"] = (
                source,
                Path(getattr(source, "name", "media.bin")).name,
            )
        media_type = "video" if media.kind == "animation" else media.kind
        input_media = {"type": media.kind, "media": attachment}
        if "blocks" in result:
            field = media.kind
            result["blocks"].insert(0, {
                "type": media.kind,
                field: input_media,
            })
        else:
            if media_type == "photo":
                media_tag = '<img src="tg://photo?id=hero"/>'
            elif media_type == "audio":
                media_tag = '<audio src="tg://audio?id=hero"></audio>'
            else:
                media_tag = '<video src="tg://video?id=hero"></video>'
            if "html" in result:
                result["html"] = f'{media_tag}\n{result["html"]}'
            else:
                result["markdown"] = (
                    f'![](tg://{media_type}?id=hero)\n{result["markdown"]}'
                )
            result["media"] = [{"id": "hero", "media": input_media}]
        return result, files

    async def _request(self, method: str, payload: dict, files: dict):
        session = await self._session()
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        if files:
            form = aiohttp.FormData()
            for key, value in payload.items():
                form.add_field(
                    key,
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list)) else str(value),
                )
            for key, (handle, filename) in files.items():
                form.add_field(
                    key,
                    handle,
                    filename=filename,
                    content_type=mimetypes.guess_type(filename)[0]
                    or "application/octet-stream",
                )
            response_context = session.post(url, data=form)
        else:
            response_context = session.post(url, json=payload)
        async with response_context as response:
            status = response.status
            data = await response.json(content_type=None)
        if not data.get("ok"):
            description = str(data.get("description", "Unknown Bot API error"))
            description_lower = description.lower()
            unavailable = (
                status == 404
                or data.get("error_code") == 404
                or any(phrase in description_lower for phrase in (
                    "method not found", "unknown method", "method is not available"
                ))
            )
            if unavailable:
                self.capable = False
                self.logger.warning("Bot API rich messages are unavailable: %s", description)
            else:
                self.logger.warning("Rich message %s failed: %s", method, description)
            return None
        return data.get("result")

    async def _bound_message(self, chat_id, result):
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not message_id:
            raise RuntimeError("Telegram accepted a rich message without a message ID")
        last_error = None
        for _ in range(3):
            try:
                return await self.client.get_messages(chat_id, message_id)
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(0.2)
        raise RuntimeError("Could not bind the sent rich message") from last_error

    async def send(
        self, chat_id, content, *, media: RichMedia | None = None,
        fallback_text: str | None = None,
        reply_markup=None, reply_parameters=None, message_thread_id=None,
        disable_notification=None, protect_content=None,
    ):
        if not self.enabled or not self.capable:
            return None
        try:
            with ExitStack() as stack:
                rich_message, files = self._rich_message(content, media, stack)
                payload = {"chat_id": chat_id, "rich_message": rich_message}
                for key, value in (
                    ("reply_markup", bot_api_dict(reply_markup)),
                    ("reply_parameters", bot_api_dict(reply_parameters)),
                    ("message_thread_id", message_thread_id),
                    ("disable_notification", disable_notification),
                    ("protect_content", protect_content),
                ):
                    if value is not None:
                        payload[key] = value
                result = await self._request("sendRichMessage", payload, files)
            return None if result is None else await self._bound_message(chat_id, result)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, TypeError,
                ValueError, RuntimeError) as exc:
            self.logger.warning("Rich message send failed; using HTML fallback: %s", exc)
            return None

    async def edit(
        self, chat_id, message_id: int, content, *,
        media: RichMedia | None = None, reply_markup=None,
        fallback_text: str | None = None,
    ):
        if not self.enabled or not self.capable:
            return None
        try:
            with ExitStack() as stack:
                rich_message, files = self._rich_message(content, media, stack)
                payload = {
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "rich_message": rich_message,
                }
                if reply_markup is not None:
                    payload["reply_markup"] = bot_api_dict(reply_markup)
                result = await self._request("editMessageText", payload, files)
            return None if result is None else await self._bound_message(chat_id, result)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError, TypeError,
                ValueError, RuntimeError) as exc:
            self.logger.warning("Rich message edit failed; using HTML fallback: %s", exc)
            return None

    async def replace_placeholder(self, placeholder, content, **kwargs):
        sent = await self.send(
            placeholder.chat.id,
            content,
            reply_parameters={
                "message_id": placeholder.reply_to_message_id
            } if placeholder.reply_to_message_id else None,
            message_thread_id=getattr(placeholder, "message_thread_id", None),
            **kwargs,
        )
        if sent is not None:
            try:
                await placeholder.delete()
            except Exception:
                self.logger.debug("Could not delete replaced placeholder", exc_info=True)
        return sent
