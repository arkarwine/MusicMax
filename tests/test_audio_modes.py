import importlib.util
import json
import sqlite3
import unittest
from pathlib import Path

from pytgcalls.ffmpeg import _get_stream_params


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audio_modes_under_test",
    ROOT / "anony" / "core" / "audio.py",
)
audio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio)


class AudioModeTests(unittest.TestCase):
    def test_modes_cycle_in_display_order(self):
        self.assertEqual(audio.next_audio_mode("original"), "spatial")
        self.assertEqual(audio.next_audio_mode("spatial"), "hall")
        self.assertEqual(audio.next_audio_mode("hall"), "original")

    def test_invalid_modes_fall_back_to_original(self):
        self.assertEqual(audio.normalize_audio_mode(None), "original")
        self.assertEqual(audio.normalize_audio_mode("invalid"), "original")
        self.assertIsNone(audio.audio_filter("invalid"))

    def test_original_preserves_existing_ffmpeg_parameters(self):
        self.assertIsNone(audio.build_ffmpeg_parameters(0, "original"))
        self.assertEqual(
            audio.build_ffmpeg_parameters(42, "original"),
            "-ss 42",
        )

    def test_effect_modes_preserve_seek_and_add_one_audio_filter(self):
        for mode in ("spatial", "hall"):
            parameters = audio.build_ffmpeg_parameters(42, mode)
            self.assertTrue(parameters.startswith("-ss 42 ---mid -af \""))
            self.assertTrue(parameters.endswith("\""))
            self.assertIn("aformat=channel_layouts=stereo", parameters)
            self.assertIn("alimiter=limit=0.95", parameters)

        self.assertIn("stereowiden", audio.audio_filter("spatial"))
        self.assertIn("aecho", audio.audio_filter("hall"))

    def test_pytgcalls_places_seek_before_input_and_filter_after_it(self):
        parameters = audio.build_ffmpeg_parameters(42, "spatial")
        sections = _get_stream_params(parameters)["audio"]
        self.assertEqual(sections["start"], ["-ss", "42"])
        self.assertEqual(sections["mid"][0], "-af")
        self.assertEqual(sections["mid"][1], audio.audio_filter("spatial"))
        self.assertEqual(sections["end"], [])

    def test_persistence_playback_and_settings_are_wired(self):
        database = (ROOT / "anony/core/database.py").read_text(encoding="utf-8")
        calls = (ROOT / "anony/core/calls.py").read_text(encoding="utf-8")
        settings = (ROOT / "anony/helpers/_inline.py").read_text(encoding="utf-8")
        callbacks = (ROOT / "anony/plugins/callbacks.py").read_text(encoding="utf-8")

        self.assertIn("audio_mode TEXT NOT NULL DEFAULT 'original'", database)
        self.assertIn("async def get_audio_mode", database)
        self.assertIn("async def set_audio_mode", database)
        self.assertIn("build_ffmpeg_parameters(seek_time, audio_mode)", calls)
        self.assertIn('callback_data=callbacks.settings(chat_id, "audio")', settings)
        self.assertIn("await db.set_audio_mode(chat_id, _audio_mode)", callbacks)

    def test_all_locales_and_premium_theme_expose_the_modes(self):
        for code in ("en", "my"):
            locale = json.loads(
                (ROOT / f"anony/locales/{code}.json").read_text(encoding="utf-8")
            )
            for key in (
                "audio_mode",
                "setting_original",
                "setting_spatial",
                "setting_hall",
            ):
                self.assertTrue(locale[key])

        theme = json.loads(
            (ROOT / "anony/themes/premium.json").read_text(encoding="utf-8")
        )
        buttons = theme["ui"]["emojis"]["placements"]["buttons"]
        self.assertEqual(buttons["settings.audio_mode"], "music")

    def test_additive_sqlite_column_defaults_and_restricts_values(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE chats (chat_id INTEGER PRIMARY KEY)")
        connection.execute(
            "ALTER TABLE chats ADD COLUMN audio_mode "
            "TEXT NOT NULL DEFAULT 'original' "
            "CHECK (audio_mode IN ('original', 'spatial', 'hall'))"
        )
        connection.execute("INSERT INTO chats (chat_id) VALUES (1)")
        value = connection.execute(
            "SELECT audio_mode FROM chats WHERE chat_id = 1"
        ).fetchone()[0]
        self.assertEqual(value, "original")
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO chats (chat_id, audio_mode) VALUES (2, 'invalid')"
            )
        connection.close()


if __name__ == "__main__":
    unittest.main()
