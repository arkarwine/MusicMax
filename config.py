import logging
import re
from os import getenv
from string import Formatter
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class Config:
    PLAY_CONTROL_NAMES = ("loop", "stop", "pause", "skip", "replay")
    DEFAULT_PLAY_CONTROLS_LAYOUT = ",".join(PLAY_CONTROL_NAMES)
    PLAY_TEMPLATE_FIELDS = frozenset({
        "image", "title", "title_link", "duration", "requester",
        "source_url",
    })
    MAX_PLAY_TEMPLATE_LENGTH = 900

    RUNTIME_FIELDS = {
        "duration_limit": "DURATION_LIMIT",
        "queue_limit": "QUEUE_LIMIT",
        "playlist_limit": "PLAYLIST_LIMIT",
        "support_channel": "SUPPORT_CHANNEL",
        "support_chat": "SUPPORT_CHAT",
        "auto_leave": "AUTO_LEAVE",
        "auto_end": "AUTO_END",
        "thumb_gen": "THUMB_GEN",
        "video_play": "VIDEO_PLAY",
        "play_button_text": "PLAY_BUTTON_TEXT",
        "play_button_url": "PLAY_BUTTON_URL",
        "play_image": "PLAY_IMAGE",
        "play_controls_layout": "PLAY_CONTROLS_LAYOUT",
        "play_message_template_en": "PLAY_MESSAGE_TEMPLATE_EN",
        "play_message_template_my": "PLAY_MESSAGE_TEMPLATE_MY",
        "lang_code": "LANG_CODE",
        "default_thumb": "DEFAULT_THUMB",
        "ping_img": "PING_IMG",
        "start_img": "START_IMG",
    }

    def __init__(self):
        self.API_ID = int(getenv("API_ID", 0))
        self.API_HASH = getenv("API_HASH")

        self.BOT_TOKEN = getenv("BOT_TOKEN")
        self.DATABASE_PATH = getenv("DATABASE_PATH", "data/anonxmusic.db")

        self.OWNER_ID = int(getenv("OWNER_ID", 0))

        self.DURATION_LIMIT = int(getenv("DURATION_LIMIT", 60)) * 60
        self.QUEUE_LIMIT = int(getenv("QUEUE_LIMIT", 20))
        self.PLAYLIST_LIMIT = int(getenv("PLAYLIST_LIMIT", 20))

        first_session = getenv("SESSION")
        self.SESSIONS = (first_session,) if first_session else ()

        self.SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/fallenx")
        self.SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/DevilsHeavenMF")

        self.AUTO_LEAVE: bool = getenv("AUTO_LEAVE", "False").lower() == "true"
        self.AUTO_END: bool = getenv("AUTO_END", "False").lower() == "true"
    
        self.THUMB_GEN: bool = getenv("THUMB_GEN", "True").lower() == "true"
        self.VIDEO_PLAY: bool = getenv("VIDEO_PLAY", "True").lower() == "true"
        self.RICH_MESSAGES: bool = (
            getenv("RICH_MESSAGES", "True").lower() == "true"
        )
        self.PLAY_BUTTON_TEXT = getenv("PLAY_BUTTON_TEXT", "").strip()
        self.PLAY_BUTTON_URL = getenv("PLAY_BUTTON_URL", "").strip()
        self.PLAY_IMAGE = getenv("PLAY_IMAGE", "").strip()
        try:
            self.PLAY_CONTROLS_LAYOUT = self._normalize_play_controls_layout(
                getenv(
                    "PLAY_CONTROLS_LAYOUT",
                    self.DEFAULT_PLAY_CONTROLS_LAYOUT,
                )
            )
        except ValueError:
            self.PLAY_CONTROLS_LAYOUT = self.DEFAULT_PLAY_CONTROLS_LAYOUT
        self.PLAY_MESSAGE_TEMPLATE_EN = self._environment_play_template(
            "PLAY_MESSAGE_TEMPLATE_EN"
        )
        self.PLAY_MESSAGE_TEMPLATE_MY = self._environment_play_template(
            "PLAY_MESSAGE_TEMPLATE_MY"
        )

        language = getenv("LANG_CODE", "en").lower()
        self.LANG_CODE = language if language in {"en", "my"} else "en"

        self.COOKIES_URL = [
            url for url in getenv("COOKIES_URL", "").split(" ")
            if url and "batbin.me" in url
        ]
        self.DEFAULT_THUMB = getenv("DEFAULT_THUMB", "https://te.legra.ph/file/3e40a408286d4eda24191.jpg")
        self.PING_IMG = getenv("PING_IMG", "https://files.catbox.moe/haagg2.png")
        self.START_IMG = getenv("START_IMG", "").strip()
        self._runtime_defaults = {
            key: getattr(self, attr)
            for key, attr in self.RUNTIME_FIELDS.items()
        }

    @staticmethod
    def _boolean(value: str) -> bool:
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enable", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disable", "disabled"}:
            return False
        raise ValueError("Use on or off")

    @staticmethod
    def _url(value: str, *, telegram: bool = False) -> str:
        normalized = value.strip()
        if len(normalized) > 512:
            raise ValueError("URL is too long")
        if telegram and normalized.startswith("@"):
            normalized = f"https://t.me/{normalized[1:]}"
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Use a complete http(s) URL")
        return normalized

    @classmethod
    @classmethod
    def _media(cls, value: str, *, telegram: bool = False) -> str:
        normalized = value.strip()
        if normalized.startswith(("http://", "https://")) or (
            telegram and normalized.startswith("@")
        ):
            return cls._url(normalized, telegram=telegram)
        if (
            20 <= len(normalized) <= 512
            and re.fullmatch(r"[A-Za-z0-9_-]+", normalized)
        ):
            return normalized
        raise ValueError(
            "Use a complete http(s) URL or Telegram media file ID"
        )

    def _normalize_play_controls_layout(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "-":
            return "-"
        if not normalized:
            raise ValueError(
                "Control layout cannot be empty; use - to hide all"
            )

        rows = []
        seen = set()
        allowed = set(cls.PLAY_CONTROL_NAMES)
        for raw_row in normalized.split("|"):
            tokens = [token.strip() for token in raw_row.split(",")]
            if not tokens or any(not token for token in tokens):
                raise ValueError("Control layout contains an empty position")
            for token in tokens:
                if token not in allowed:
                    valid = ", ".join(cls.PLAY_CONTROL_NAMES)
                    raise ValueError(
                        f"Unknown control {token}; use: {valid}"
                    )
                if token in seen:
                    raise ValueError(f"Control {token} is duplicated")
                seen.add(token)
            rows.append(",".join(tokens))
        return "|".join(rows)

    @classmethod
    def _validate_play_message_template(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return ""
        if len(value) > cls.MAX_PLAY_TEMPLATE_LENGTH:
            raise ValueError(
                f"Play template must be {cls.MAX_PLAY_TEMPLATE_LENGTH} "
                "characters or less"
            )
        try:
            fields = list(Formatter().parse(value))
        except ValueError as exc:
            raise ValueError("Play template contains malformed braces") from exc
        for _, field, format_spec, conversion in fields:
            if field is None:
                continue
            if field not in cls.PLAY_TEMPLATE_FIELDS:
                valid = ", ".join(sorted(cls.PLAY_TEMPLATE_FIELDS))
                raise ValueError(
                    f"Unknown play placeholder {field}; use: {valid}"
                )
            if format_spec or conversion:
                raise ValueError(
                    "Play placeholders do not support formats or conversions"
                )
        image_count = sum(
            field == "image" for _, field, _, _ in fields
            if field is not None
        )
        if image_count > 1:
            raise ValueError("Play template can contain {image} only once")
        if image_count and not re.search(
            r"(?m)^\s*\{image\}\s*$", value
        ):
            raise ValueError(
                "The {image} placeholder must be on its own line"
            )
        fence = chr(96) * 3
        if value.count(fence) % 2:
            raise ValueError("Play template has an unmatched code fence")
        inline_text = "".join(value.split(fence)[::2])
        for delimiter in ("**", "__", "~~", chr(96)):
            count = 0
            index = 0
            while index < len(inline_text):
                if inline_text[index] == "\\":
                    index += 2
                    continue
                if inline_text.startswith(delimiter, index):
                    count += 1
                    index += len(delimiter)
                else:
                    index += 1
            if count % 2:
                raise ValueError(
                    f"Play template has an unmatched {delimiter} delimiter"
                )
        link_markers = value.count("](")
        valid_links = re.findall(
            r"\[(?:\\.|[^\]])+\]\((?:\\.|[^)])+\)",
            value,
        )
        if link_markers != len(valid_links):
            raise ValueError("Play template contains a malformed link")
        return value

    @classmethod
    def _environment_play_template(cls, name: str) -> str:
        value = getenv(name, "")
        try:
            return cls._validate_play_message_template(value)
        except ValueError as exc:
            logger.warning("Ignored invalid %s: %s", name, exc)
            return ""

    def set_runtime(self, key: str, raw_value: str) -> str:
        """Validate, normalize, and immediately apply a safe runtime value."""
        key = key.strip().lower()
        if key not in self.RUNTIME_FIELDS:
            raise KeyError(key)

        if key == "duration_limit":
            minutes = int(raw_value)
            if not 1 <= minutes <= 1440:
                raise ValueError("Duration must be between 1 and 1440 minutes")
            value, stored = minutes * 60, str(minutes)
        elif key in {"queue_limit", "playlist_limit"}:
            value = int(raw_value)
            if not 1 <= value <= 1000:
                raise ValueError("Limit must be between 1 and 1000")
            stored = str(value)
        elif key in {"auto_leave", "auto_end", "thumb_gen", "video_play"}:
            value = self._boolean(raw_value)
            stored = "on" if value else "off"
        elif key == "lang_code":
            value = raw_value.strip().lower()
            if value not in {"en", "my"}:
                raise ValueError("Language must be en or my")
            stored = value
        elif key == "play_button_text":
            value = raw_value.strip()
            if value == "-":
                value = ""
            if len(value) > 64:
                raise ValueError("Playback button text must be 64 characters or less")
            stored = value
        elif key == "play_button_url":
            normalized = raw_value.strip()
            value = "" if normalized == "-" else self._url(normalized, telegram=True)
            stored = value
        elif key in {"play_image", "start_img"}:
            normalized = raw_value.strip()
            value = "" if normalized == "-" else self._media(
                normalized, telegram=True
            )
            stored = value
        elif key == "play_controls_layout":
            value = self._normalize_play_controls_layout(raw_value)
            stored = value
        elif key in {
            "play_message_template_en", "play_message_template_my"
        }:
            value = self._validate_play_message_template(raw_value)
            stored = value
        elif key in {"support_channel", "support_chat"}:
            value = self._url(raw_value, telegram=True)
            stored = value
        elif key in {"default_thumb", "ping_img"}:
            value = self._media(raw_value)
            stored = value
        else:
            value = self._url(raw_value)
            stored = value

        setattr(self, self.RUNTIME_FIELDS[key], value)
        return stored

    def reset_runtime(self, key: str) -> None:
        key = key.strip().lower()
        if key not in self.RUNTIME_FIELDS:
            raise KeyError(key)
        setattr(self, self.RUNTIME_FIELDS[key], self._runtime_defaults[key])

    def runtime_display(self, key: str) -> str:
        key = key.strip().lower()
        attr = self.RUNTIME_FIELDS[key]
        value = getattr(self, attr)
        if key == "duration_limit":
            return str(value // 60)
        if key in {
            "play_button_text", "play_button_url", "play_image",
            "start_img",
        } and not value:
            return "disabled"
        if key == "play_controls_layout" and value == "-":
            return "disabled"
        if key in {
            "play_message_template_en", "play_message_template_my"
        }:
            return "default" if not value else f"custom · {len(value)} chars"
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value)

    def playback_button(self) -> tuple[str, str] | None:
        text = self.PLAY_BUTTON_TEXT.strip()
        url = self.PLAY_BUTTON_URL.strip()
        if not text or not url or len(text) > 64:
            return None
        try:
            return text, self._url(url, telegram=True)
        except ValueError:
            return None

    def play_image_url(self) -> str | None:
        value = self.PLAY_IMAGE.strip()
        if not value:
            return None
        try:
            return self._media(value, telegram=True)
        except ValueError:
            return None

    def play_controls_layout(self) -> tuple[tuple[str, ...], ...]:
        value = self.PLAY_CONTROLS_LAYOUT
        if value == "-":
            return ()
        return tuple(
            tuple(row.split(",")) for row in value.split("|")
        )

    def play_message_template(self, lang_code: str) -> str | None:
        attr = (
            "PLAY_MESSAGE_TEMPLATE_MY"
            if str(lang_code).lower() == "my"
            else "PLAY_MESSAGE_TEMPLATE_EN"
        )
        return getattr(self, attr).strip() or None

    def runtime_export(self, key: str, *, default: bool = False):
        """Return one safe runtime value in the typed theme JSON format."""
        key = key.strip().lower()
        if key not in self.RUNTIME_FIELDS:
            raise KeyError(key)
        value = (
            self._runtime_defaults[key]
            if default
            else getattr(self, self.RUNTIME_FIELDS[key])
        )
        if key == "duration_limit":
            return value // 60
        if key in {"queue_limit", "playlist_limit"}:
            return int(value)
        if key in {"auto_leave", "auto_end", "thumb_gen", "video_play"}:
            return bool(value)
        if key == "play_controls_layout":
            if value == "-":
                return []
            return [row.split(",") for row in value.split("|")]
        if key in {
            "play_button_text", "play_button_url", "play_image", "start_img",
        } and not value:
            return None
        if key in {"play_message_template_en", "play_message_template_my"}:
            return value or None
        return value

    @staticmethod
    def runtime_import_value(key: str, value) -> str:
        """Convert a typed theme value to the existing runtime validator input."""
        if isinstance(value, bool):
            return "on" if value else "off"
        if value is None:
            if key in {
                "play_message_template_en", "play_message_template_my",
            }:
                return ""
            return "-"
        if key == "play_controls_layout" and isinstance(value, list):
            if not value:
                return "-"
            if any(not isinstance(row, list) for row in value):
                raise ValueError("Play controls must be an array of rows")
            return "|".join(",".join(map(str, row)) for row in value)
        if isinstance(value, (str, int)):
            return str(value)
        raise ValueError(f"Unsupported value type for {key}")

    def check(self):
        missing = [
            var
            for var in ["API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID"]
            if not getattr(self, var)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
