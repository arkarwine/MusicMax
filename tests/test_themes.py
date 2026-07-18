import copy
import importlib.util
import json
import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]

CONFIG_SPEC = importlib.util.spec_from_file_location(
    "theme_config_under_test", ROOT / "config.py"
)
config_module = importlib.util.module_from_spec(CONFIG_SPEC)
CONFIG_SPEC.loader.exec_module(config_module)

THEME_SPEC = importlib.util.spec_from_file_location(
    "themes_under_test", ROOT / "anony/core/themes.py"
)
theme_module = importlib.util.module_from_spec(THEME_SPEC)
sys.modules[THEME_SPEC.name] = theme_module
THEME_SPEC.loader.exec_module(theme_module)


class FakeLanguage:
    def __init__(self):
        self.languages = {
            "en": {
                "greeting": "Hello {0}",
                "button": "Open",
                "play_message_template": "# Now playing\n{title_link}",
            },
            "my": {
                "greeting": "မင်္ဂလာပါ {0}",
                "button": "ဖွင့်ရန်",
                "play_message_template": "# Now playing\n{title_link}",
            },
        }
        self.applied = {}

    def apply_theme(self, overrides):
        self.applied = copy.deepcopy(overrides)


class FakeDB:
    def __init__(self, legacy=None):
        self.manifests = {}
        self.overrides = {}
        self.settings = {}
        self.legacy = dict(legacy or {})
        self.lang = {1: "en"}

    async def get_theme_manifests(self):
        return copy.deepcopy(self.manifests)

    async def save_theme_manifest(self, theme_id, manifest):
        self.manifests[theme_id] = copy.deepcopy(manifest)

    async def delete_theme_manifest(self, theme_id):
        self.manifests.pop(theme_id, None)
        self.overrides.pop(theme_id, None)

    async def get_theme_overrides(self, theme_id):
        return copy.deepcopy(self.overrides.get(theme_id, {}))

    async def set_theme_override(self, theme_id, path, value):
        self.overrides.setdefault(theme_id, {})[path] = copy.deepcopy(value)

    async def reset_theme_override(self, theme_id, path):
        self.overrides.setdefault(theme_id, {}).pop(path, None)

    async def reset_theme_overrides(self, theme_id, prefix=None):
        if prefix is None:
            self.overrides.pop(theme_id, None)
            return
        values = self.overrides.setdefault(theme_id, {})
        for path in list(values):
            if path.startswith(prefix):
                values.pop(path)

    async def get_setting_value(self, key):
        return self.settings.get(key)

    async def set_setting_value(self, key, value):
        self.settings[key] = value

    async def get_runtime_config(self):
        return dict(self.legacy)

    async def set_runtime_config(self, key, value):
        self.legacy[key] = value

    async def reset_runtime_config(self, key):
        self.legacy.pop(key, None)

    async def reset_all_runtime_config(self):
        self.legacy.clear()

    async def migrate_theme_config_to_runtime(self, theme_id, values):
        self.legacy.update(values)
        for overrides in self.overrides.values():
            for path in list(overrides):
                if path.startswith("config."):
                    overrides.pop(path)
        self.settings["runtime_config_v2"] = "1"

    async def complete_theme_migration(self, active_theme, manifest=None):
        if manifest:
            self.manifests[manifest["id"]] = copy.deepcopy(manifest)
        self.settings["active_theme"] = active_theme
        self.settings["theme_migration_v1"] = "1"
        self.legacy.clear()


class ThemeManagerTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved_modules = {
            name: sys.modules.get(name)
            for name in ("anony", "anony.core", "anony.core.rich_messages")
        }
        fake_anony = types.ModuleType("anony")
        fake_anony.__path__ = []
        fake_core = types.ModuleType("anony.core")
        fake_core.__path__ = []
        fake_rich = types.ModuleType("anony.core.rich_messages")
        fake_rich.ui = {}

        def set_theme_ui(value):
            fake_rich.ui = copy.deepcopy(value)

        def get_theme_ui():
            return copy.deepcopy(fake_rich.ui)

        fake_rich.set_theme_ui = set_theme_ui
        fake_rich.get_theme_ui = get_theme_ui
        sys.modules.update({
            "anony": fake_anony,
            "anony.core": fake_core,
            "anony.core.rich_messages": fake_rich,
        })

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.saved_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def manager(self, *, legacy=None):
        config = config_module.Config()
        language = FakeLanguage()
        db = FakeDB(legacy)
        manager = theme_module.ThemeManager(
            config, language, db, logging.getLogger(__name__)
        )
        manager._theme_dir = ROOT / "anony/themes"
        return manager, config, language, db

    async def test_boot_loads_builtins_and_activates_premium(self):
        manager, _, _, db = self.manager()
        await manager.boot()

        self.assertEqual(manager.active_id, "premium")
        self.assertEqual(set(manager.themes), {"default", "premium"})
        self.assertTrue(manager.themes["default"].builtin)
        self.assertEqual(db.settings["theme_migration_v1"], "1")

    async def test_migration_preserves_effective_config_as_current(self):
        manager, config, _, db = self.manager(legacy={"queue_limit": "77"})
        config.set_runtime("queue_limit", "77")
        await manager.boot()

        self.assertEqual(manager.active.name, "Current")
        self.assertEqual(config.QUEUE_LIMIT, 77)
        self.assertEqual(manager.active.config["queue_limit"], 77)
        self.assertFalse(db.legacy)

    async def test_runtime_overrides_survive_theme_changes_and_reset(self):
        manager, config, _, db = self.manager()
        await manager.boot()

        await manager.set_config("queue_limit", "77")
        self.assertEqual(config.QUEUE_LIMIT, 77)
        self.assertEqual(db.legacy["queue_limit"], "77")

        custom = await manager.create("Night", clone_id="premium")
        await manager.activate(custom.id)
        self.assertEqual(config.QUEUE_LIMIT, 77)
        await manager.activate("default")
        self.assertEqual(config.QUEUE_LIMIT, 77)

        await manager.reset_config("queue_limit")
        self.assertNotIn("queue_limit", db.legacy)
        self.assertEqual(
            config.QUEUE_LIMIT,
            config._runtime_defaults["queue_limit"],
        )

    async def test_builtin_settings_are_editable_but_themes_remain_read_only(self):
        manager, config, _, _ = self.manager()
        await manager.boot()
        await manager.set_config("queue_limit", "50")
        self.assertEqual(config.QUEUE_LIMIT, 50)
        with self.assertRaisesRegex(theme_module.ThemeError, "built-in"):
            await manager.set_emojis(manager.ui()["emojis"])

        custom = await manager.create("Editable", clone_id="premium")
        await manager.activate(custom.id)
        with self.assertRaisesRegex(theme_module.ThemeError, "Switch"):
            await manager.delete(custom.id)

    async def test_export_import_round_trip_is_complete(self):
        manager, config, _, _ = self.manager()
        await manager.boot()
        custom = await manager.create("Portable", clone_id="premium")
        await manager.activate(custom.id)
        await manager.set_config("auto_end", "on")
        exported = await manager.export(custom.id)

        self.assertEqual(exported["config"], {})
        self.assertTrue(config.AUTO_END)
        exported["id"] = "portable-copy"
        installed = await manager.install(exported)
        self.assertNotIn("auto_end", installed.config)

    async def test_validation_rejects_schema_keys_placeholders_and_actions(self):
        manager, _, _, _ = self.manager()
        base = json.loads(
            (ROOT / "anony/themes/premium.json").read_text(encoding="utf-8")
        )
        invalid = copy.deepcopy(base)
        invalid["schema_version"] = 3
        with self.assertRaisesRegex(theme_module.ThemeError, "schema"):
            manager.validate(invalid)

        invalid = copy.deepcopy(base)
        invalid["$schema"] = "https://example.com/untrusted.schema.json"
        with self.assertRaisesRegex(theme_module.ThemeError, "schema reference"):
            manager.validate(invalid)


        invalid = copy.deepcopy(base)
        invalid["config"]["bot_token"] = "secret"
        with self.assertRaisesRegex(theme_module.ThemeError, "Unknown config"):
            manager.validate(invalid)

        invalid = copy.deepcopy(base)
        invalid["locales"] = {"en": {"greeting": "Hello {1}"}}
        with self.assertRaisesRegex(theme_module.ThemeError, "Placeholders"):
            manager.validate(invalid)

        invalid = copy.deepcopy(base)
        invalid["ui"]["keyboards"] = {"help": [["execute_code"]]}
        with self.assertRaisesRegex(theme_module.ThemeError, "keyboard action"):
            manager.validate(invalid)

    async def test_typed_values_and_media_file_ids_are_validated(self):
        manager, _, _, _ = self.manager()
        base = json.loads(
            (ROOT / "anony/themes/default.json").read_text(encoding="utf-8")
        )
        base["id"] = "typed"
        base["name"] = "Typed"
        base["config"] = {
            "queue_limit": 25,
            "auto_end": True,
            "play_controls_layout": [["pause", "skip"], ["stop"]],
            "play_image": "AgACAgQAAxkBAAIBExampleFileId123456789",
            "play_message_template_en": None,
        }
        theme = manager.validate(base)

        self.assertEqual(theme.config["queue_limit"], 25)
        self.assertTrue(theme.config["auto_end"])
        self.assertEqual(
            theme.config["play_controls_layout"],
            [["pause", "skip"], ["stop"]],
        )
        self.assertIsNone(theme.config["play_message_template_en"])


    async def test_activation_failure_rolls_back_memory_and_persistence(self):
        manager, config, _, db = self.manager()
        await manager.boot()
        previous_queue = config.QUEUE_LIMIT
        original_apply = manager._apply

        def fail_default(theme):
            if theme.id == "default":
                raise RuntimeError("renderer failed")
            original_apply(theme)

        manager._apply = fail_default
        with self.assertRaisesRegex(RuntimeError, "renderer failed"):
            await manager.activate("default")

        self.assertEqual(manager.active_id, "premium")
        self.assertEqual(db.settings["active_theme"], "premium")
        self.assertEqual(config.QUEUE_LIMIT, previous_queue)

    async def test_config_apply_failure_restores_override_and_values(self):
        manager, config, _, db = self.manager()
        await manager.boot()
        custom = await manager.create("Rollback", clone_id="premium")
        await manager.activate(custom.id)
        previous_queue = config.QUEUE_LIMIT
        original_apply = manager._apply
        attempts = 0

        def fail_once(theme):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("locale refresh failed")
            original_apply(theme)

        manager._apply = fail_once
        with self.assertRaisesRegex(RuntimeError, "locale refresh failed"):
            await manager.set_config("queue_limit", "88")

        self.assertNotIn("queue_limit", db.legacy)
        self.assertEqual(config.QUEUE_LIMIT, previous_queue)

    async def test_legacy_theme_config_edits_migrate_to_runtime(self):
        manager, config, _, db = self.manager()
        db.settings.update({
            "theme_migration_v1": "1",
            "active_theme": "legacy-theme",
        })
        manifest = json.loads(
            (ROOT / "anony/themes/default.json").read_text(encoding="utf-8")
        )
        manifest.update({"id": "legacy-theme", "name": "Legacy"})
        db.manifests["legacy-theme"] = manifest
        db.overrides["legacy-theme"] = {
            "config.queue_limit": 73,
            "ui.heading_alignment": "center",
        }

        await manager.boot()

        self.assertEqual(config.QUEUE_LIMIT, 73)
        self.assertEqual(db.legacy["queue_limit"], "73")
        self.assertNotIn(
            "config.queue_limit", db.overrides["legacy-theme"]
        )
        self.assertIn(
            "ui.heading_alignment", db.overrides["legacy-theme"]
        )

    async def test_runtime_import_cannot_shadow_a_builtin(self):
        manager, _, _, _ = self.manager()
        await manager.boot()
        document = json.loads(
            (ROOT / "anony/themes/default.json").read_text(encoding="utf-8")
        )
        with self.assertRaisesRegex(theme_module.ThemeError, "built-in"):
            await manager.install(document, replace_existing=True)


