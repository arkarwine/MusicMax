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
    START_BUTTON_NAMES = (
        "add", "help", "language", "stats", "trending",
        "support", "channel", "owner",
    )
    DEFAULT_START_BUTTONS_LAYOUT = (
        "add|help,language,stats|trending|support,channel|owner"
    )
    START_BUTTON_TEXT_FIELDS = {
        "start_add_text": "START_ADD_TEXT",
        "start_help_text": "START_HELP_TEXT",
        "start_language_text": "START_LANGUAGE_TEXT",
        "start_stats_text": "START_STATS_TEXT",
        "start_trending_text": "START_TRENDING_TEXT",
        "start_support_text": "START_SUPPORT_TEXT",
        "start_channel_text": "START_CHANNEL_TEXT",
        "start_owner_text": "START_OWNER_TEXT",
    }
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
        "start_buttons_layout": "START_BUTTONS_LAYOUT",
        **START_BUTTON_TEXT_FIELDS,
        "lang_code": "LANG_CODE",
        "default_thumb": "DEFAULT_THUMB",
        "ping_img": "PING_IMG",
        "start_img": "START_IMG",
    }

    @staticmethod
    def _environment_int(
        name: str,
        default: int,
        *,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        raw = getenv(name)
        if raw is None or not raw.strip():
            return default
        try:
            value = int(raw.strip())
        except ValueError:
            logger.warning("Ignored invalid %s; using %s", name, default)
            return default
        if minimum is not None and value < minimum:
            logger.warning("Ignored out-of-range %s; using %s", name, default)
            return default
        if maximum is not None and value > maximum:
            logger.warning("Ignored out-of-range %s; using %s", name, default)
            return default
        return value

    @classmethod
    def _environment_bool(cls, name: str, default: bool) -> bool:
        raw = getenv(name)
        if raw is None or not raw.strip():
            return default
        try:
            return cls._boolean(raw)
        except ValueError:
            logger.warning("Ignored invalid %s; using %s", name, default)
            return default

    @classmethod
    def _environment_url(
        cls, name: str, default: str = "", *, telegram: bool = False
    ) -> str:
        raw = getenv(name, default).strip()
        if not raw:
            return ""
        try:
            return cls._url(raw, telegram=telegram)
        except ValueError as exc:
            logger.warning("Ignored invalid %s: %s", name, exc)
            return cls._url(default, telegram=telegram) if default else ""

    @classmethod
    def _environment_media(
        cls, name: str, default: str = "", *, telegram: bool = False
    ) -> str:
        raw = getenv(name, default).strip()
        if not raw:
            return ""
        try:
            return cls._media(raw, telegram=telegram)
        except ValueError as exc:
            logger.warning("Ignored invalid %s: %s", name, exc)
            return cls._media(default, telegram=telegram) if default else ""

    def __init__(self):
        self.API_ID = self._environment_int("API_ID", 0, minimum=1)
        self.API_HASH = (getenv("API_HASH") or "").strip()

        self.BOT_TOKEN = (getenv("BOT_TOKEN") or "").strip()
        self.DATABASE_PATH = (
            getenv("DATABASE_PATH", "data/anonxmusic.db").strip()
            or "data/anonxmusic.db"
        )

        self.OWNER_ID = self._environment_int("OWNER_ID", 0, minimum=1)

        self.DURATION_LIMIT = self._environment_int(
            "DURATION_LIMIT", 60, minimum=1, maximum=1440
        ) * 60
        self.QUEUE_LIMIT = self._environment_int(
            "QUEUE_LIMIT", 20, minimum=1, maximum=1000
        )
        self.PLAYLIST_LIMIT = self._environment_int(
            "PLAYLIST_LIMIT", 20, minimum=1, maximum=1000
        )

        first_session = (getenv("SESSION") or "").strip()
        self.SESSIONS = (first_session,) if first_session else ()

        self.SUPPORT_CHANNEL = self._environment_url(
            "SUPPORT_CHANNEL", "https://t.me/fallenx", telegram=True
        )
        self.SUPPORT_CHAT = self._environment_url(
            "SUPPORT_CHAT", "https://t.me/DevilsHeavenMF", telegram=True
        )

        self.AUTO_LEAVE = self._environment_bool("AUTO_LEAVE", False)
        self.AUTO_END = self._environment_bool("AUTO_END", False)
        self.THUMB_GEN = self._environment_bool("THUMB_GEN", True)
        self.VIDEO_PLAY = self._environment_bool("VIDEO_PLAY", True)
        self.RICH_MESSAGES = self._environment_bool("RICH_MESSAGES", True)
        self.WATCHDOG_RESTART_ON_STALL = self._environment_bool(
            "WATCHDOG_RESTART_ON_STALL", False
        )
        self.WATCHDOG_STALL_SECONDS = self._environment_int(
            "WATCHDOG_STALL_SECONDS", 21600, minimum=300, maximum=86400
        )
        self.EXTERNAL_WATCHDOG = self._environment_bool(
            "EXTERNAL_WATCHDOG", False
        )
        self.WATCHDOG_PM2_APP = (getenv("WATCHDOG_PM2_APP") or "GPH").strip() or "GPH"
        self.WATCHDOG_CHECK_INTERVAL = self._environment_int(
            "WATCHDOG_CHECK_INTERVAL", 30, minimum=10, maximum=3600
        )
        self.WATCHDOG_HEARTBEAT_STALE_SECONDS = self._environment_int(
            "WATCHDOG_HEARTBEAT_STALE_SECONDS", 180, minimum=60, maximum=86400
        )
        self.WATCHDOG_UPDATE_STALE_SECONDS = self._environment_int(
            "WATCHDOG_UPDATE_STALE_SECONDS", 900, minimum=300, maximum=86400
        )
        self.WATCHDOG_MIN_UPTIME_SECONDS = self._environment_int(
            "WATCHDOG_MIN_UPTIME_SECONDS", 300, minimum=0, maximum=86400
        )
        self.WATCHDOG_RESTART_COOLDOWN_SECONDS = self._environment_int(
            "WATCHDOG_RESTART_COOLDOWN_SECONDS", 600, minimum=60, maximum=86400
        )
        self.PLAY_BUTTON_TEXT = getenv("PLAY_BUTTON_TEXT", "").strip()
        if len(self.PLAY_BUTTON_TEXT) > 64:
            logger.warning(
                "Ignored PLAY_BUTTON_TEXT longer than 64 characters"
            )
            self.PLAY_BUTTON_TEXT = ""
        self.PLAY_BUTTON_URL = self._environment_url(
            "PLAY_BUTTON_URL", telegram=True
        )
        self.PLAY_IMAGE = self._environment_media(
            "PLAY_IMAGE", telegram=True
        )
        try:
            self.PLAY_CONTROLS_LAYOUT = self._normalize_play_controls_layout(
                getenv(
                    "PLAY_CONTROLS_LAYOUT",
                    self.DEFAULT_PLAY_CONTROLS_LAYOUT,
                )
            )
        except ValueError as exc:
            logger.warning(
                "Ignored invalid PLAY_CONTROLS_LAYOUT: %s", exc
            )
            self.PLAY_CONTROLS_LAYOUT = self.DEFAULT_PLAY_CONTROLS_LAYOUT
        self.PLAY_MESSAGE_TEMPLATE_EN = self._environment_play_template(
            "PLAY_MESSAGE_TEMPLATE_EN"
        )
        self.PLAY_MESSAGE_TEMPLATE_MY = self._environment_play_template(
            "PLAY_MESSAGE_TEMPLATE_MY"
        )
        try:
            self.START_BUTTONS_LAYOUT = self._normalize_start_buttons_layout(
                getenv(
                    "START_BUTTONS_LAYOUT",
                    self.DEFAULT_START_BUTTONS_LAYOUT,
                )
            )
        except ValueError as exc:
            logger.warning(
                "Ignored invalid START_BUTTONS_LAYOUT: %s", exc
            )
            self.START_BUTTONS_LAYOUT = self.DEFAULT_START_BUTTONS_LAYOUT
        for attr in self.START_BUTTON_TEXT_FIELDS.values():
            value = getenv(attr, "").strip()
            if len(value) > 64:
                logger.warning("Ignored %s longer than 64 characters", attr)
                value = ""
            setattr(self, attr, value)

        language = getenv("LANG_CODE", "en").strip().lower()
        self.LANG_CODE = language if language in {"en", "my"} else "en"

        cookie_urls = re.split(r"[\s,]+", getenv("COOKIES_URL", "").strip())
        self.COOKIES_URL = [
            url for url in cookie_urls
            if urlparse(url).scheme == "https" and urlparse(url).netloc
        ]
        if any(url for url in cookie_urls if url) and not self.COOKIES_URL:
            logger.warning("COOKIES_URL contains no valid HTTPS URL")
        self.DEFAULT_THUMB = self._environment_media(
            "DEFAULT_THUMB",
            "https://te.legra.ph/file/3e40a408286d4eda24191.jpg",
        )
        self.PING_IMG = self._environment_media(
            "PING_IMG", "https://files.catbox.moe/haagg2.png"
        )
        self.START_IMG = self._environment_media(
            "START_IMG", telegram=True
        )
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

    @classmethod
    def _normalize_button_layout(
        cls,
        value: str,
        *,
        allowed: tuple[str, ...],
        kind: str,
    ) -> str:
        normalized = value.strip().lower()
        if normalized in {"-", "off", "none", "disabled"}:
            return "-"
        if not normalized:
            raise ValueError(
                f"{kind} layout cannot be empty; use off to hide all"
            )

        rows = []
        seen = set()
        allowed_set = set(allowed)
        for raw_row in normalized.split("|"):
            tokens = [token.strip() for token in raw_row.split(",")]
            if not tokens or any(not token for token in tokens):
                raise ValueError(f"{kind} layout contains an empty position")
            for token in tokens:
                if token not in allowed_set:
                    valid = ", ".join(allowed)
                    raise ValueError(
                        f"Unknown {kind} button {token}; use: {valid}"
                    )
                if token in seen:
                    raise ValueError(f"{kind} button {token} is duplicated")
                seen.add(token)
            rows.append(",".join(tokens))
        return "|".join(rows)

    @classmethod
    def _normalize_play_controls_layout(cls, value: str) -> str:
        return cls._normalize_button_layout(
            value,
            allowed=cls.PLAY_CONTROL_NAMES,
            kind="Control",
        )

    @classmethod
    def _normalize_start_buttons_layout(cls, value: str) -> str:
        return cls._normalize_button_layout(
            value,
            allowed=cls.START_BUTTON_NAMES,
            kind="Start button",
        )

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
        elif key == "start_buttons_layout":
            value = self._normalize_start_buttons_layout(raw_value)
            stored = value
        elif key in self.START_BUTTON_TEXT_FIELDS:
            value = raw_value.strip()
            if value == "-":
                value = ""
            if len(value) > 64:
                raise ValueError("Start button text must be 64 characters or less")
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
        if key in self.START_BUTTON_TEXT_FIELDS and not value:
            return "default"
        if key in {
            "play_image", "start_img", "default_thumb", "ping_img",
        } and not str(value).startswith(("http://", "https://")):
            return "Telegram image"
        if key in {"play_controls_layout", "start_buttons_layout"} and value == "-":
            return "disabled"
        if key == "start_buttons_layout" and value != "disabled":
            return value.replace(",", " · ").replace("|", " / ")
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

    def start_buttons_layout(self) -> tuple[tuple[str, ...], ...]:
        value = self.START_BUTTONS_LAYOUT
        if value == "-":
            return ()
        return tuple(
            tuple(row.split(",")) for row in value.split("|")
        )

    def start_button_text(self, action: str, default: str) -> str:
        attr = self.START_BUTTON_TEXT_FIELDS.get(f"start_{action}_text")
        if not attr:
            return default
        return getattr(self, attr).strip() or default

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
        if key in {"play_controls_layout", "start_buttons_layout"}:
            if value == "-":
                return []
            return [row.split(",") for row in value.split("|")]
        if key in {
            "play_button_text", "play_button_url", "play_image", "start_img",
            *self.START_BUTTON_TEXT_FIELDS,
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
        if key in {"play_controls_layout", "start_buttons_layout"} and isinstance(value, list):
            if not value:
                return "-"
            if any(not isinstance(row, list) for row in value):
                raise ValueError("Button layout must be an array of rows")
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
