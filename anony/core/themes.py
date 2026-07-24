"""Validated global themes with immutable manifests and per-theme overrides."""

from __future__ import annotations

import asyncio
import copy
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from string import Formatter


SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, SCHEMA_VERSION})
THEME_SCHEMA_REF = "./theme.schema.json"
MAX_THEME_BYTES = 256 * 1024
THEME_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
THEME_ROOT_KEYS = frozenset({
    "$schema", "schema_version", "id", "name", "description", "author", "version",
    "config", "ui", "locales",
})
SURFACES = frozenset({
    "start", "help", "language", "play", "queue", "setup", "settings",
    "stats", "status", "trending", "sessions", "session", "broadcast",
    "active_streams", "access", "logs", "result", "error",
    "runtime_config",
})
KEYBOARD_ACTIONS = {
    "start_private": frozenset({
        "add", "help", "language", "stats", "trending", "support",
        "channel", "owner",
    }),
    "help": frozenset({
        "admins", "auth", "blist", "lang", "ping", "play", "queue",
        "stats", "sudo",
    }),
}
EMOJI_PLACEMENTS = {
    "headings": SURFACES,
    "messages": frozenset({
        "loop_count", "loop_forever", "play_paused", "play_resumed",
        "play_skipped", "play_stopped",
    }),
    "buttons": frozenset({
        "start.add", "start.support", "start.channel", "start.owner",
        "help.admins", "help.auth", "help.blist", "help.lang",
        "help.ping", "help.play", "help.queue", "help.stats", "help.sudo",
        "control.loop", "control.stop", "control.pause", "control.resume",
        "control.skip", "control.replay", "stats.refresh",
        "settings.play_mode", "settings.playback",
        "settings.command_delete",
        "settings.cleanup", "settings.language", "settings.open",
    }),
    "ranks": frozenset(str(index) for index in range(1, 10)),
}

APP_UI_DEFAULTS = {
    "heading_font": "small_caps",
    "icons": True,
    "heading_alignment": "center",
    "separators": True,
    "media_placement": "automatic",
    "tables": {
        "bordered": None,
        "striped": None,
        "header_alignment": None,
        "value_alignment": None,
    },
    "surfaces": {"play": {"heading_alignment": "left"}},
    "keyboards": {},
    "emojis": {"mode": "custom", "registry": {}, "placements": {}},
}


class ThemeError(ValueError):
    """A safe, user-facing theme validation or lifecycle error."""


@dataclass(frozen=True, slots=True)
class Theme:
    schema_version: int
    id: str
    name: str
    description: str
    author: str
    version: str
    config: dict
    ui: dict
    locales: dict
    builtin: bool = False

    def document(self) -> dict:
        return {
            "$schema": THEME_SCHEMA_REF,
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "author": self.author,
            "version": self.version,
            "config": copy.deepcopy(self.config),
            "ui": copy.deepcopy(self.ui),
            "locales": copy.deepcopy(self.locales),
        }


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = "theme-" + slug
    return slug[:32].rstrip("-") or "theme"