class ThemeUiSourceTests(unittest.IsolatedAsyncioTestCase):
    manager = ThemeManagerTests.manager

    @classmethod
    def setUpClass(cls):
        ThemeManagerTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        ThemeManagerTests.tearDownClass.__func__(cls)

    def test_management_plugin_exposes_complete_lifecycle(self):
        source = (ROOT / "anony/plugins/themes.py").read_text(encoding="utf-8")
        for command in ("themes", "importtheme", "exporttheme"):
            self.assertIn(command, source)
        for action in (
            'theme("activate"', 'theme("clone"', 'theme("create"',
            'theme("import"', 'theme("export"', 'theme("rename"',
            'theme("delete"',
        ):
            self.assertIn(action, source)
        self.assertIn("ForceReply", source)

    def test_database_schema_has_theme_foreign_key_and_migration_marker(self):
        source = (ROOT / "anony/core/database.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS themes", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS theme_overrides", source)
        self.assertIn("REFERENCES themes(theme_id)", source)
        self.assertIn("theme_migration_v1", source)
        self.assertIn("runtime_config_v2", source)


    async def test_schema_v1_normalizes_and_emoji_schema_is_strict(self):
        manager, _, _, _ = self.manager()
        base = json.loads(
            (ROOT / "anony/themes/premium.json").read_text(encoding="utf-8")
        )
        legacy = copy.deepcopy(base)
        legacy["schema_version"] = 1
        legacy["ui"].pop("emojis")
        normalized = manager.validate(legacy)
        self.assertEqual(normalized.schema_version, 2)

        invalid = copy.deepcopy(base)
        invalid["ui"]["emojis"]["registry"]["music"]["native"] = "🎵🎵"
        with self.assertRaisesRegex(theme_module.ThemeError, "one native"):
            manager.validate(invalid)

        invalid = copy.deepcopy(base)
        invalid["ui"]["emojis"]["placements"]["headings"]["unknown"] = "music"
        with self.assertRaisesRegex(theme_module.ThemeError, "placement"):
            manager.validate(invalid)

    async def test_emoji_overrides_are_atomic_resettable_and_exported(self):
        manager, _, _, db = self.manager()
        await manager.boot()
        custom = await manager.create("Emoji Lab", clone_id="premium")
        await manager.activate(custom.id)

        emojis = manager.ui()["emojis"]
        emojis["mode"] = "native"
        await manager.set_emojis(emojis)
        await manager.update_emoji_token(
            "music", native="🎶", custom_emoji_id="123456"
        )

        self.assertTrue(await manager.emoji_overridden())
        self.assertEqual(manager.ui()["emojis"]["mode"], "native")
        self.assertEqual(
            manager.ui()["emojis"]["registry"]["music"]["native"], "🎶"
        )
        exported = await manager.export(custom.id)
        self.assertEqual(exported["$schema"], "./theme.schema.json")
        self.assertEqual(exported["schema_version"], 2)
        self.assertEqual(exported["ui"]["emojis"]["mode"], "native")
        self.assertIn("ui.emojis", await db.get_theme_overrides(custom.id))

        await manager.reset_emojis()
        self.assertFalse(await manager.emoji_overridden())
        self.assertEqual(manager.ui()["emojis"]["mode"], "custom")

if __name__ == "__main__":
    unittest.main()
