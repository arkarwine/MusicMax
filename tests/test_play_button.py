import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


spec = importlib.util.spec_from_file_location(
    "play_button_config_under_test",
    ROOT / "config.py",
)
config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config_module)


class PlaybackButtonConfigTests(unittest.TestCase):
    def setUp(self):
        self.config = config_module.Config()
        self.config.PLAY_BUTTON_TEXT = ""
        self.config.PLAY_BUTTON_URL = ""
        self.config.PLAY_IMAGE = ""
        self.config.PLAY_CONTROLS_LAYOUT = (
            self.config.DEFAULT_PLAY_CONTROLS_LAYOUT
        )

    def test_button_requires_valid_text_and_url(self):
        self.assertIsNone(self.config.playback_button())

        self.config.PLAY_BUTTON_TEXT = "Open channel"
        self.assertIsNone(self.config.playback_button())

        self.config.PLAY_BUTTON_URL = "@anonxmusic"
        self.assertEqual(
            self.config.playback_button(),
            ("Open channel", "https://t.me/anonxmusic"),
        )

        self.config.PLAY_BUTTON_URL = "not a url"
        self.assertIsNone(self.config.playback_button())

    def test_runtime_values_can_be_updated_and_disabled(self):
        self.assertEqual(
            self.config.set_runtime("play_button_text", " Open channel "),
            "Open channel",
        )
        self.assertEqual(
            self.config.set_runtime("play_button_url", "@anonxmusic"),
            "https://t.me/anonxmusic",
        )
        self.assertEqual(
            self.config.playback_button(),
            ("Open channel", "https://t.me/anonxmusic"),
        )

        self.config.set_runtime("play_button_url", "-")
        self.assertIsNone(self.config.playback_button())
        self.assertEqual(
            self.config.runtime_display("play_button_url"),
            "disabled",
        )

    def test_play_image_can_be_configured_and_disabled(self):
        self.assertIsNone(self.config.play_image_url())

        self.assertEqual(
            self.config.set_runtime("play_image", "@anonxmusic"),
            "https://t.me/anonxmusic",
        )
        self.assertEqual(
            self.config.play_image_url(),
            "https://t.me/anonxmusic",
        )

        self.config.set_runtime("play_image", "-")
        self.assertIsNone(self.config.play_image_url())
        self.assertEqual(
            self.config.runtime_display("play_image"),
            "disabled",
        )

    def test_invalid_environment_play_image_is_ignored(self):
        self.config.PLAY_IMAGE = "not a url"

        self.assertIsNone(self.config.play_image_url())

    def test_default_play_control_layout_preserves_classic_order(self):
        self.assertEqual(
            self.config.play_controls_layout(),
            (("loop", "stop", "pause", "skip", "replay"),),
        )

    def test_play_control_layout_supports_rows_and_omissions(self):
        stored = self.config.set_runtime(
            "play_controls_layout", " pause, skip | stop "
        )

        self.assertEqual(stored, "pause,skip|stop")
        self.assertEqual(
            self.config.play_controls_layout(),
            (("pause", "skip"), ("stop",)),
        )

    def test_play_control_layout_can_hide_all_controls(self):
        self.config.set_runtime("play_controls_layout", "-")

        self.assertEqual(self.config.play_controls_layout(), ())
        self.assertEqual(
            self.config.runtime_display("play_controls_layout"),
            "disabled",
        )

    def test_play_control_layout_reset_restores_environment_default(self):
        self.config._runtime_defaults["play_controls_layout"] = (
            self.config.DEFAULT_PLAY_CONTROLS_LAYOUT
        )
        self.config.set_runtime("play_controls_layout", "pause|stop")
        self.config.reset_runtime("play_controls_layout")

        self.assertEqual(
            self.config.play_controls_layout(),
            (("loop", "stop", "pause", "skip", "replay"),),
        )

    def test_play_control_layout_rejects_invalid_positions(self):
        invalid = (
            "pause,pause",
            "pause,unknown",
            "pause||stop",
            "pause,,stop",
            "",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.config.set_runtime("play_controls_layout", value)

    def test_controls_append_the_configured_url_button(self):
        tree = ast.parse(
            (ROOT / "anony/helpers/_inline.py").read_text(encoding="utf-8")
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "playback_button"
        ]
        url_keywords = [
            keyword
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for keyword in node.keywords
            if keyword.arg == "url"
        ]

        self.assertEqual(len(calls), 1)
        self.assertTrue(url_keywords)

    def test_controls_use_the_configured_layout(self):
        tree = ast.parse(
            (ROOT / "anony/helpers/_inline.py").read_text(encoding="utf-8")
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "play_controls_layout"
        ]

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