def _merge(base: dict, update: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _format_fields(value: str) -> set[str]:
    try:
        return {
            field for _, field, _, _ in Formatter().parse(value)
            if field is not None
        }
    except ValueError as exc:
        raise ThemeError("Locale text contains malformed placeholders") from exc


def _single_emoji(value: str) -> bool:
    """Accept one Unicode emoji grapheme without adding a heavy dependency."""
    if not value or len(value) > 16 or any(char.isspace() for char in value):
        return False
    emoji_like = any(
        unicodedata.category(char) in {"So", "Sk", "Sm"}
        or ord(char) == 0x20E3
        or 0x1F000 <= ord(char) <= 0x1FAFF
        for char in value
    )
    if not emoji_like:
        return False
    if "\u200d" in value:
        return any(
            unicodedata.category(char) in {"So", "Sk"} for char in value
        )
    ignored = {"\ufe0e", "\ufe0f", "\u20e3"}
    bases = [
        char for char in value
        if char not in ignored
        and not unicodedata.combining(char)
        and not 0x1F3FB <= ord(char) <= 0x1F3FF
    ]
    if len(bases) == 1:
        return True
    return len(bases) == 2 and all(
        0x1F1E6 <= ord(char) <= 0x1F1FF for char in bases
    )



class ThemeManager:
    def __init__(self, config, language, database, logger) -> None:
        self.config = config
        self.language = language
        self.db = database
        self.logger = logger
        self.lock = asyncio.Lock()
        self.themes: dict[str, Theme] = {}
        self.active_id = "premium"
        self._builtins: set[str] = set()
        self._runtime_overrides: dict[str, str] = {}
        self._theme_dir = Path(__file__).resolve().parents[1] / "themes"

    @property
    def active(self) -> Theme:
        return self.themes[self.active_id]

    def is_builtin(self, theme_id: str) -> bool:
        return theme_id in self._builtins

    @property
    def editable(self) -> bool:
        return not self.active.builtin

    def _normalize_config(self, values: dict) -> dict:
        if not isinstance(values, dict):
            raise ThemeError("config must be an object")
        unknown = set(values) - set(self.config.RUNTIME_FIELDS)
        if unknown:
            raise ThemeError("Unknown config key: " + sorted(unknown)[0])
        snapshot = {
            key: getattr(self.config, attr)
            for key, attr in self.config.RUNTIME_FIELDS.items()
        }
        normalized = {}
        try:
            for key, value in values.items():
                raw = self.config.runtime_import_value(key, value)
                self.config.set_runtime(key, raw)
                normalized[key] = self.config.runtime_export(key)
        except (TypeError, ValueError) as exc:
            raise ThemeError(str(exc)) from exc
        finally:
            for key, value in snapshot.items():
                setattr(self.config, self.config.RUNTIME_FIELDS[key], value)
        return normalized

    @staticmethod
    def _validate_table(value: object, label: str) -> dict:
        if not isinstance(value, dict):
            raise ThemeError(f"{label} must be an object")
        allowed = {
            "bordered", "striped", "header_alignment", "value_alignment",
            "expandable",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ThemeError(f"Unknown {label} key: {sorted(unknown)[0]}")
        result = {}
        for key in ("bordered", "striped", "expandable"):
            if key in value:
                if value[key] is not None and not isinstance(value[key], bool):
                    raise ThemeError(f"{label}.{key} must be true, false, or null")
                result[key] = value[key]
        for key in ("header_alignment", "value_alignment"):
            if key in value:
                if value[key] not in {None, "left", "center", "right"}:
                    raise ThemeError(f"{label}.{key} has an invalid alignment")
                result[key] = value[key]
        return result

    @staticmethod
    def _validate_emojis(value: object) -> dict:
        if not isinstance(value, dict):
            raise ThemeError("emojis must be an object")
        unknown = set(value) - {"mode", "registry", "placements"}
        if unknown:
            raise ThemeError("Unknown emojis key: " + sorted(unknown)[0])
        mode = value.get("mode", "custom")
        if mode not in {"native", "custom", "none"}:
            raise ThemeError("Emoji mode must be native, custom, or none")
        registry = value.get("registry", {})
        if not isinstance(registry, dict) or len(registry) > 128:
            raise ThemeError("Emoji registry must contain at most 128 tokens")
        clean_registry = {}
        for name, token in registry.items():
            if not isinstance(name, str) or not re.fullmatch(
                r"[a-z][a-z0-9_.-]{0,47}", name
            ):
                raise ThemeError("Emoji token names must be lowercase identifiers")
            if not isinstance(token, dict) or set(token) - {
                "native", "custom_emoji_id", "hidden",
            }:
                raise ThemeError(f"Emoji token {name} is invalid")
            native = token.get("native")
            if not isinstance(native, str) or not _single_emoji(native):
                raise ThemeError(f"Emoji token {name} needs one native emoji")
            custom_id = token.get("custom_emoji_id")
            if custom_id is not None and (
                not isinstance(custom_id, str)
                or not custom_id.isdecimal()
                or len(custom_id) > 32
            ):
                raise ThemeError(f"Emoji token {name} has an invalid custom id")
            hidden = token.get("hidden", False)
            if not isinstance(hidden, bool):
                raise ThemeError(f"Emoji token {name}.hidden must be boolean")
            clean_registry[name] = {
                "native": native,
                "custom_emoji_id": custom_id,
                "hidden": hidden,
            }
        placements = value.get("placements", {})
        if not isinstance(placements, dict):
            raise ThemeError("Emoji placements must be an object")
        unknown = set(placements) - set(EMOJI_PLACEMENTS)
        if unknown:
            raise ThemeError("Unknown emoji placement group: " + sorted(unknown)[0])
        clean_placements = {}
        for group, mappings in placements.items():
            if not isinstance(mappings, dict):
                raise ThemeError(f"Emoji placements.{group} must be an object")
            invalid = set(mappings) - EMOJI_PLACEMENTS[group]
            if invalid:
                raise ThemeError("Unknown emoji placement: " + sorted(invalid)[0])
            if any(
                token is not None and not isinstance(token, str)
                for token in mappings.values()
            ):
                raise ThemeError("Emoji placement values must be token names or null")
            missing = {
                token for token in mappings.values()
                if token is not None and token not in clean_registry
            }
            if missing:
                raise ThemeError("Unknown emoji token: " + sorted(missing)[0])
            clean_placements[group] = copy.deepcopy(mappings)
        return {
            "mode": mode,
            "registry": clean_registry,
            "placements": clean_placements,
        }

    def _validate_ui(self, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ThemeError("ui must be an object")
        allowed = {
            "heading_font", "icons", "heading_alignment", "separators",
            "media_placement", "tables", "surfaces", "keyboards", "emojis",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ThemeError("Unknown ui key: " + sorted(unknown)[0])
        result = {}
        if "heading_font" in value:
            if value["heading_font"] not in {"plain", "small_caps"}:
                raise ThemeError("heading_font must be plain or small_caps")
            result["heading_font"] = value["heading_font"]
        for key in ("icons", "separators"):
            if key in value:
                if not isinstance(value[key], bool):
                    raise ThemeError(f"{key} must be true or false")
                result[key] = value[key]
        if "heading_alignment" in value:
            if value["heading_alignment"] not in {"left", "center"}:
                raise ThemeError("heading_alignment must be left or center")
            result["heading_alignment"] = value["heading_alignment"]
        if "media_placement" in value:
            if value["media_placement"] not in {
                "automatic", "before", "after_heading",
            }:
                raise ThemeError("Invalid media placement")
            result["media_placement"] = value["media_placement"]
        if "tables" in value:
            result["tables"] = self._validate_table(value["tables"], "tables")
        surfaces = value.get("surfaces", {})
        if not isinstance(surfaces, dict):
            raise ThemeError("surfaces must be an object")
        unknown = set(surfaces) - SURFACES
        if unknown:
            raise ThemeError("Unknown surface: " + sorted(unknown)[0])
        result["surfaces"] = {}
        for surface, options in surfaces.items():
            if not isinstance(options, dict):
                raise ThemeError(f"Surface {surface} must be an object")
            allowed_surface = {
                "heading_level", "heading_alignment", "icon", "tables",
                "separators", "media_placement",
            }
            extra = set(options) - allowed_surface
            if extra:
                raise ThemeError(
                    f"Unknown {surface} option: {sorted(extra)[0]}"
                )
            clean = {}
            if "heading_level" in options:
                if options["heading_level"] not in {1, 2, 3}:
                    raise ThemeError("heading_level must be 1, 2, or 3")
                clean["heading_level"] = options["heading_level"]
            if "heading_alignment" in options:
                if options["heading_alignment"] not in {"left", "center"}:
                    raise ThemeError("Invalid surface heading alignment")
                clean["heading_alignment"] = options["heading_alignment"]
            if "icon" in options:
                if not isinstance(options["icon"], str) or len(options["icon"]) > 8:
                    raise ThemeError("Surface icon must be at most 8 characters")
                clean["icon"] = options["icon"]
            if "separators" in options:
                if not isinstance(options["separators"], bool):
                    raise ThemeError("Surface separators must be true or false")
                clean["separators"] = options["separators"]
            if "media_placement" in options:
                if options["media_placement"] not in {
                    "automatic", "before", "after_heading",
                }:
                    raise ThemeError("Invalid surface media placement")
                clean["media_placement"] = options["media_placement"]
            if "tables" in options:
                clean["tables"] = self._validate_table(
                    options["tables"], f"surfaces.{surface}.tables"
                )
            result["surfaces"][surface] = clean
        keyboards = value.get("keyboards", {})
        if not isinstance(keyboards, dict):
            raise ThemeError("keyboards must be an object")
        unknown = set(keyboards) - set(KEYBOARD_ACTIONS)
        if unknown:
            raise ThemeError("Unknown keyboard: " + sorted(unknown)[0])
        result["keyboards"] = {}
        for name, rows in keyboards.items():
            if not isinstance(rows, list) or any(
                not isinstance(row, list) or not row for row in rows
            ):
                raise ThemeError(f"Keyboard {name} must be an array of rows")
            actions = [action for row in rows for action in row]
            if any(not isinstance(action, str) for action in actions):
                raise ThemeError("Keyboard actions must be strings")
            if len(actions) != len(set(actions)):
                raise ThemeError(f"Keyboard {name} contains duplicate actions")
            invalid = set(actions) - KEYBOARD_ACTIONS[name]
            if invalid:
                raise ThemeError("Unknown keyboard action: " + sorted(invalid)[0])
            result["keyboards"][name] = copy.deepcopy(rows)
        if "emojis" in value:
            result["emojis"] = self._validate_emojis(value["emojis"])
        return result

    def _validate_locales(self, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ThemeError("locales must be an object")
        unknown_languages = set(value) - set(self.language.languages)
        if unknown_languages:
            raise ThemeError("Unknown locale: " + sorted(unknown_languages)[0])
        result = {}
        for code, overrides in value.items():
            if not isinstance(overrides, dict):
                raise ThemeError(f"Locale {code} must be an object")
            unknown = set(overrides) - set(self.language.languages[code])
            if unknown:
                raise ThemeError("Unknown locale key: " + sorted(unknown)[0])
            result[code] = {}
            for key, text in overrides.items():
                if not isinstance(text, str) or len(text) > 4096:
                    raise ThemeError(f"Locale value {code}.{key} is invalid")
                expected = _format_fields(str(self.language.languages[code][key]))
                if _format_fields(text) != expected:
                    raise ThemeError(f"Placeholders do not match for {code}.{key}")
                result[code][key] = text
        return result

    def validate(self, document: dict, *, builtin: bool = False) -> Theme:
        if not isinstance(document, dict):
            raise ThemeError("Theme document must be a JSON object")
        unknown = set(document) - THEME_ROOT_KEYS
        if unknown:
            raise ThemeError("Unknown theme key: " + sorted(unknown)[0])
        schema_ref = document.get("$schema")
        if schema_ref is not None and schema_ref != THEME_SCHEMA_REF:
            raise ThemeError(
                f"Unsupported theme schema reference; use {THEME_SCHEMA_REF}"
            )
        source_version = document.get("schema_version")
        if source_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ThemeError(
                f"Unsupported theme schema version; use {SCHEMA_VERSION}"
            )
        document = copy.deepcopy(document)
        document["schema_version"] = SCHEMA_VERSION
        theme_id = document.get("id")
        if not isinstance(theme_id, str) or not THEME_ID_RE.fullmatch(theme_id):
            raise ThemeError("Theme id must be a lowercase slug up to 32 characters")
        metadata = {}
        for key, limit in {
            "name": 64, "description": 300, "author": 64, "version": 32,
        }.items():
            value = document.get(key, "")
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ThemeError(f"Theme {key} is required and must be at most {limit} characters")
            metadata[key] = value.strip()
        return Theme(
            SCHEMA_VERSION,
            theme_id,
            metadata["name"],
            metadata["description"],
            metadata["author"],
            metadata["version"],
            self._normalize_config(document.get("config", {})),
            self._validate_ui(document.get("ui", {})),
            self._validate_locales(document.get("locales", {})),
            builtin,
        )

    async def _load_themes(self) -> None:
        loaded = {}
        builtins = set()
        for path in sorted(self._theme_dir.glob("*.json")):
            if path.name == "theme.schema.json":
                continue
            document = json.loads(path.read_text(encoding="utf-8"))
            theme = self.validate(document, builtin=True)
            loaded[theme.id] = theme
            builtins.add(theme.id)
        for theme_id, document in (await self.db.get_theme_manifests()).items():
            try:
                theme = self.validate(document)
            except ThemeError as exc:
                self.logger.warning("Ignored invalid theme %s: %s", theme_id, exc)
                continue
            if theme.id in builtins:
                self.logger.warning("Ignored custom theme shadowing built-in: %s", theme.id)
                continue
            loaded[theme.id] = theme
        self.themes = loaded
        self._builtins = builtins

    def _effective_document(
        self, theme: Theme, overrides: dict[str, object]
    ) -> dict:
        document = theme.document()
        for path, value in overrides.items():
            section, separator, key = path.partition(".")
            if not separator or section not in {"config", "ui", "locales"}:
                continue
            if section == "config":
                document[section][key] = value
            elif section == "ui":
                document[section][key] = copy.deepcopy(value)
        return document

    async def resolved(self, theme_id: str | None = None) -> Theme:
        theme = self.themes[theme_id or self.active_id]
        overrides = (
            {} if theme.builtin else await self.db.get_theme_overrides(theme.id)
        )
        document = self._effective_document(theme, overrides)
        return self.validate(document, builtin=theme.builtin)

    def _apply(self, theme: Theme) -> None:
        from anony.core.rich_messages import set_theme_ui

        for key in self.config.RUNTIME_FIELDS:
            self.config.reset_runtime(key)
        for key, value in theme.config.items():
            self.config.set_runtime(
                key, self.config.runtime_import_value(key, value)
            )
        for key, value in self._runtime_overrides.items():
            self.config.set_runtime(key, value)
        ui = _merge(APP_UI_DEFAULTS, theme.ui)
        set_theme_ui(ui)
        self.language.apply_theme(theme.locales)
        self.db.lang.clear()

    async def boot(self) -> None:
        async with self.lock:
            await self._load_themes()
            migrated = await self.db.get_setting_value("theme_migration_v1")
            active = await self.db.get_setting_value("active_theme")
            if not migrated:
                legacy = await self.db.get_runtime_config()
                manifest = None
                if legacy:
                    current_id = "current"
                    suffix = 2
                    while current_id in self.themes:
                        current_id = f"current-{suffix}"
                        suffix += 1
                    manifest = {
                        "schema_version": SCHEMA_VERSION,
                        "id": current_id,
                        "name": "Current",
                        "description": "Configuration preserved during theme migration.",
                        "author": "Migration",
                        "version": "1.0.0",
                        "config": {
                            key: self.config.runtime_export(key)
                            for key in self.config.RUNTIME_FIELDS
                        },
                        "ui": copy.deepcopy(APP_UI_DEFAULTS),
                        "locales": {},
                    }
                    manifest = self.validate(manifest).document()
                    active = current_id
                else:
                    active = "premium"
                await self.db.complete_theme_migration(active, manifest)
                await self._load_themes()
            if active not in self.themes:
                active = "premium" if "premium" in self.themes else "default"
                await self.db.set_setting_value("active_theme", active)
            self.active_id = active
            if not await self.db.get_setting_value("runtime_config_v2"):
                legacy_overrides = (
                    {} if self.active.builtin
                    else await self.db.get_theme_overrides(active)
                )
                migrated = {}
                for path, value in legacy_overrides.items():
                    if not path.startswith("config."):
                        continue
                    key = path.removeprefix("config.")
                    if key not in self.config.RUNTIME_FIELDS:
                        continue
                    raw = self.config.runtime_import_value(key, value)
                    migrated[key] = self.config.set_runtime(key, raw)
                await self.db.migrate_theme_config_to_runtime(
                    active, migrated
                )
            self._runtime_overrides = await self.db.get_runtime_config()
            self._apply(await self.resolved(active))

    async def activate(self, theme_id: str) -> Theme:
        async with self.lock:
            if theme_id not in self.themes:
                raise ThemeError("Theme not found")
            target = await self.resolved(theme_id)
            previous_id = self.active_id
            previous = await self.resolved(previous_id)
            try:
                self._apply(target)
                await self.db.set_setting_value("active_theme", theme_id)
            except Exception:
                self._apply(previous)
                self.active_id = previous_id
                raise
            self.active_id = theme_id
            return target

    async def emoji_overridden(self) -> bool:
        if self.active.builtin:
            return False
        overrides = await self.db.get_theme_overrides(self.active_id)
        return "ui.emojis" in overrides

    async def set_emojis(self, value: dict) -> dict:
        async with self.lock:
            if not self.editable:
                raise ThemeError("Clone this built-in theme before editing it")
            normalized = self._validate_emojis(value)
            theme_id = self.active_id
            path = "ui.emojis"
            previous = await self.resolved(theme_id)
            overrides = await self.db.get_theme_overrides(theme_id)
            await self.db.set_theme_override(theme_id, path, normalized)
            try:
                self._apply(await self.resolved(theme_id))
            except Exception:
                if path in overrides:
                    await self.db.set_theme_override(
                        theme_id, path, overrides[path]
                    )
                else:
                    await self.db.reset_theme_override(theme_id, path)
                self._apply(previous)
                raise
            return copy.deepcopy(normalized)

    async def update_emoji_token(
        self,
        token: str,
        *,
        native: str | None = None,
        custom_emoji_id: str | None | object = ...,
        hidden: bool | None = None,
    ) -> dict:
        emojis = copy.deepcopy(self.ui().get("emojis", {}))
        registry = emojis.setdefault("registry", {})
        if token not in registry:
            raise ThemeError("Emoji token not found")
        if native is not None:
            registry[token]["native"] = native
        if custom_emoji_id is not ...:
            registry[token]["custom_emoji_id"] = custom_emoji_id
        if hidden is not None:
            registry[token]["hidden"] = hidden
        return await self.set_emojis(emojis)

    async def reset_emojis(self) -> None:
        async with self.lock:
            if not self.editable:
                raise ThemeError("Built-in themes cannot be edited")
            theme_id = self.active_id
            previous = await self.resolved(theme_id)
            overrides = await self.db.get_theme_overrides(theme_id)
            await self.db.reset_theme_override(theme_id, "ui.emojis")
            try:
                self._apply(await self.resolved(theme_id))
            except Exception:
                if "ui.emojis" in overrides:
                    await self.db.set_theme_override(
                        theme_id, "ui.emojis", overrides["ui.emojis"]
                    )
                self._apply(previous)
                raise


    async def config_overrides(self) -> dict[str, str]:
        return copy.deepcopy(self._runtime_overrides)

    async def set_config(self, key: str, raw_value: str) -> object:
        async with self.lock:
            if key not in self.config.RUNTIME_FIELDS:
                raise ThemeError("Setting not found")
            previous = copy.deepcopy(self._runtime_overrides)
            current_theme = await self.resolved(self.active_id)
            try:
                stored = self.config.set_runtime(key, raw_value)
                await self.db.set_runtime_config(key, stored)
                self._runtime_overrides[key] = stored
                self._apply(current_theme)
            except Exception:
                self._runtime_overrides = previous
                if key in previous:
                    await self.db.set_runtime_config(key, previous[key])
                else:
                    await self.db.reset_runtime_config(key)
                self._apply(current_theme)
                raise
            return self.config.runtime_export(key)

    async def reset_config(self, key: str) -> None:
        async with self.lock:
            if key not in self.config.RUNTIME_FIELDS:
                raise ThemeError("Setting not found")
            previous = copy.deepcopy(self._runtime_overrides)
            current_theme = await self.resolved(self.active_id)
            try:
                await self.db.reset_runtime_config(key)
                self._runtime_overrides.pop(key, None)
                self._apply(current_theme)
            except Exception:
                self._runtime_overrides = previous
                if key in previous:
                    await self.db.set_runtime_config(key, previous[key])
                self._apply(current_theme)
                raise

    async def reset_all_config(self) -> None:
        async with self.lock:
            previous = copy.deepcopy(self._runtime_overrides)
            current_theme = await self.resolved(self.active_id)
            try:
                await self.db.reset_all_runtime_config()
                self._runtime_overrides.clear()
                self._apply(current_theme)
            except Exception:
                self._runtime_overrides = previous
                for key, value in previous.items():
                    await self.db.set_runtime_config(key, value)
                self._apply(current_theme)
                raise

    def unique_id(self, name: str) -> str:
        base = slugify(name)
        candidate = base
        suffix = 2
        while candidate in self.themes:
            tail = f"-{suffix}"
            candidate = base[:32 - len(tail)].rstrip("-") + tail
            suffix += 1
        return candidate

    async def create(self, name: str, *, clone_id: str | None = None) -> Theme:
        async with self.lock:
            return await self._create_unlocked(name, clone_id=clone_id)

    async def _create_unlocked(
        self, name: str, *, clone_id: str | None = None
    ) -> Theme:
        theme_id = self.unique_id(name)
        if clone_id:
            source = await self.resolved(clone_id)
            document = source.document()
            document["config"] = copy.deepcopy(source.config)
            document["ui"] = _merge(APP_UI_DEFAULTS, source.ui)
            document["locales"] = copy.deepcopy(source.locales)
        else:
            document = {
                "schema_version": SCHEMA_VERSION,
                "config": {},
                "ui": copy.deepcopy(APP_UI_DEFAULTS),
                "locales": {},
            }
        document.update({
            "id": theme_id,
            "name": name.strip(),
            "description": "Created in Telegram.",
            "author": "Bot administrator",
            "version": "1.0.0",
        })
        theme = self.validate(document)
        await self.db.save_theme_manifest(theme.id, theme.document())
        self.themes[theme.id] = theme
        return theme

    async def install(self, document: dict, *, replace_existing: bool = False) -> Theme:
        async with self.lock:
            return await self._install_unlocked(
                document, replace_existing=replace_existing
            )

    async def _install_unlocked(
        self, document: dict, *, replace_existing: bool = False
    ) -> Theme:
        theme = self.validate(document)
        if theme.id in self._builtins:
            raise ThemeError("A runtime theme cannot replace a built-in theme")
        if theme.id in self.themes and not replace_existing:
            raise ThemeError("A theme with this id already exists")
        await self.db.save_theme_manifest(theme.id, theme.document())
        self.themes[theme.id] = theme
        if replace_existing:
            await self.db.reset_theme_overrides(theme.id)
        if theme.id == self.active_id:
            self._apply(theme)
        return theme

    async def rename(self, theme_id: str, name: str) -> Theme:
        async with self.lock:
            return await self._rename_unlocked(theme_id, name)

    async def _rename_unlocked(self, theme_id: str, name: str) -> Theme:
        theme = self.themes.get(theme_id)
        if theme is None or theme.builtin:
            raise ThemeError("Only custom themes can be renamed")
        if not name.strip() or len(name.strip()) > 64:
            raise ThemeError("Theme name must be 1 to 64 characters")
        updated = replace(theme, name=name.strip())
        await self.db.save_theme_manifest(theme_id, updated.document())
        self.themes[theme_id] = updated
        return updated

    async def delete(self, theme_id: str) -> None:
        async with self.lock:
            await self._delete_unlocked(theme_id)

    async def _delete_unlocked(self, theme_id: str) -> None:
        theme = self.themes.get(theme_id)
        if theme is None or theme.builtin:
            raise ThemeError("Built-in themes cannot be deleted")
        if theme_id == self.active_id:
            raise ThemeError("Switch themes before deleting the active theme")
        await self.db.delete_theme_manifest(theme_id)
        self.themes.pop(theme_id, None)

    async def export(self, theme_id: str) -> dict:
        theme = await self.resolved(theme_id)
        document = theme.document()
        document["config"] = copy.deepcopy(theme.config)
        document["ui"] = _merge(APP_UI_DEFAULTS, theme.ui)
        return document

    def ui(self) -> dict:
        from anony.core.rich_messages import get_theme_ui

        return get_theme_ui()
