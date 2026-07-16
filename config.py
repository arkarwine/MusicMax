from os import getenv
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

class Config:
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
        elif key in {"support_channel", "support_chat"}:
            value = self._url(raw_value, telegram=True)
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
        if key in {"play_button_text", "play_button_url"} and not value:
            return "disabled"
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

    def check(self):
        missing = [
            var
            for var in ["API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID"]
            if not getattr(self, var)
        ]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")
